import test from "node:test";
import assert from "node:assert/strict";
import worker, { EMPTY_SHA256, hmacHex, sha256Hex } from "../src/worker.js";

const SECRET = "test-secret-that-is-at-least-thirty-two-bytes-long";
const BASE = "https://wiki-media.example.test";

class MemoryBucket {
  constructor() {
    this.objects = new Map();
    this.uploads = new Map();
    this.nextUpload = 1;
    this.failComplete = false;
    this.abortCount = 0;
  }

  metadata(key, entry) {
    if (!entry) return null;
    return {
      key,
      size: entry.bytes.byteLength,
      etag: entry.etag,
      httpEtag: `"${entry.etag}"`,
      uploaded: entry.uploaded,
      httpMetadata: entry.httpMetadata,
      customMetadata: entry.customMetadata,
      writeHttpMetadata(headers) {
        if (entry.httpMetadata?.contentType) headers.set("Content-Type", entry.httpMetadata.contentType);
      },
    };
  }

  seed(key, value, contentType = "image/jpeg") {
    const bytes = new TextEncoder().encode(value);
    this.objects.set(key, { bytes, etag: `etag-${this.objects.size + 1}-${bytes.byteLength}`, uploaded: new Date(), httpMetadata: { contentType }, customMetadata: {} });
  }

  async head(key) { return this.metadata(key, this.objects.get(key)); }

  async get(key, options) {
    const entry = this.objects.get(key);
    if (!entry) return null;
    const range = options?.range;
    const bytes = range ? entry.bytes.slice(range.offset, range.offset + range.length) : entry.bytes;
    return { ...this.metadata(key, entry), body: bytes };
  }

  async put(key, body, options = {}) {
    if (options.onlyIf?.etagDoesNotMatch === "*" && this.objects.has(key)) return null;
    const bytes = new Uint8Array(body);
    const entry = {
      bytes,
      etag: `etag-${bytes.byteLength}-${key}`,
      uploaded: new Date(),
      httpMetadata: options.httpMetadata || {},
      customMetadata: options.customMetadata || {},
    };
    this.objects.set(key, entry);
    return this.metadata(key, entry);
  }

  async delete(key) { this.objects.delete(key); }

  async list({ prefix, cursor, limit }) {
    const keys = [...this.objects.keys()].filter((key) => key.startsWith(prefix)).sort();
    const start = cursor ? Number(cursor) : 0;
    const selected = keys.slice(start, start + limit);
    const next = start + selected.length;
    return { objects: selected.map((key) => this.metadata(key, this.objects.get(key))), truncated: next < keys.length, cursor: String(next) };
  }

  async createMultipartUpload(key, options = {}) {
    const uploadId = `upload-${this.nextUpload++}`;
    this.uploads.set(uploadId, { key, options, parts: new Map() });
    return { key, uploadId };
  }

  resumeMultipartUpload(key, uploadId) {
    const bucket = this;
    const state = this.uploads.get(uploadId);
    if (!state || state.key !== key) throw new Error("unknown upload");
    return {
      async uploadPart(partNumber, body) {
        const bytes = new Uint8Array(body);
        const etag = `part-${partNumber}-${bytes.byteLength}`;
        state.parts.set(partNumber, { bytes, etag });
        return { partNumber, etag };
      },
      async complete(parts) {
        if (bucket.failComplete) throw new Error("injected complete failure");
        const chosen = parts.map(({ partNumber, etag }) => {
          const part = state.parts.get(partNumber);
          if (!part || part.etag !== etag) throw new Error("part mismatch");
          return part.bytes;
        });
        const size = chosen.reduce((sum, bytes) => sum + bytes.byteLength, 0);
        const merged = new Uint8Array(size);
        let offset = 0;
        for (const bytes of chosen) { merged.set(bytes, offset); offset += bytes.byteLength; }
        bucket.uploads.delete(uploadId);
        return bucket.put(key, merged, state.options);
      },
      async abort() { bucket.abortCount += 1; bucket.uploads.delete(uploadId); },
    };
  }
}

function environment(bucket = new MemoryBucket()) {
  return {
    MEDIA_BUCKET: bucket,
    HMAC_SECRET: SECRET,
    ALLOWED_KEY_PREFIXES: "Photos/,documents/,thumbnails/",
    PUBLIC_MEDIA_PREFIXES: "Photos/,thumbnails/",
    ALLOWED_UPLOAD_EXTENSIONS: "jpg,jpeg,png,webp,pdf",
    PUBLIC_MEDIA_EXTENSIONS: "jpg,jpeg,png,webp",
    MAX_CLOCK_SKEW_SECONDS: "300",
    MAX_DOWNLOAD_LIFETIME_SECONDS: "120",
    MAX_UPLOAD_BYTES: "1048576",
  };
}

async function signedRequest(path, { method = "GET", body, headers = {}, timestamp, target, hash } = {}) {
  const now = timestamp ?? Math.floor(Date.now() / 1000);
  const bytes = body === undefined ? new Uint8Array() : typeof body === "string" ? new TextEncoder().encode(body) : body;
  const contentHash = hash ?? await sha256Hex(bytes);
  const canonical = `v1\n${method}\n${target ?? path}\n${now}\n${contentHash}`;
  const signature = await hmacHex(SECRET, canonical);
  const requestHeaders = new Headers(headers);
  requestHeaders.set("X-Media-Timestamp", String(now));
  requestHeaders.set("X-Media-Content-SHA256", contentHash);
  requestHeaders.set("X-Media-Signature", signature);
  if (body !== undefined) requestHeaders.set("Content-Length", String(bytes.byteLength));
  return new Request(`${BASE}${path}`, { method, body: body === undefined ? undefined : bytes, headers: requestHeaders });
}

async function signedDownload(path, method = "GET", expires = Math.floor(Date.now() / 1000) + 60) {
  const canonical = `v1\n${method}\n${path}\n${expires}\n${EMPTY_SHA256}`;
  const signature = await hmacHex(SECRET, canonical);
  return new Request(`${BASE}${path}?expires=${expires}&sig=${signature}`, { method });
}

test("public media supports cache headers, conditional GET, Range, and HEAD", async () => {
  const bucket = new MemoryBucket();
  bucket.seed("Photos/中文/photo.jpg", "0123456789", "text/html");
  const env = environment(bucket);
  const path = "/media/Photos/%E4%B8%AD%E6%96%87/photo.jpg";
  const ranged = await worker.fetch(new Request(`${BASE}${path}`, { headers: { Range: "bytes=2-5" } }), env);
  assert.equal(ranged.status, 206);
  assert.equal(await ranged.text(), "2345");
  assert.equal(ranged.headers.get("Content-Range"), "bytes 2-5/10");
  assert.equal(ranged.headers.get("Cache-Control"), "public, max-age=86400");
  assert.equal(ranged.headers.get("Content-Type"), "image/jpeg");
  assert.equal(ranged.headers.get("Access-Control-Allow-Origin"), "*");

  const head = await worker.fetch(new Request(`${BASE}${path}`, { method: "HEAD", headers: { Range: "bytes=-3" } }), env);
  assert.equal(head.status, 206);
  assert.equal(head.headers.get("Content-Length"), "3");
  assert.equal(await head.text(), "");

  const objectEtag = (await bucket.head("Photos/中文/photo.jpg")).httpEtag;
  const notModified = await worker.fetch(new Request(`${BASE}${path}`, { headers: { "If-None-Match": `W/${objectEtag}`, Range: "bytes=0-1" } }), env);
  assert.equal(notModified.status, 304);

  const ifRangeMiss = await worker.fetch(new Request(`${BASE}${path}`, { headers: { Range: "bytes=0-1", "If-Range": '"different"' } }), env);
  assert.equal(ifRangeMiss.status, 200);
  assert.equal(await ifRangeMiss.text(), "0123456789");
});

test("invalid and multiple ranges return 416", async () => {
  const bucket = new MemoryBucket();
  bucket.seed("Photos/a.jpg", "1234");
  for (const range of ["bytes=9-10", "bytes=0-1,2-3", "items=0-1"]) {
    const response = await worker.fetch(new Request(`${BASE}/media/Photos/a.jpg`, { headers: { Range: range } }), environment(bucket));
    assert.equal(response.status, 416);
    assert.equal(response.headers.get("Content-Range"), "bytes */4");
  }
  const head = await worker.fetch(new Request(`${BASE}/media/Photos/a.jpg`, { method: "HEAD", headers: { Range: "bytes=99-100" } }), environment(bucket));
  assert.equal(head.status, 416);
  assert.equal(head.headers.get("Cache-Control"), "no-store");
  assert.equal(await head.text(), "");
});

test("path traversal, encoded separators, forbidden prefixes, and extensions are rejected", async () => {
  const env = environment();
  const cases = [
    ["/media/Photos/../secret.jpg", 403],
    ["/media/Photos/%252e%252e/secret.jpg", 400],
    ["/media/Photos/foo%2Fbar.jpg", 400],
    ["/media/private/a.jpg", 403],
    ["/media/Photos/a.svg", 415],
  ];
  for (const [path, status] of cases) assert.equal((await worker.fetch(new Request(`${BASE}${path}`), env)).status, status, path);
});

test("wiki policy exposes yearbook pages and thumbnails but keeps PDFs signed-only", async () => {
  const bucket = new MemoryBucket();
  bucket.seed("yearbook-pages/2026/001.jpg", "page", "image/jpeg");
  bucket.seed("thumbnails/yearbook/2026/001.jpg.image.webp", "thumb", "image/webp");
  bucket.seed("yearbook-pdfs/2026/yearbook.pdf", "pdf", "application/pdf");
  const env = environment(bucket);
  env.ALLOWED_KEY_PREFIXES = "Photos/,avatars/,project-media/,thumbnails/,yearbook-pages/,yearbook-pdfs/,documents/,video-thumbnails/,CAS/";
  env.PUBLIC_MEDIA_PREFIXES = "Photos/,avatars/,project-media/,thumbnails/,yearbook-pages/,video-thumbnails/,CAS/";
  env.ALLOWED_UPLOAD_EXTENSIONS = "jpg,jpeg,png,webp,gif,avif,pdf,doc,docx,xls,xlsx,ppt,pptx,txt,md,zip";

  const videoPath = "/internal/object/Photos/video.mp4";
  const video = await worker.fetch(await signedRequest(videoPath, { method: "PUT", body: "video", headers: { "Content-Type": "video/mp4" } }), env);
  assert.equal(video.status, 415);
  assert.equal((await worker.fetch(new Request(`${BASE}/media/yearbook-pages/2026/001.jpg`), env)).status, 200);
  assert.equal((await worker.fetch(new Request(`${BASE}/media/thumbnails/yearbook/2026/001.jpg.image.webp`), env)).status, 200);
  assert.equal((await worker.fetch(new Request(`${BASE}/media/yearbook-pdfs/2026/yearbook.pdf`), env)).status, 403);
  assert.equal((await worker.fetch(await signedDownload("/download/yearbook-pdfs/2026/yearbook.pdf"), env)).status, 200);
  assert.equal((await worker.fetch(new Request(`${BASE}/media/yearbook/2026/001.jpg`), env)).status, 403);
  assert.equal((await worker.fetch(new Request(`${BASE}/media/yearbook-thumbnails/2026/001.jpg`), env)).status, 403);

  const pdfInPages = await worker.fetch(await signedRequest(
    "/internal/object/yearbook-pages/2026/book.pdf",
    { method: "PUT", body: "pdf", headers: { "Content-Type": "application/pdf" } },
  ), env);
  const imageInPdfs = await worker.fetch(await signedRequest(
    "/internal/object/yearbook-pdfs/2026/001.jpg",
    { method: "PUT", body: "image", headers: { "Content-Type": "image/jpeg" } },
  ), env);
  assert.equal(pdfInPages.status, 415);
  assert.equal(imageInPdfs.status, 415);
});

test("download requires a valid short-lived method-specific signature", async () => {
  const bucket = new MemoryBucket();
  bucket.seed("documents/report.pdf", "report", "application/pdf");
  const env = environment(bucket);
  const ok = await worker.fetch(await signedDownload("/download/documents/report.pdf"), env);
  assert.equal(ok.status, 200);
  assert.equal(ok.headers.get("Cache-Control"), "private, no-store");
  assert.match(ok.headers.get("Content-Disposition"), /^attachment;/);
  const expired = await worker.fetch(await signedDownload("/download/documents/report.pdf", "GET", Math.floor(Date.now() / 1000) - 1), env);
  assert.equal(expired.status, 401);
  const getSignatureUsedForHead = await signedDownload("/download/documents/report.pdf");
  const wrongMethod = new Request(getSignatureUsedForHead.url, { method: "HEAD" });
  assert.equal((await worker.fetch(wrongMethod, env)).status, 401);
});

test("internal authentication rejects expired, future, altered, and browser-originated requests", async () => {
  const env = environment();
  const now = Math.floor(Date.now() / 1000);
  assert.equal((await worker.fetch(await signedRequest("/internal/list?prefix=Photos%2F", { target: "/internal/list?prefix=Photos%2F", timestamp: now - 301 }), env)).status, 401);
  assert.equal((await worker.fetch(await signedRequest("/internal/list?prefix=Photos%2F", { target: "/internal/list?prefix=Photos%2F", timestamp: now + 301 }), env)).status, 401);
  assert.equal((await worker.fetch(await signedRequest("/internal/list?prefix=Photos%2F&limit=10", { target: "/internal/list?prefix=Photos%2F" }), env)).status, 401);
  assert.equal((await worker.fetch(await signedRequest("/internal/list?prefix=Photos%2F", { target: "/internal/list?prefix=Photos%2F", headers: { Origin: "https://attacker.test" } }), env)).status, 403);
});

test("invalid security limit configuration fails closed", async () => {
  const env = environment();
  env.MAX_CLOCK_SKEW_SECONDS = "not-a-number";
  const path = "/internal/list?prefix=Photos%2F";
  assert.equal((await worker.fetch(await signedRequest(path, { target: path }), env)).status, 503);

  const downloadEnv = environment();
  downloadEnv.MAX_DOWNLOAD_LIFETIME_SECONDS = "NaN";
  const bucket = downloadEnv.MEDIA_BUCKET;
  bucket.seed("documents/report.pdf", "report", "application/pdf");
  assert.equal((await worker.fetch(await signedDownload("/download/documents/report.pdf"), downloadEnv)).status, 503);
});

test("signed object upload verifies body hash and rejects overwrite", async () => {
  const bucket = new MemoryBucket();
  const env = environment(bucket);
  const path = "/internal/object/Photos/new.jpg";
  const first = await worker.fetch(await signedRequest(path, { method: "PUT", body: "jpeg-data", headers: { "Content-Type": "image/jpeg" } }), env);
  assert.equal(first.status, 201);
  assert.equal((await bucket.head("Photos/new.jpg")).customMetadata.sha256.length, 64);
  const conflict = await worker.fetch(await signedRequest(path, { method: "PUT", body: "other", headers: { "Content-Type": "image/jpeg" } }), env);
  assert.equal(conflict.status, 409);
  const badHash = await worker.fetch(await signedRequest("/internal/object/Photos/bad.jpg", { method: "PUT", body: "actual", hash: "0".repeat(64), headers: { "Content-Type": "image/jpeg" } }), env);
  assert.equal(badHash.status, 401);
  assert.equal(await bucket.head("Photos/bad.jpg"), null);
});

test("object content type, length, and request size are bounded", async () => {
  const env = environment();
  const mismatch = await worker.fetch(await signedRequest("/internal/object/Photos/a.jpg", { method: "PUT", body: "x", headers: { "Content-Type": "image/png" } }), env);
  assert.equal(mismatch.status, 415);
  const request = await signedRequest("/internal/object/Photos/b.jpg", { method: "PUT", body: "x", headers: { "Content-Type": "image/jpeg" } });
  request.headers.set("Content-Length", "1048577");
  assert.equal((await worker.fetch(request, env)).status, 413);
});

test("internal HEAD and DELETE are authenticated", async () => {
  const bucket = new MemoryBucket();
  bucket.seed("Photos/a.jpg", "abc");
  const env = environment(bucket);
  const headPath = "/internal/object/Photos/a.jpg";
  const head = await worker.fetch(await signedRequest(headPath, { method: "HEAD" }), env);
  assert.equal(head.status, 200);
  assert.equal(head.headers.get("Content-Length"), "3");
  assert.equal(head.headers.get("X-Media-Size"), "3");
  assert.equal(await head.text(), "");
  const deleted = await worker.fetch(await signedRequest(headPath, { method: "DELETE" }), env);
  assert.equal(deleted.status, 204);
  assert.equal(await bucket.head("Photos/a.jpg"), null);
});

test("internal HEAD accepts Cloudflare Edge's non-null empty body stream", async () => {
  const bucket = new MemoryBucket();
  bucket.seed("Photos/edge-head.jpg", "abc");
  const signed = await signedRequest("/internal/object/Photos/edge-head.jpg", { method: "HEAD" });
  const edgeRequest = {
    method: signed.method,
    url: signed.url,
    headers: signed.headers,
    body: new ReadableStream({ start(controller) { controller.close(); } }),
    async arrayBuffer() { return new ArrayBuffer(0); },
  };
  const response = await worker.fetch(edgeRequest, environment(bucket));
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("Content-Length"), "3");
});

test("list enforces allowed prefix, page size, and cursor response", async () => {
  const bucket = new MemoryBucket();
  bucket.seed("Photos/a.jpg", "a");
  bucket.seed("Photos/b.jpg", "b");
  const env = environment(bucket);
  const path = "/internal/list?limit=1&prefix=Photos%2F";
  const target = "/internal/list?limit=1&prefix=Photos%2F";
  const page = await worker.fetch(await signedRequest(path, { target }), env);
  assert.equal(page.status, 200);
  const payload = await page.json();
  assert.equal(payload.objects.length, 1);
  assert.equal(payload.objects[0].key, "Photos/a.jpg");
  assert.equal(payload.objects[0].size, 1);
  assert.equal(payload.nextCursor, "1");
  assert.equal(payload.hasMore, true);
  const forbiddenPath = "/internal/list?prefix=private%2F";
  assert.equal((await worker.fetch(await signedRequest(forbiddenPath, { target: forbiddenPath }), env)).status, 403);
  const ambiguousRoot = "/internal/list?prefix=Photos";
  assert.equal((await worker.fetch(await signedRequest(ambiguousRoot, { target: ambiguousRoot }), env)).status, 403);
  const tooLarge = "/internal/list?limit=101&prefix=Photos%2F";
  assert.equal((await worker.fetch(await signedRequest(tooLarge, { target: tooLarge }), env)).status, 400);
});

test("yearbook list accepts only the normalized page and PDF prefixes", async () => {
  const env = environment();
  env.ALLOWED_KEY_PREFIXES = "yearbook-pages/,yearbook-pdfs/,thumbnails/";
  for (const prefix of ["yearbook-pages/2026/", "yearbook-pdfs/2026/", "thumbnails/yearbook/2026/"]) {
    const encoded = encodeURIComponent(prefix);
    const path = `/internal/list?prefix=${encoded}`;
    assert.equal((await worker.fetch(await signedRequest(path, { target: path }), env)).status, 200);
  }
  for (const prefix of ["yearbook/2026/", "yearbook-thumbnails/2026/"]) {
    const encoded = encodeURIComponent(prefix);
    const path = `/internal/list?prefix=${encoded}`;
    assert.equal((await worker.fetch(await signedRequest(path, { target: path }), env)).status, 403);
  }
});

test("multipart create, part upload, and complete produce an object", async () => {
  const bucket = new MemoryBucket();
  const env = environment(bucket);
  const keyPath = "/internal/multipart/Photos/large.jpg";
  const created = await worker.fetch(await signedRequest(keyPath, { method: "POST", headers: { "X-Media-Content-Type": "image/jpeg" } }), env);
  assert.equal(created.status, 201);
  const { uploadId } = await created.json();
  const partPath = `${keyPath}/part/1?uploadId=${uploadId}`;
  const part = await worker.fetch(await signedRequest(partPath, { method: "PUT", body: "first", target: partPath }), env);
  assert.equal(part.status, 200);
  const { etag } = await part.json();
  const completionBody = JSON.stringify({ parts: [{ partNumber: 1, etag }] });
  const completePath = `${keyPath}?uploadId=${uploadId}`;
  const completed = await worker.fetch(await signedRequest(completePath, { method: "POST", body: completionBody, target: completePath, headers: { "Content-Type": "application/json" } }), env);
  assert.equal(completed.status, 201);
  assert.equal(new TextDecoder().decode((await bucket.get("Photos/large.jpg")).body), "first");
});

test("multipart completion conflict and failure abort unfinished upload", async () => {
  for (const failureMode of ["conflict", "complete-error"]) {
    const bucket = new MemoryBucket();
    const env = environment(bucket);
    const keyPath = "/internal/multipart/Photos/rollback.jpg";
    const create = await worker.fetch(await signedRequest(keyPath, { method: "POST", headers: { "X-Media-Content-Type": "image/jpeg" } }), env);
    const { uploadId } = await create.json();
    const partPath = `${keyPath}/part/1?uploadId=${uploadId}`;
    const part = await worker.fetch(await signedRequest(partPath, { method: "PUT", body: "data", target: partPath }), env);
    const { etag } = await part.json();
    if (failureMode === "conflict") bucket.seed("Photos/rollback.jpg", "winner");
    else bucket.failComplete = true;
    const body = JSON.stringify({ parts: [{ partNumber: 1, etag }] });
    const completePath = `${keyPath}?uploadId=${uploadId}`;
    const response = await worker.fetch(await signedRequest(completePath, { method: "POST", body, target: completePath }), env);
    assert.equal(response.status, 409);
    assert.equal(bucket.abortCount, 1);
    assert.equal(bucket.uploads.has(uploadId), false);
  }
});

test("multipart abort endpoint removes unfinished upload", async () => {
  const bucket = new MemoryBucket();
  const env = environment(bucket);
  const keyPath = "/internal/multipart/Photos/aborted.jpg";
  const create = await worker.fetch(await signedRequest(keyPath, { method: "POST", headers: { "X-Media-Content-Type": "image/jpeg" } }), env);
  const { uploadId } = await create.json();
  const abortPath = `${keyPath}?uploadId=${uploadId}`;
  const response = await worker.fetch(await signedRequest(abortPath, { method: "DELETE", target: abortPath }), env);
  assert.equal(response.status, 204);
  assert.equal(bucket.uploads.has(uploadId), false);
});

test("unknown multipart uploads return a controlled conflict", async () => {
  const env = environment();
  const partPath = "/internal/multipart/Photos/missing.jpg/part/1?uploadId=missing";
  const part = await worker.fetch(await signedRequest(partPath, { method: "PUT", body: "part", target: partPath }), env);
  assert.equal(part.status, 409);
  assert.equal((await part.json()).error, "multipart_part_failed");

  const abortPath = "/internal/multipart/Photos/missing.jpg?uploadId=missing";
  const aborted = await worker.fetch(await signedRequest(abortPath, { method: "DELETE", target: abortPath }), env);
  assert.equal(aborted.status, 409);
  assert.equal((await aborted.json()).error, "multipart_abort_failed");
});

test("internal endpoints do not expose permissive CORS", async () => {
  const response = await worker.fetch(new Request(`${BASE}/internal/list?prefix=Photos%2F`, { method: "OPTIONS", headers: { Origin: "https://attacker.test" } }), environment());
  assert.equal(response.status, 405);
  assert.equal(response.headers.get("Allow"), "GET");
  assert.equal(response.headers.has("Access-Control-Allow-Origin"), false);
});

test("bodyless internal endpoints reject a smuggled body", async () => {
  const path = "/internal/multipart/Photos/unexpected.jpg";
  const request = await signedRequest(path, { method: "POST", body: "ignored", hash: EMPTY_SHA256 });
  const response = await worker.fetch(request, environment());
  assert.equal(response.status, 400);
  assert.equal((await response.json()).error, "unexpected_body");
});
