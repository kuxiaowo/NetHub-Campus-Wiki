import test from "node:test";
import assert from "node:assert/strict";
import worker, { ReplayGuard, databaseFailureCategory } from "../src/worker.js";

const SECRET = "test-secret-012345678901234567890123";
const BASE = "https://db.example.test";
const encoder = new TextEncoder();
const hex = (bytes) => [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("");
async function signature(value) {
  const key = await crypto.subtle.importKey("raw", encoder.encode(SECRET), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return hex(await crypto.subtle.sign("HMAC", key, encoder.encode(value)));
}
async function request(payload, { id = crypto.randomUUID(), timestamp = Math.floor(Date.now() / 1000), bodyId = id, bodyTimestamp = timestamp, tamper = false } = {}) {
  const body = JSON.stringify({ ...payload, requestId: bodyId, timestamp: bodyTimestamp });
  const digest = hex(await crypto.subtle.digest("SHA-256", encoder.encode(body)));
  const canonical = `v1\nPOST\n/internal/db\n${id}\n${timestamp}\n${digest}`;
  const sig = await signature(canonical);
  return new Request(`${BASE}/internal/db`, {
    method: "POST", body,
    headers: { "X-DB-Request-ID": id, "X-DB-Timestamp": String(timestamp), "X-DB-Signature": tamper ? `${sig.slice(0, -1)}${sig.endsWith("0") ? "1" : "0"}` : sig },
  });
}
function env() {
  const calls = [];
  const db = {
    calls,
    prepare(sql) {
      return { bind(...params) { return { sql, params }; } };
    },
    async batch(statements) {
      calls.push(["batch", statements]);
      return statements.map((statement) => ({ results: [], meta: { changes: 1, last_row_id: 9 } }));
    },
  };
  db.prepare = (sql) => ({ bind(...params) {
    const bound = { sql, params };
    return {
      async all() { calls.push(["all", bound]); return { results: [{ id: 1 }], meta: { changes: 0, last_row_id: null } }; },
      async run() { calls.push(["run", bound]); return { results: [], meta: { changes: 1, last_row_id: 7 } }; },
    };
  } });
  return { HMAC_SECRET: SECRET, DB: db, MAX_CLOCK_SKEW_SECONDS: "300", ALLOW_IN_MEMORY_REPLAY: "true" };
}

test("single query returns rows and normalized metadata", async () => {
  const response = await worker.fetch(await request({ mode: "single", statements: [{ sql: "SELECT * FROM users WHERE id = ?", params: [1] }] }), env());
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.deepEqual(body.results[0], { rows: [{ id: 1 }], meta: { changes: 0, last_row_id: null } });
});

test("batch uses D1 batch and returns changes/last_row_id", async () => {
  const environment = env();
  const response = await worker.fetch(await request({ mode: "batch", statements: [
    { sql: "INSERT INTO users(name) VALUES (?)", params: ["a"] },
    { sql: "UPDATE users SET name = ? WHERE id = ?", params: ["b", 1] },
  ] }), environment);
  assert.equal(response.status, 200);
  assert.equal(environment.DB.calls[0][0], "batch");
  assert.deepEqual((await response.json()).results[0].meta, { changes: 1, last_row_id: 9 });
});

test("database failure classification does not expose SQL or row values", () => {
  assert.equal(databaseFailureCategory("D1_ERROR: daily rows written limit exceeded"), "quota_or_limit");
  assert.equal(databaseFailureCategory("SQLITE_BUSY: database is locked"), "temporary_unavailable");
  assert.equal(databaseFailureCategory("D1_ERROR: no such column: example"), "schema_or_sql");
  assert.equal(databaseFailureCategory("token_hash=secret-value"), "unclassified");
});

test("signature, timestamp and replay protections reject invalid requests", async () => {
  const environment = env();
  const stale = await worker.fetch(await request({ mode: "single", statements: [{ sql: "SELECT 1", params: [] }] }, { timestamp: Math.floor(Date.now() / 1000) - 301 }), environment);
  assert.equal(stale.status, 401);
  const altered = await worker.fetch(await request({ mode: "single", statements: [{ sql: "SELECT 1", params: [] }] }, { tamper: true }), environment);
  assert.equal(altered.status, 401);
  const replayId = crypto.randomUUID();
  const signed = await request({ mode: "single", statements: [{ sql: "SELECT 1", params: [] }] }, { id: replayId });
  assert.equal((await worker.fetch(signed, environment)).status, 200);
  const replay = await request({ mode: "single", statements: [{ sql: "SELECT 1", params: [] }] }, { id: replayId });
  assert.equal((await worker.fetch(replay, environment)).status, 401);
});

test("invalid payloads and missing binding fail without executing SQL", async () => {
  const environment = env();
  const bad = await worker.fetch(await request({ mode: "single", statements: [] }), environment);
  assert.equal(bad.status, 400);
  const ddl = await worker.fetch(await request({ mode: "single", statements: [{ sql: "DROP TABLE users", params: [] }] }), environment);
  assert.equal(ddl.status, 400);
  const mismatch = await worker.fetch(await request({ mode: "single", statements: [{ sql: "SELECT 1", params: [] }] }, { bodyId: "different-request-id" }), environment);
  assert.equal(mismatch.status, 400);
  const missing = await worker.fetch(await request({ mode: "single", statements: [{ sql: "SELECT 1", params: [] }] }), { HMAC_SECRET: SECRET });
  assert.equal(missing.status, 503);
  const noReplayGuard = env();
  delete noReplayGuard.ALLOW_IN_MEMORY_REPLAY;
  const failClosed = await worker.fetch(await request({ mode: "single", statements: [{ sql: "SELECT 1", params: [] }] }), noReplayGuard);
  assert.equal(failClosed.status, 503);
});

test("durable replay guard atomically rejects a duplicate request id", async () => {
  const values = new Map();
  let alarm = null;
  const storage = {
    async transaction(callback) {
      return callback({
        get: async (key) => values.get(key),
        put: async (key, value) => values.set(key, value),
      });
    },
    async getAlarm() { return alarm; },
    async setAlarm(value) { alarm = value; },
    async list() { return values; },
    async delete(keys) { for (const key of keys) values.delete(key); },
  };
  const guard = new ReplayGuard({ storage });
  const payload = JSON.stringify({ requestId: "durable-request-id", now: 100, expiresAt: 200 });
  const first = await guard.fetch(new Request("https://replay.internal/claim", { method: "POST", body: payload }));
  const duplicate = await guard.fetch(new Request("https://replay.internal/claim", { method: "POST", body: payload }));
  assert.equal(first.status, 201);
  assert.equal(duplicate.status, 409);
  assert.equal(alarm, 200000);
});
