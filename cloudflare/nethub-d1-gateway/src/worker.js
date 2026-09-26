const encoder = new TextEncoder();
const replayed = new Map();

class GatewayError extends Error {
  constructor(status, code, message, details) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function json(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" },
  });
}

function hex(bytes) { return [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join(""); }
async function sha256(value) { return hex(await crypto.subtle.digest("SHA-256", value)); }
async function hmac(secret, value) {
  const key = await crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return hex(await crypto.subtle.sign("HMAC", key, encoder.encode(value)));
}
function equal(left, right) {
  if (left.length !== right.length) return false;
  let result = 0;
  for (let i = 0; i < left.length; i += 1) result |= left.charCodeAt(i) ^ right.charCodeAt(i);
  return result === 0;
}
function configuredSecret(env) {
  if (!env.HMAC_SECRET || encoder.encode(String(env.HMAC_SECRET)).byteLength < 32) {
    throw new GatewayError(503, "worker_not_configured", "HMAC_SECRET must contain at least 32 UTF-8 bytes");
  }
  return String(env.HMAC_SECRET);
}
function maxSkew(env) {
  const value = Number(env.MAX_CLOCK_SKEW_SECONDS ?? 300);
  if (!Number.isSafeInteger(value) || value < 1 || value > 3600) throw new GatewayError(503, "worker_not_configured", "MAX_CLOCK_SKEW_SECONDS is invalid");
  return value;
}
function purgeReplay(now) {
  for (const [id, expires] of replayed) if (expires <= now) replayed.delete(id);
}

export class ReplayGuard {
  constructor(state) { this.state = state; }

  async fetch(request) {
    const { requestId, expiresAt, now } = await request.json();
    if (typeof requestId !== "string" || !Number.isSafeInteger(expiresAt) || !Number.isSafeInteger(now)) return new Response(null, { status: 400 });
    const claimed = await this.state.storage.transaction(async (txn) => {
      const existing = await txn.get(requestId);
      if (typeof existing === "number" && existing > now) return false;
      await txn.put(requestId, expiresAt);
      return true;
    });
    if (!claimed) return new Response(null, { status: 409 });
    const alarm = await this.state.storage.getAlarm();
    const alarmMs = expiresAt * 1000;
    if (alarm === null || alarmMs < alarm) await this.state.storage.setAlarm(alarmMs);
    return new Response(null, { status: 201 });
  }

  async alarm() {
    const now = Math.floor(Date.now() / 1000);
    const entries = await this.state.storage.list({ limit: 1000 });
    const expired = [];
    let next = null;
    for (const [key, expiresAt] of entries) {
      if (expiresAt <= now) expired.push(key);
      else if (next === null || expiresAt < next) next = expiresAt;
    }
    if (expired.length) await this.state.storage.delete(expired);
    if (entries.size === 1000) next = Math.min(next ?? now + 1, now + 1);
    if (next !== null) await this.state.storage.setAlarm(next * 1000);
  }
}

async function claimReplay(env, requestId, expiresAt, now) {
  if (env.REPLAY_GUARD && typeof env.REPLAY_GUARD.idFromName === "function") {
    const id = env.REPLAY_GUARD.idFromName("d1-gateway-replay-v1");
    const response = await env.REPLAY_GUARD.get(id).fetch("https://replay.internal/claim", {
      method: "POST",
      body: JSON.stringify({ requestId, expiresAt, now }),
    });
    if (response.status === 409) throw new GatewayError(401, "replayed_request", "Request ID has already been used");
    if (!response.ok) throw new GatewayError(503, "replay_guard_unavailable", "Durable replay guard is unavailable");
    return;
  }
  if (String(env.ALLOW_IN_MEMORY_REPLAY ?? "false").toLowerCase() !== "true") {
    throw new GatewayError(503, "worker_not_configured", "REPLAY_GUARD Durable Object binding is required");
  }
  purgeReplay(now);
  if (replayed.has(requestId)) throw new GatewayError(401, "replayed_request", "Request ID has already been used");
  replayed.set(requestId, expiresAt);
}

async function authenticate(request, env, bodyBytes, now = Math.floor(Date.now() / 1000)) {
  const timestamp = request.headers.get("X-DB-Timestamp") || "";
  const requestId = request.headers.get("X-DB-Request-ID") || "";
  const supplied = (request.headers.get("X-DB-Signature") || "").toLowerCase();
  if (!/^\d{10}$/.test(timestamp) || !/^[0-9a-fA-F-]{16,128}$/.test(requestId) || !/^[a-f0-9]{64}$/.test(supplied)) {
    throw new GatewayError(401, "invalid_signature", "Required database signature headers are missing or malformed");
  }
  if (Math.abs(now - Number(timestamp)) > maxSkew(env)) throw new GatewayError(401, "expired_signature", "Request timestamp is expired");
  const digest = await sha256(bodyBytes);
  const target = new URL(request.url).pathname;
  const canonical = `v1\n${request.method.toUpperCase()}\n${target}\n${requestId}\n${timestamp}\n${digest}`;
  const expected = await hmac(configuredSecret(env), canonical);
  if (!equal(expected, supplied)) throw new GatewayError(401, "invalid_signature", "Database signature verification failed");
  await claimReplay(env, requestId, Number(timestamp) + maxSkew(env), now);
}

function validatePayload(payload) {
  if (!payload || (payload.mode !== "single" && payload.mode !== "batch") || !Array.isArray(payload.statements) || payload.statements.length < 1 || payload.statements.length > 100) {
    throw new GatewayError(400, "invalid_request", "mode and 1-100 statements are required");
  }
  if (payload.mode === "single" && payload.statements.length !== 1) throw new GatewayError(400, "invalid_request", "single mode accepts exactly one statement");
  return payload.statements.map((statement) => {
    if (!statement || typeof statement.sql !== "string" || !statement.sql.trim() || !Array.isArray(statement.params)) throw new GatewayError(400, "invalid_statement", "Each statement requires sql and params");
    if (statement.sql.length > 10000 || statement.params.length > 100) throw new GatewayError(400, "invalid_statement", "Statement exceeds configured limits");
    if (!["SELECT", "INSERT", "UPDATE", "DELETE", "WITH", "EXPLAIN"].includes(statement.sql.trim().split(/\s+/, 1)[0].toUpperCase())) throw new GatewayError(400, "invalid_statement", "Runtime gateway does not allow schema, transaction, or PRAGMA statements");
    if (statement.params.some((value) => value !== null && !["string", "number", "boolean"].includes(typeof value))) throw new GatewayError(400, "invalid_statement", "Bound parameters must be JSON scalar values");
    return { sql: statement.sql, params: statement.params };
  });
}
function isQuery(sql) {
  const normalized = sql.trim();
  return /^(SELECT|WITH|PRAGMA|EXPLAIN)\b/i.test(normalized) || /\bRETURNING\b/i.test(normalized);
}
async function executeOne(db, statement) {
  const prepared = db.prepare(statement.sql).bind(...statement.params);
  const result = isQuery(statement.sql) ? await prepared.all() : await prepared.run();
  const meta = result?.meta || {};
  return { rows: result?.results || [], meta: { changes: meta.changes ?? 0, last_row_id: meta.last_row_id ?? null } };
}
async function execute(db, mode, statements) {
  try {
    if (mode === "single") return [await executeOne(db, statements[0])];
    const prepared = statements.map((statement) => db.prepare(statement.sql).bind(...statement.params));
    const results = await db.batch(prepared);
    return results.map((result) => ({ rows: result?.results || [], meta: { changes: result?.meta?.changes ?? 0, last_row_id: result?.meta?.last_row_id ?? null } }));
  } catch (error) {
    const message = String(error?.message || error);
    if (/constraint|unique|foreign key|not null/i.test(message)) {
      throw new GatewayError(409, "database_integrity_error", "Database constraint rejected the operation");
    }
    throw new GatewayError(503, "database_unavailable", "Database operation failed");
  }
}

async function handle(request, env) {
  if (request.method !== "POST" || new URL(request.url).pathname !== "/internal/db") throw new GatewayError(404, "not_found", "Route not found");
  if (!env.DB || typeof env.DB.prepare !== "function") throw new GatewayError(503, "worker_not_configured", "D1 DB binding is not configured");
  const body = new Uint8Array(await request.arrayBuffer());
  if (body.byteLength > Number(env.MAX_REQUEST_BYTES ?? 1024 * 1024)) throw new GatewayError(413, "payload_too_large", "Request body exceeds configured limit");
  await authenticate(request, env, body);
  let payload;
  try { payload = JSON.parse(new TextDecoder().decode(body)); } catch { throw new GatewayError(400, "invalid_json", "Request body must be valid JSON"); }
  if (payload?.requestId !== request.headers.get("X-DB-Request-ID") || String(payload?.timestamp) !== request.headers.get("X-DB-Timestamp")) {
    throw new GatewayError(400, "invalid_request", "Body requestId/timestamp must match signed headers");
  }
  const statements = validatePayload(payload);
  const results = await execute(env.DB, payload.mode, statements);
  return json({ requestId: request.headers.get("X-DB-Request-ID"), results });
}

export default {
  async fetch(request, env) {
    try { return await handle(request, env); }
    catch (error) {
      if (error instanceof GatewayError) return json({ error: error.code, message: error.message, ...(error.details ? { details: error.details } : {}) }, error.status);
      console.error("Unhandled D1 gateway error", error);
      return json({ error: "internal_error", message: "Internal server error" }, 500);
    }
  },
};

export { authenticate, executeOne, execute, validatePayload };
