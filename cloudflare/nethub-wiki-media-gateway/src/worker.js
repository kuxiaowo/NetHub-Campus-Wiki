const EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
const encoder = new TextEncoder();
let cachedHmacSecret = null;
let cachedHmacKey = null;

class HttpError extends Error {
  constructor(status, code, message, details) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function strictEncode(value) {
  return encodeURIComponent(value).replace(/[!'()*]/g, (char) => `%${char.charCodeAt(0).toString(16).toUpperCase()}`);
}

function csv(value, fallback = "") {
  return String(value || fallback)
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function boundedInteger(env, name, fallback, minimum, maximum) {
  const raw = env[name] ?? fallback;
  if (!/^\d+$/.test(String(raw))) throw new HttpError(503, "worker_not_configured", `${name} must be an integer`);
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw new HttpError(503, "worker_not_configured", `${name} is outside its safe range`);
  }
  return value;
}

function canonicalKeyFromEncoded(encodedKey) {
  if (!encodedKey || encodedKey.endsWith("/")) {
    throw new HttpError(400, "invalid_key", "Object key is empty or ends with a slash");
  }
  const decoded = encodedKey.split("/").map((part) => {
    if (!part) throw new HttpError(400, "invalid_key", "Object key contains an empty segment");
    let value;
    try {
      value = decodeURIComponent(part);
    } catch {
      throw new HttpError(400, "invalid_key", "Object key has invalid percent encoding");
    }
    value = value.normalize("NFC");
    if (value === "." || value === ".." || value.includes("/") || value.includes("\\") || value.includes("%") || /[\u0000-\u001f\u007f]/u.test(value)) {
      throw new HttpError(400, "invalid_key", "Object key contains a forbidden segment");
    }
    return value;
  });
  const key = decoded.join("/");
  if (encoder.encode(key).byteLength > 1024) throw new HttpError(414, "key_too_long", "Object key is too long");
  return { key, encoded: decoded.map(strictEncode).join("/") };
}

function normalizePrefix(value) {
  const raw = String(value || "").normalize("NFC");
  if (!raw || raw.startsWith("/") || raw.includes("\\") || raw.includes("%") || /[\u0000-\u001f\u007f]/u.test(raw)) {
    throw new HttpError(400, "invalid_prefix", "List prefix is invalid");
  }
  const trailingSlash = raw.endsWith("/");
  const parts = raw.split("/").filter((part, index, all) => !(trailingSlash && index === all.length - 1));
  if (parts.some((part) => !part || part === "." || part === "..")) {
    throw new HttpError(400, "invalid_prefix", "List prefix contains a forbidden segment");
  }
  return parts.join("/") + (trailingSlash ? "/" : "");
}

function configuredPrefixes(env, name, fallback) {
  return csv(env[name], fallback).map((prefix) => normalizePrefix(prefix.endsWith("/") ? prefix : `${prefix}/`));
}

function keyAllowed(key, prefixes) {
  return prefixes.some((prefix) => key.startsWith(prefix));
}

function extensionOf(key) {
  const file = key.slice(key.lastIndexOf("/") + 1);
  const dot = file.lastIndexOf(".");
  return dot > 0 ? file.slice(dot + 1).toLowerCase() : "";
}

function assertYearbookKeyClass(key) {
  const extension = extensionOf(key);
  if (key.startsWith("yearbook-pages/") && !["jpg", "jpeg", "png", "webp", "gif", "avif"].includes(extension)) {
    throw new HttpError(415, "forbidden_extension", "yearbook-pages only accepts page images");
  }
  if (key.startsWith("yearbook-pdfs/") && extension !== "pdf") {
    throw new HttpError(415, "forbidden_extension", "yearbook-pdfs only accepts PDF files");
  }
  if (key.startsWith("thumbnails/yearbook/") && extension !== "webp") {
    throw new HttpError(415, "forbidden_extension", "Yearbook thumbnails must be WebP files");
  }
}

function assertAllowedKey(key, env, isPublic = false) {
  const prefixes = configuredPrefixes(
    env,
    isPublic ? "PUBLIC_MEDIA_PREFIXES" : "ALLOWED_KEY_PREFIXES",
    isPublic ? "Photos/,avatars/,project-media/,thumbnails/,yearbook-pages/,video-thumbnails/,CAS/" : "Photos/,avatars/,project-media/,thumbnails/,yearbook-pages/,yearbook-pdfs/,documents/,video-thumbnails/,CAS/",
  );
  if (!keyAllowed(key, prefixes)) throw new HttpError(403, "forbidden_key", "Object key prefix is not allowed");
  assertYearbookKeyClass(key);
  const extensions = csv(
    env[isPublic ? "PUBLIC_MEDIA_EXTENSIONS" : "ALLOWED_UPLOAD_EXTENSIONS"],
    isPublic ? "jpg,jpeg,png,webp,gif,avif" : "jpg,jpeg,png,webp,gif,avif,pdf,doc,docx,xls,xlsx,ppt,pptx,txt,md,zip",
  ).map((item) => item.toLowerCase());
  if (!extensions.includes(extensionOf(key))) throw new HttpError(415, "forbidden_extension", "Object extension is not allowed");
}

function assertAllowedListPrefix(prefix, env) {
  const prefixes = configuredPrefixes(env, "ALLOWED_KEY_PREFIXES", "Photos/,avatars/,project-media/,thumbnails/,yearbook-pages/,yearbook-pdfs/,documents/,video-thumbnails/,CAS/");
  if (!keyAllowed(prefix, prefixes)) {
    throw new HttpError(403, "forbidden_prefix", "List prefix is not allowed");
  }
}

async function sha256Hex(data) {
  const digest = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function hmacHex(secret, value) {
  if (cachedHmacSecret !== secret || !cachedHmacKey) {
    cachedHmacSecret = secret;
    cachedHmacKey = crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  }
  const key = await cachedHmacKey;
  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(value));
  return [...new Uint8Array(signature)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function constantTimeEqual(left, right) {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  return difference === 0;
}

function oneParam(params, name, required = false) {
  const values = params.getAll(name);
  if (values.length > 1 || (required && values.length !== 1)) throw new HttpError(400, "invalid_query", `Query parameter ${name} must appear exactly once`);
  return values[0] ?? null;
}

function rejectUnknownParams(params, allowed) {
  for (const name of params.keys()) if (!allowed.includes(name)) throw new HttpError(400, "invalid_query", `Unknown query parameter: ${name}`);
}

function canonicalQuery(params) {
  return [...params.entries()]
    .sort(([leftKey, leftValue], [rightKey, rightValue]) => {
      if (leftKey !== rightKey) return leftKey < rightKey ? -1 : 1;
      if (leftValue === rightValue) return 0;
      return leftValue < rightValue ? -1 : 1;
    })
    .map(([key, value]) => `${strictEncode(key)}=${strictEncode(value)}`)
    .join("&");
}

function canonicalTarget(pathname, params) {
  const query = canonicalQuery(params);
  return query ? `${pathname}?${query}` : pathname;
}

function secret(env) {
  if (!env.HMAC_SECRET || encoder.encode(String(env.HMAC_SECRET)).byteLength < 32) {
    throw new HttpError(503, "worker_not_configured", "HMAC secret must contain at least 32 UTF-8 bytes");
  }
  return String(env.HMAC_SECRET);
}

async function authenticateInternal(request, env, target) {
  if (request.headers.has("Origin")) throw new HttpError(403, "browser_forbidden", "Browser-originated internal requests are forbidden");
  const timestamp = request.headers.get("X-Media-Timestamp") || "";
  const claimedHash = (request.headers.get("X-Media-Content-SHA256") || "").toLowerCase();
  const supplied = (request.headers.get("X-Media-Signature") || "").toLowerCase();
  if (!/^\d{10}$/.test(timestamp) || !/^[a-f0-9]{64}$/.test(claimedHash) || !/^[a-f0-9]{64}$/.test(supplied)) {
    throw new HttpError(401, "invalid_signature", "Required signature headers are missing or malformed");
  }
  const now = Math.floor(Date.now() / 1000);
  const skew = boundedInteger(env, "MAX_CLOCK_SKEW_SECONDS", 300, 1, 3600);
  if (Math.abs(now - Number(timestamp)) > skew) throw new HttpError(401, "expired_signature", "Request timestamp is expired or too far in the future");
  const canonical = `v1\n${request.method.toUpperCase()}\n${target}\n${timestamp}\n${claimedHash}`;
  const expected = await hmacHex(secret(env), canonical);
  if (!constantTimeEqual(expected, supplied)) throw new HttpError(401, "invalid_signature", "Signature verification failed");
  return claimedHash;
}

async function authenticateDownload(request, env, pathname, params) {
  rejectUnknownParams(params, ["expires", "sig"]);
  const expires = oneParam(params, "expires", true);
  const supplied = (oneParam(params, "sig", true) || "").toLowerCase();
  if (!/^\d{10}$/.test(expires) || !/^[a-f0-9]{64}$/.test(supplied)) throw new HttpError(401, "invalid_signature", "Download signature is malformed");
  const now = Math.floor(Date.now() / 1000);
  const maximumLifetime = boundedInteger(env, "MAX_DOWNLOAD_LIFETIME_SECONDS", 120, 1, 900);
  if (Number(expires) < now || Number(expires) > now + maximumLifetime) throw new HttpError(401, "expired_signature", "Download signature is expired or exceeds the maximum lifetime");
  const canonical = `v1\n${request.method.toUpperCase()}\n${pathname}\n${expires}\n${EMPTY_SHA256}`;
  const expected = await hmacHex(secret(env), canonical);
  if (!constantTimeEqual(expected, supplied)) throw new HttpError(401, "invalid_signature", "Download signature verification failed");
}

async function readVerifiedBody(request, claimedHash, env, limitOverride) {
  const limit = limitOverride ?? boundedInteger(env, "MAX_UPLOAD_BYTES", 25 * 1024 * 1024, 1, 100 * 1024 * 1024);
  const lengthHeader = request.headers.get("Content-Length");
  if (!/^\d+$/.test(lengthHeader || "")) throw new HttpError(411, "length_required", "A valid Content-Length header is required");
  if (Number(lengthHeader) > limit) throw new HttpError(413, "payload_too_large", "Request body exceeds the configured limit");
  const body = await request.arrayBuffer();
  if (body.byteLength !== Number(lengthHeader)) throw new HttpError(400, "length_mismatch", "Content-Length does not match the request body");
  const actualHash = await sha256Hex(body);
  if (!constantTimeEqual(actualHash, claimedHash)) throw new HttpError(401, "body_hash_mismatch", "Request body hash verification failed");
  return body;
}

async function assertEmptyRequestBody(request, claimedHash) {
  if (claimedHash !== EMPTY_SHA256) throw new HttpError(401, "body_hash_mismatch", "Bodyless requests must sign the empty SHA-256 hash");
  const lengthHeader = request.headers.get("Content-Length");
  if (lengthHeader !== null && (!/^\d+$/.test(lengthHeader) || Number(lengthHeader) !== 0)) {
    throw new HttpError(400, "unexpected_body", "This endpoint does not accept a request body");
  }
  // Cloudflare may expose a non-null, already-empty stream for a real Edge HEAD
  // request. Inspect the bytes instead of treating stream presence as payload.
  if (request.body !== null && (await request.arrayBuffer()).byteLength !== 0) {
    throw new HttpError(400, "unexpected_body", "This endpoint does not accept a request body");
  }
}

function json(data, status = 200, headers = {}) {
  const responseHeaders = new Headers(headers);
  if (!responseHeaders.has("Content-Type")) responseHeaders.set("Content-Type", "application/json; charset=utf-8");
  if (!responseHeaders.has("Cache-Control")) responseHeaders.set("Cache-Control", "no-store");
  if (!responseHeaders.has("X-Content-Type-Options")) responseHeaders.set("X-Content-Type-Options", "nosniff");
  return new Response(JSON.stringify(data), {
    status,
    headers: responseHeaders,
  });
}

function applyObjectHeaders(headers, object, cacheControl) {
  if (typeof object.writeHttpMetadata === "function") object.writeHttpMetadata(headers);
  if (object.httpEtag) headers.set("ETag", object.httpEtag);
  headers.set("Accept-Ranges", "bytes");
  headers.set("Cache-Control", cacheControl);
  headers.set("X-Content-Type-Options", "nosniff");
}

function parseRange(value, size) {
  if (!value) return null;
  if (size === 0) throw new HttpError(416, "invalid_range", "Byte range is unsatisfiable", { size });
  const match = /^bytes=(\d*)-(\d*)$/.exec(value.trim());
  if (!match || (!match[1] && !match[2])) throw new HttpError(416, "invalid_range", "Only one byte range is supported", { size });
  let start;
  let end;
  if (!match[1]) {
    const suffix = Number(match[2]);
    if (!Number.isSafeInteger(suffix) || suffix <= 0) throw new HttpError(416, "invalid_range", "Byte range is unsatisfiable", { size });
    start = Math.max(0, size - suffix);
    end = size - 1;
  } else {
    start = Number(match[1]);
    end = match[2] ? Number(match[2]) : size - 1;
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start > end || start >= size) {
      throw new HttpError(416, "invalid_range", "Byte range is unsatisfiable", { size });
    }
    end = Math.min(end, size - 1);
  }
  return { offset: start, length: end - start + 1, end };
}

function etagMatches(request, etag) {
  const value = request.headers.get("If-None-Match");
  if (!value || !etag) return false;
  const weakValue = (item) => item.trim().replace(/^W\//, "");
  return value.trim() === "*" || value.split(",").some((item) => weakValue(item) === weakValue(etag));
}

function rangeMayBeServed(request, object) {
  const ifRange = request.headers.get("If-Range");
  if (!ifRange) return true;
  if (ifRange.startsWith("\"") || ifRange.startsWith("W/")) return ifRange === object.httpEtag && !ifRange.startsWith("W/");
  const requestedDate = Date.parse(ifRange);
  const uploaded = object.uploaded instanceof Date ? object.uploaded.getTime() : Date.parse(object.uploaded);
  return Number.isFinite(requestedDate) && Number.isFinite(uploaded) && uploaded <= requestedDate;
}

async function serveObject(request, env, key, kind) {
  const head = await env.MEDIA_BUCKET.head(key);
  if (!head) throw new HttpError(404, "not_found", "Object not found");
  const cacheControl = kind === "media" ? (env.PUBLIC_CACHE_CONTROL || "public, max-age=86400") : "private, no-store";
  const headers = new Headers();
  applyObjectHeaders(headers, head, cacheControl);
  if (kind === "media") {
    headers.set("Access-Control-Allow-Origin", env.PUBLIC_CORS_ORIGIN || "*");
    headers.set("Content-Type", expectedContentType(key));
  }
  else headers.set("Content-Disposition", `attachment; filename*=UTF-8''${strictEncode(key.slice(key.lastIndexOf("/") + 1))}`);
  if (etagMatches(request, head.httpEtag)) return new Response(null, { status: 304, headers });
  let range;
  try {
    range = rangeMayBeServed(request, head) ? parseRange(request.headers.get("Range"), head.size) : null;
  } catch (error) {
    if (error instanceof HttpError && error.status === 416) {
      headers.set("Content-Range", `bytes */${head.size}`);
      headers.set("Cache-Control", "no-store");
      return json({ error: error.code, message: error.message }, 416, headers);
    }
    throw error;
  }
  if (range) {
    headers.set("Content-Range", `bytes ${range.offset}-${range.end}/${head.size}`);
    headers.set("Content-Length", String(range.length));
  } else headers.set("Content-Length", String(head.size));
  const status = range ? 206 : 200;
  if (request.method === "HEAD") return new Response(null, { status, headers });
  const object = await env.MEDIA_BUCKET.get(key, range ? { range: { offset: range.offset, length: range.length } } : undefined);
  if (!object) throw new HttpError(404, "not_found", "Object not found");
  return new Response(object.body, { status, headers });
}

function expectedContentType(key) {
  const extension = extensionOf(key);
  return {
    jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", webp: "image/webp", gif: "image/gif", avif: "image/avif",
    pdf: "application/pdf", txt: "text/plain", md: "text/markdown", json: "application/json", zip: "application/zip",
    doc: "application/msword", docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    xls: "application/vnd.ms-excel", xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ppt: "application/vnd.ms-powerpoint", pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  }[extension] || "application/octet-stream";
}

function assertContentType(key, contentType) {
  const expected = expectedContentType(key);
  if (expected && contentType && contentType.split(";", 1)[0].trim().toLowerCase() !== expected) {
    throw new HttpError(415, "content_type_mismatch", "Content-Type does not match the object extension");
  }
  return contentType || expected;
}

async function putObject(request, env, key, claimedHash) {
  assertAllowedKey(key, env);
  const contentType = assertContentType(key, request.headers.get("Content-Type"));
  const body = await readVerifiedBody(request, claimedHash, env);
  if (await env.MEDIA_BUCKET.head(key)) throw new HttpError(409, "object_exists", "Object already exists; overwrite is forbidden");
  const result = await env.MEDIA_BUCKET.put(key, body, {
    httpMetadata: { contentType },
    customMetadata: { sha256: claimedHash },
    onlyIf: { etagDoesNotMatch: "*" },
  });
  if (!result) throw new HttpError(409, "object_exists", "Object was created concurrently; overwrite is forbidden");
  return json({ key, size: body.byteLength, etag: result.httpEtag || result.etag, sha256: claimedHash }, 201);
}

async function deleteObject(env, key) {
  assertAllowedKey(key, env);
  if (!(await env.MEDIA_BUCKET.head(key))) throw new HttpError(404, "not_found", "Object not found");
  await env.MEDIA_BUCKET.delete(key);
  return new Response(null, { status: 204, headers: { "Cache-Control": "no-store" } });
}

async function listObjects(url, env) {
  rejectUnknownParams(url.searchParams, ["prefix", "cursor", "limit"]);
  const prefix = normalizePrefix(oneParam(url.searchParams, "prefix", true));
  assertAllowedListPrefix(prefix, env);
  const cursor = oneParam(url.searchParams, "cursor") || undefined;
  if (cursor && (cursor.length > 2048 || /[\u0000-\u001f\u007f]/u.test(cursor))) throw new HttpError(400, "invalid_cursor", "List cursor is invalid");
  const rawLimit = oneParam(url.searchParams, "limit") || "50";
  if (!/^\d+$/.test(rawLimit)) throw new HttpError(400, "invalid_limit", "List limit must be an integer");
  const limit = Number(rawLimit);
  if (limit < 1 || limit > 100) throw new HttpError(400, "invalid_limit", "List limit must be between 1 and 100");
  const result = await env.MEDIA_BUCKET.list({ prefix, cursor, limit, include: ["httpMetadata", "customMetadata"] });
  return json({
    objects: result.objects.map((object) => ({ key: object.key, size: object.size, etag: object.httpEtag || object.etag, uploaded: object.uploaded, httpMetadata: object.httpMetadata, customMetadata: object.customMetadata })),
    nextCursor: result.truncated ? result.cursor : null,
    hasMore: Boolean(result.truncated),
  });
}

function multipartFrom(env, key, uploadId) {
  if (!uploadId || uploadId.length > 512 || /[\u0000-\u001f\u007f]/u.test(uploadId)) {
    throw new HttpError(400, "invalid_upload_id", "Multipart uploadId is missing or invalid");
  }
  try {
    return env.MEDIA_BUCKET.resumeMultipartUpload(key, uploadId);
  } catch {
    throw new HttpError(409, "multipart_not_found", "Multipart upload is missing or expired");
  }
}

async function createMultipart(request, env, key) {
  assertAllowedKey(key, env);
  if (await env.MEDIA_BUCKET.head(key)) throw new HttpError(409, "object_exists", "Object already exists; overwrite is forbidden");
  const contentType = assertContentType(key, request.headers.get("X-Media-Content-Type"));
  const upload = await env.MEDIA_BUCKET.createMultipartUpload(key, { httpMetadata: { contentType } });
  return json({ key, uploadId: upload.uploadId }, 201);
}

async function uploadPart(request, env, key, uploadId, partNumber, claimedHash) {
  assertAllowedKey(key, env);
  if (!Number.isInteger(partNumber) || partNumber < 1 || partNumber > 10000) throw new HttpError(400, "invalid_part", "Part number must be between 1 and 10000");
  const body = await readVerifiedBody(request, claimedHash, env);
  let part;
  try {
    part = await multipartFrom(env, key, uploadId).uploadPart(partNumber, body);
  } catch {
    throw new HttpError(409, "multipart_part_failed", "Multipart upload is missing, expired, or rejected the part");
  }
  return json({ partNumber: part.partNumber, etag: part.etag, size: body.byteLength });
}

async function completeMultipart(request, env, key, uploadId, claimedHash) {
  assertAllowedKey(key, env);
  const upload = multipartFrom(env, key, uploadId);
  const body = await readVerifiedBody(request, claimedHash, env, 1024 * 1024);
  let payload;
  try {
    payload = JSON.parse(new TextDecoder().decode(body));
  } catch {
    throw new HttpError(400, "invalid_json", "Completion body is not valid JSON");
  }
  if (!Array.isArray(payload.parts) || payload.parts.length === 0 || payload.parts.length > 10000) throw new HttpError(400, "invalid_parts", "Completion requires a non-empty parts array");
  const parts = payload.parts.map((part) => {
    if (!Number.isInteger(part.partNumber) || part.partNumber < 1 || part.partNumber > 10000 || typeof part.etag !== "string" || !part.etag || part.etag.length > 512 || /[\u0000-\u001f\u007f]/u.test(part.etag)) {
      throw new HttpError(400, "invalid_parts", "Each completed part needs a valid partNumber and etag");
    }
    return { partNumber: part.partNumber, etag: part.etag };
  });
  if (new Set(parts.map((part) => part.partNumber)).size !== parts.length) throw new HttpError(400, "invalid_parts", "Duplicate part numbers are forbidden");
  parts.sort((left, right) => left.partNumber - right.partNumber);
  if (await env.MEDIA_BUCKET.head(key)) {
    await upload.abort().catch(() => undefined);
    throw new HttpError(409, "object_exists", "Object appeared during multipart upload; upload was aborted");
  }
  try {
    const object = await upload.complete(parts);
    return json({ key, etag: object.httpEtag || object.etag, completed: true }, 201);
  } catch {
    let rolledBack = true;
    try { await upload.abort(); } catch { rolledBack = false; }
    throw new HttpError(409, "multipart_complete_failed", "Multipart completion failed and rollback was attempted", { rolledBack });
  }
}

async function abortMultipart(env, key, uploadId) {
  assertAllowedKey(key, env);
  try {
    await multipartFrom(env, key, uploadId).abort();
  } catch {
    throw new HttpError(409, "multipart_abort_failed", "Multipart upload is missing, expired, or could not be aborted");
  }
  return new Response(null, { status: 204, headers: { "Cache-Control": "no-store" } });
}

function parseRoute(pathname) {
  const routes = [
    ["media", "/media/"], ["download", "/download/"], ["object", "/internal/object/"], ["multipart", "/internal/multipart/"],
  ];
  for (const [name, prefix] of routes) {
    if (pathname.startsWith(prefix)) {
      let encodedKey = pathname.slice(prefix.length);
      let partNumber = null;
      if (name === "multipart") {
        const match = /\/part\/(\d+)$/.exec(encodedKey);
        if (match) {
          partNumber = Number(match[1]);
          encodedKey = encodedKey.slice(0, match.index);
        }
      }
      const parsed = canonicalKeyFromEncoded(encodedKey);
      return { name, ...parsed, partNumber, pathname: `${prefix}${parsed.encoded}${partNumber === null ? "" : `/part/${partNumber}`}` };
    }
  }
  if (pathname === "/internal/list") return { name: "list", pathname };
  return null;
}

async function handle(request, env) {
  if (!env.MEDIA_BUCKET) throw new HttpError(503, "worker_not_configured", "R2 bucket binding is not configured");
  const url = new URL(request.url);
  const route = parseRoute(url.pathname);
  if (!route) throw new HttpError(404, "not_found", "Route not found");

  if (route.name === "media") {
    if (!["GET", "HEAD"].includes(request.method)) throw new HttpError(405, "method_not_allowed", "Only GET and HEAD are allowed", { allowedMethods: ["GET", "HEAD"] });
    if ([...url.searchParams].length) throw new HttpError(400, "invalid_query", "Public media URLs do not accept query parameters");
    assertAllowedKey(route.key, env, true);
    return serveObject(request, env, route.key, "media");
  }
  if (route.name === "download") {
    if (!["GET", "HEAD"].includes(request.method)) throw new HttpError(405, "method_not_allowed", "Only GET and HEAD are allowed", { allowedMethods: ["GET", "HEAD"] });
    assertAllowedKey(route.key, env);
    await authenticateDownload(request, env, route.pathname, url.searchParams);
    return serveObject(request, env, route.key, "download");
  }
  const allowedMethods = route.name === "object" ? ["PUT", "HEAD", "DELETE"]
    : route.name === "list" ? ["GET"]
      : route.partNumber === null ? ["POST", "DELETE"] : ["PUT"];
  if (!allowedMethods.includes(request.method)) throw new HttpError(405, "method_not_allowed", "Method is not allowed for this endpoint", { allowedMethods });
  if (route.name === "list") rejectUnknownParams(url.searchParams, ["prefix", "cursor", "limit"]);
  else if (route.name === "multipart") rejectUnknownParams(url.searchParams, ["uploadId"]);
  else if ([...url.searchParams].length) throw new HttpError(400, "invalid_query", "Object endpoints do not accept query parameters");
  const target = canonicalTarget(route.pathname, url.searchParams);
  const claimedHash = await authenticateInternal(request, env, target);
  const hasBody = request.method === "PUT" || (route.name === "multipart" && request.method === "POST" && oneParam(url.searchParams, "uploadId"));
  if (!hasBody) await assertEmptyRequestBody(request, claimedHash);

  if (route.name === "list") return listObjects(url, env);
  if (route.name === "object") {
    if (request.method === "PUT") return putObject(request, env, route.key, claimedHash);
    assertAllowedKey(route.key, env);
    if (request.method === "HEAD") {
      const object = await env.MEDIA_BUCKET.head(route.key);
      if (!object) throw new HttpError(404, "not_found", "Object not found");
      const headers = new Headers({
        "Cache-Control": "no-store",
        "Content-Length": String(object.size),
        "X-Media-Size": String(object.size),
        "X-Content-Type-Options": "nosniff",
      });
      if (typeof object.writeHttpMetadata === "function") object.writeHttpMetadata(headers);
      if (object.httpEtag || object.etag) headers.set("ETag", object.httpEtag || object.etag);
      if (object.uploaded) headers.set("X-Media-Uploaded", new Date(object.uploaded).toISOString());
      if (object.customMetadata?.sha256) headers.set("X-Media-SHA256", object.customMetadata.sha256);
      return new Response(null, { status: 200, headers });
    }
    return deleteObject(env, route.key);
  }
  const uploadId = oneParam(url.searchParams, "uploadId", request.method !== "POST" || route.partNumber !== null);
  if (route.partNumber !== null) return uploadPart(request, env, route.key, uploadId, route.partNumber, claimedHash);
  if (request.method === "POST" && !uploadId) return createMultipart(request, env, route.key);
  if (request.method === "POST") return completeMultipart(request, env, route.key, uploadId, claimedHash);
  return abortMultipart(env, route.key, uploadId);
}

function finalizeResponse(request, response) {
  if (request.method !== "HEAD" || response.body === null) return response;
  return new Response(null, { status: response.status, statusText: response.statusText, headers: response.headers });
}

export default {
  async fetch(request, env) {
    try {
      return finalizeResponse(request, await handle(request, env));
    } catch (error) {
      if (error instanceof HttpError) {
        const headers = error.status === 405 ? { Allow: (error.details?.allowedMethods || []).join(", ") } : {};
        return finalizeResponse(request, json({ error: error.code, message: error.message, ...(error.details ? { details: error.details } : {}) }, error.status, headers));
      }
      console.error("Unhandled media gateway error", error);
      return finalizeResponse(request, json({ error: "internal_error", message: "Internal server error" }, 500));
    }
  },
};

export { EMPTY_SHA256, canonicalTarget, hmacHex, sha256Hex };
