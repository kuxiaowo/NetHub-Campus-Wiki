"""Transactional SQLite outbox and ordered, idempotent D1 delivery.

The application keeps using SQLite.  Install the capture triggers before taking
the baseline snapshot; do not arm delivery until that snapshot has been
reconciled to D1 and the D1 watermark has been set to its captured sequence.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

VERSION = 1
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
RESERVED = ("sqlite_", "_sync_", "_cf_")
SITE_ENV = {
    "accounts": ("ACCOUNTS_D1_GATEWAY_URL", "ACCOUNTS_D1_GATEWAY_SECRET"),
    "wiki": ("D1_GATEWAY_URL", "D1_GATEWAY_HMAC_SECRET"),
    "todo": ("TODO_D1_GATEWAY_URL", "TODO_D1_GATEWAY_SECRET"),
    "cas": ("D1_GATEWAY_URL", "D1_HMAC_SECRET"),
    "techx": ("MOOD_D1_GATEWAY_URL", "MOOD_D1_GATEWAY_SECRET"),
}


def quote(name: str) -> str:
    if not IDENTIFIER.fullmatch(name):
        raise ValueError("unsupported database identifier")
    return '"' + name + '"'


def tables(db: sqlite3.Connection) -> list[str]:
    return [
        row[0]
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        if not row[0].startswith(RESERVED)
    ]


def columns(db: sqlite3.Connection, table: str) -> tuple[list[str], list[str], str]:
    info = db.execute(f"PRAGMA table_info({quote(table)})").fetchall()
    names = [row[1] for row in info]
    primary = [row[1] for row in sorted(info, key=lambda row: row[5]) if row[5]]
    if not names or not primary:
        raise ValueError(f"{table}: capture requires a declared primary key")
    definition = json.dumps(
        [(row[1], row[2], row[3], row[4], row[5]) for row in info],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return names, primary, hashlib.sha256(definition.encode()).hexdigest()


def _json_object(prefix: str, names: list[str]) -> str:
    pieces = []
    for name in names:
        field = f"{prefix}.{quote(name)}"
        pieces.extend(
            (f"'{name}'", f"CASE WHEN typeof({field})='blob' THEN hex({field}) ELSE {field} END")
        )
    return "json_object(" + ",".join(pieces) + ")"


def _types_object(prefix: str, names: list[str]) -> str:
    pieces = []
    for name in names:
        pieces.extend((f"'{name}'", f"typeof({prefix}.{quote(name)})"))
    return "json_object(" + ",".join(pieces) + ")"


def _trigger_sql(
    table: str, operation: str, names: list[str], pk: list[str], schema_hash: str
) -> str:
    suffix = {"INSERT": "ai", "UPDATE": "au", "DELETE": "ad"}[operation]
    trigger = f"_sync_{table}_{suffix}"
    current = "OLD" if operation == "DELETE" else "NEW"
    row_json = "NULL" if operation == "DELETE" else _json_object("NEW", names)
    types_json = "NULL" if operation == "DELETE" else _types_object("NEW", names)
    old_pk = _json_object("OLD", pk) if operation == "UPDATE" else "NULL"
    return f"""CREATE TRIGGER {quote(trigger)} AFTER {operation} ON {quote(table)} BEGIN
        UPDATE _sync_clock SET seq=seq+1 WHERE id=1;
        INSERT INTO _sync_outbox
          (seq,event_id,table_name,operation,pk_json,old_pk_json,row_json,types_json,schema_hash)
        SELECT seq,lower(hex(randomblob(16))),'{table}','{operation.lower()}',
               {_json_object(current, pk)},{old_pk},{row_json},{types_json},'{schema_hash}'
          FROM _sync_clock WHERE id=1;
    END"""


def expected_triggers(db: sqlite3.Connection) -> dict[str, str]:
    result = {}
    for table in tables(db):
        names, pk, schema_hash = columns(db, table)
        for operation, suffix in (("INSERT", "ai"), ("UPDATE", "au"), ("DELETE", "ad")):
            result[f"_sync_{table}_{suffix}"] = _trigger_sql(
                table, operation, names, pk, schema_hash
            )
    return result


def connect(path: Path, *, write: bool = False) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=15, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=15000")
    if write:
        db.execute("PRAGMA synchronous=FULL")
    return db


def install(path: Path) -> None:
    db = connect(path, write=True)
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "CREATE TABLE IF NOT EXISTS _sync_clock "
            "(id INTEGER PRIMARY KEY CHECK(id=1), seq INTEGER NOT NULL)"
        )
        db.execute("INSERT OR IGNORE INTO _sync_clock(id,seq) VALUES(1,0)")
        db.execute("""CREATE TABLE IF NOT EXISTS _sync_outbox (
            seq INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE,
            table_name TEXT NOT NULL, operation TEXT NOT NULL,
            pk_json TEXT NOT NULL, old_pk_json TEXT, row_json TEXT,
            types_json TEXT, schema_hash TEXT NOT NULL,
            captured_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            acked_at TEXT, attempts INTEGER NOT NULL DEFAULT 0,
            last_error_code TEXT)""")
        db.execute("CREATE INDEX IF NOT EXISTS _sync_outbox_pending ON _sync_outbox(acked_at,seq)")
        db.execute("""CREATE TABLE IF NOT EXISTS _sync_control (
            id INTEGER PRIMARY KEY CHECK(id=1), ready INTEGER NOT NULL DEFAULT 0,
            baseline_seq INTEGER NOT NULL DEFAULT 0,
            capture_version INTEGER NOT NULL DEFAULT 1)""")
        db.execute("INSERT OR IGNORE INTO _sync_control(id) VALUES(1)")
        expected = expected_triggers(db)
        actual = {
            row[0]: row[1]
            for row in db.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name GLOB '_sync_*'"
            )
        }
        if actual and set(actual) != set(expected):
            raise RuntimeError(
                "capture trigger set differs from current schema; migration required"
            )
        for name, statement in expected.items():
            if name not in actual:
                db.execute(statement)
            elif "'" + columns(db, name[len("_sync_") : -3])[2] + "'" not in actual[name]:
                raise RuntimeError(f"{name}: schema changed after capture installation")
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    finally:
        db.close()


def verify_capture(db: sqlite3.Connection) -> None:
    expected = expected_triggers(db)
    actual = {
        row[0]: row[1]
        for row in db.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name GLOB '_sync_*'"
        )
    }
    if set(actual) != set(expected):
        raise RuntimeError("capture triggers missing or schema changed")
    for name, sql in actual.items():
        table = name[len("_sync_") : -3]
        if "'" + columns(db, table)[2] + "'" not in sql:
            raise RuntimeError(f"{name}: captured schema differs from current table")


def snapshot(source: Path, destination: Path) -> int:
    if destination.exists():
        raise FileExistsError(destination)
    src = connect(source)
    dst = connect(destination, write=True)
    try:
        verify_capture(src)
        src.backup(dst)
        seq = dst.execute("SELECT seq FROM _sync_clock WHERE id=1").fetchone()[0]
        if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("snapshot integrity check failed")
        if dst.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("snapshot foreign key check failed")
        return seq
    finally:
        src.close()
        dst.close()


class Gateway:
    def __init__(self, url: str, secret: str, timeout: float = 20.0):
        self.url = url.rstrip("/")
        if not self.url.endswith("/internal/db"):
            self.url += "/internal/db"
        if not self.url.startswith("https://") or not secret:
            raise ValueError("HTTPS gateway URL and secret required")
        self.secret = secret.encode()
        self.timeout = timeout

    def request(self, statements: list[tuple[str, list]]) -> list[dict]:
        rid = str(uuid.uuid4())
        timestamp = int(time.time())
        payload = {
            "requestId": rid,
            "timestamp": timestamp,
            "mode": "single" if len(statements) == 1 else "batch",
            "statements": [{"sql": sql, "params": params} for sql, params in statements],
        }
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        if len(raw) > 950_000:
            raise ValueError("event exceeds D1 gateway request limit")
        digest = hashlib.sha256(raw).hexdigest()
        message = f"v1\nPOST\n/internal/db\n{rid}\n{timestamp}\n{digest}".encode()
        signature = hmac.new(self.secret, message, hashlib.sha256).hexdigest()
        request = urllib.request.Request(
            self.url,
            raw,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": "NetHub-D1-Client/1.0",
                "X-DB-Timestamp": str(timestamp),
                "X-DB-Request-ID": rid,
                "X-DB-Signature": signature,
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = json.load(response)
        results = data.get("results")
        if not isinstance(results, list) or len(results) != len(statements):
            raise RuntimeError("invalid gateway response")
        return results


def event_hash(event: sqlite3.Row) -> str:
    fields = [
        "seq",
        "event_id",
        "table_name",
        "operation",
        "pk_json",
        "old_pk_json",
        "row_json",
        "types_json",
        "schema_hash",
    ]
    return hashlib.sha256(
        json.dumps(
            [event[field] for field in fields], separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def _predicate(pk: dict, *, prefix: str = "") -> tuple[str, list]:
    return " AND ".join(f"{prefix}{quote(name)} IS ?" for name in pk), list(pk.values())


def event_statements(
    event: sqlite3.Row, schema: dict[str, tuple[list[str], list[str], str]]
) -> list[tuple[str, list]]:
    seq = event["seq"]
    table = event["table_name"]
    if table not in schema or schema[table][2] != event["schema_hash"]:
        raise RuntimeError("event schema does not match current capture schema")
    names, pk_names, _ = schema[table]
    pk = json.loads(event["pk_json"])
    if list(pk) != pk_names:
        raise RuntimeError("invalid primary key payload")
    gate = (
        "(SELECT seq FROM _sync_watermark WHERE id=1)=? "
        "AND NOT EXISTS (SELECT 1 FROM _sync_events WHERE seq=?)"
    )
    result = []
    old_pk = json.loads(event["old_pk_json"]) if event["old_pk_json"] else None
    if event["operation"] == "delete" or (old_pk is not None and old_pk != pk):
        target = old_pk if old_pk is not None and event["operation"] != "delete" else pk
        where, values = _predicate(target)
        result.append(
            (f"DELETE FROM {quote(table)} WHERE {where} AND {gate}", values + [seq - 1, seq])
        )
    if event["operation"] in ("insert", "update"):
        row = json.loads(event["row_json"])
        types = json.loads(event["types_json"])
        if set(row) != set(names) or set(types) != set(names):
            raise RuntimeError("invalid row payload")
        if any(value == "blob" for value in types.values()):
            raise RuntimeError("binary row requires gateway BLOB support")
        values = [row[name] for name in names]
        if any(
            value is not None and not isinstance(value, (str, int, float, bool)) for value in values
        ):
            raise RuntimeError("invalid row value")
        updates = [name for name in names if name not in pk_names]
        conflict = (
            " DO UPDATE SET "
            + ",".join(f"{quote(name)}=excluded.{quote(name)}" for name in updates)
            if updates
            else " DO NOTHING"
        )
        sql = (
            f"INSERT INTO {quote(table)} ({','.join(map(quote, names))}) "
            f"SELECT {','.join('?' for _ in names)} WHERE {gate} "
            f"ON CONFLICT ({','.join(map(quote, pk_names))}){conflict}"
        )
        result.append((sql, values + [seq - 1, seq]))
    if not result:
        raise RuntimeError("unsupported outbox operation")
    digest = event_hash(event)
    result.append(
        (
            "INSERT INTO _sync_events(seq,event_id,payload_hash) "
            "SELECT ?,?,? WHERE (SELECT seq FROM _sync_watermark WHERE id=1)=? "
            "AND NOT EXISTS (SELECT 1 FROM _sync_events WHERE seq=?)",
            [seq, event["event_id"], digest, seq - 1, seq],
        )
    )
    result.append(
        (
            "UPDATE _sync_watermark SET seq=? WHERE id=1 AND seq=? "
            "AND EXISTS (SELECT 1 FROM _sync_events WHERE seq=? AND event_id=? AND payload_hash=?)",
            [seq, seq - 1, seq, event["event_id"], digest],
        )
    )
    result.append(("SELECT event_id,payload_hash FROM _sync_events WHERE seq=?", [seq]))
    if len(result) > 100 or any(len(sql) > 10_000 or len(params) > 100 for sql, params in result):
        raise RuntimeError("event exceeds D1 gateway statement limits")
    return result


def deliver(db: sqlite3.Connection, gateway: Gateway, event: sqlite3.Row, schema: dict) -> None:
    seq = event["seq"]
    digest = event_hash(event)
    existing = gateway.request(event_statements(event, schema))[-1]["rows"]
    if not existing or existing[0] != {"event_id": event["event_id"], "payload_hash": digest}:
        raise RuntimeError("D1 did not confirm event application")
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute(
            "UPDATE _sync_outbox "
            "SET acked_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),last_error_code=NULL "
            "WHERE seq=? AND acked_at IS NULL",
            (seq,),
        )
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise


def status(db: sqlite3.Connection) -> dict:
    clock = db.execute("SELECT seq FROM _sync_clock WHERE id=1").fetchone()[0]
    control = db.execute("SELECT ready,baseline_seq FROM _sync_control WHERE id=1").fetchone()
    row = db.execute(
        "SELECT COUNT(*), MIN(seq), MIN(captured_at), COALESCE(SUM(attempts),0) "
        "FROM _sync_outbox WHERE seq>? AND acked_at IS NULL",
        (control["baseline_seq"],),
    ).fetchone()
    oldest_seconds = None
    if row[2]:
        oldest_seconds = max(
            0,
            int(
                (
                    datetime.now(UTC) - datetime.fromisoformat(row[2].replace("Z", "+00:00"))
                ).total_seconds()
            ),
        )
    return {
        "local_seq": clock,
        "ready": bool(control["ready"]),
        "baseline_seq": control["baseline_seq"],
        "pending": row[0],
        "oldest_pending_seq": row[1],
        "oldest_wait_seconds": oldest_seconds,
        "failure_attempts": row[3],
    }


def worker(
    path: Path, gateway: Gateway, once: bool, poll_seconds: float, until_seq: int | None = None
) -> None:
    db = connect(path, write=True)
    try:
        verify_capture(db)
        schema = {table: columns(db, table) for table in tables(db)}
        backoff = 1.0
        while True:
            control = db.execute(
                "SELECT ready,baseline_seq FROM _sync_control WHERE id=1"
            ).fetchone()
            if not control["ready"]:
                raise RuntimeError("baseline not reconciled; delivery is disarmed")
            if until_seq is not None:
                if until_seq < control["baseline_seq"]:
                    raise ValueError("stop sequence precedes baseline")
                event = db.execute(
                    "SELECT * FROM _sync_outbox WHERE seq>? AND seq<=? "
                    "AND acked_at IS NULL ORDER BY seq LIMIT 1",
                    (control["baseline_seq"], until_seq),
                ).fetchone()
            else:
                event = db.execute(
                    "SELECT * FROM _sync_outbox WHERE seq>? "
                    "AND acked_at IS NULL ORDER BY seq LIMIT 1",
                    (control["baseline_seq"],),
                ).fetchone()
            if event is None:
                if until_seq is not None:
                    remote = gateway.request([("SELECT seq FROM _sync_watermark WHERE id=1", [])])[
                        0
                    ]["rows"]
                    if len(remote) != 1 or remote[0]["seq"] != until_seq:
                        raise RuntimeError("D1 watermark did not reach requested stop sequence")
                if once or until_seq is not None:
                    break
                time.sleep(poll_seconds)
                continue
            try:
                deliver(db, gateway, event, schema)
                backoff = 1.0
            except (
                RuntimeError,
                ValueError,
                urllib.error.HTTPError,
                urllib.error.URLError,
                TimeoutError,
            ) as exc:
                code = type(exc).__name__
                if isinstance(exc, urllib.error.HTTPError):
                    code += "_" + str(exc.code)
                db.execute(
                    "UPDATE _sync_outbox SET attempts=attempts+1,last_error_code=? WHERE seq=?",
                    (code, event["seq"]),
                )
                print(
                    f"D1 delivery blocked: seq={event['seq']} code={code}",
                    file=sys.stderr,
                    flush=True,
                )
                if once:
                    raise RuntimeError("D1 delivery blocked") from None
                time.sleep(backoff)
                backoff = min(backoff * 2, 300.0)
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("install", "verify", "snapshot", "status", "health", "arm", "worker")
    )
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--baseline-seq", type=int)
    parser.add_argument("--site", choices=tuple(SITE_ENV))
    parser.add_argument("--url-env")
    parser.add_argument("--secret-env")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--until-seq", type=int)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--max-age-seconds", type=int, default=120)
    parser.add_argument("--max-pending", type=int, default=10000)
    args = parser.parse_args()
    if args.site:
        args.url_env, args.secret_env = SITE_ENV[args.site]
    if args.command == "install":
        install(args.db)
        print("capture installed; delivery remains disarmed")
    elif args.command == "snapshot":
        if args.snapshot is None:
            parser.error("snapshot requires --snapshot")
        print(json.dumps({"snapshot_seq": snapshot(args.db, args.snapshot)}))
    elif args.command in ("verify", "status", "health"):
        db = connect(args.db)
        try:
            verify_capture(db)
            state = status(db)
            if args.command == "health":
                if not args.url_env or not args.secret_env:
                    parser.error("health requires --site or gateway environment variable names")
                gateway = Gateway(os.environ[args.url_env], os.environ[args.secret_env])
                remote = gateway.request([("SELECT seq FROM _sync_watermark WHERE id=1", [])])[0][
                    "rows"
                ]
                if len(remote) != 1:
                    raise RuntimeError("D1 watermark missing")
                state["d1_seq"] = remote[0]["seq"]
                state["lag_sequences"] = state["local_seq"] - state["d1_seq"]
                healthy = (
                    state["ready"]
                    and state["lag_sequences"] >= 0
                    and state["pending"] <= args.max_pending
                    and (state["oldest_wait_seconds"] or 0) <= args.max_age_seconds
                    and (state["pending"] > 0 or state["lag_sequences"] == 0)
                )
                state["healthy"] = healthy
                print(json.dumps(state, sort_keys=True))
                if not healthy:
                    raise SystemExit(2)
            else:
                print(json.dumps(state, sort_keys=True))
        finally:
            db.close()
    elif args.command == "arm":
        if args.baseline_seq is None or args.baseline_seq < 0:
            parser.error("arm requires --baseline-seq")
        if not args.snapshot or not args.url_env or not args.secret_env:
            parser.error("arm requires --snapshot, --url-env and --secret-env")
        snapshot_db = connect(args.snapshot)
        try:
            verify_capture(snapshot_db)
            snapshot_seq = snapshot_db.execute("SELECT seq FROM _sync_clock WHERE id=1").fetchone()[
                0
            ]
            if snapshot_seq != args.baseline_seq:
                raise RuntimeError("snapshot sequence differs from requested baseline")
        finally:
            snapshot_db.close()
        gateway = Gateway(os.environ[args.url_env], os.environ[args.secret_env])
        remote_rows = gateway.request([("SELECT seq FROM _sync_watermark WHERE id=1", [])])[0][
            "rows"
        ]
        if len(remote_rows) != 1 or remote_rows[0]["seq"] != args.baseline_seq:
            raise RuntimeError("D1 has not confirmed the baseline watermark")
        db = connect(args.db, write=True)
        try:
            verify_capture(db)
            current = db.execute("SELECT seq FROM _sync_clock WHERE id=1").fetchone()[0]
            if args.baseline_seq > current:
                raise ValueError("baseline exceeds local sequence")
            db.execute("BEGIN IMMEDIATE")
            try:
                updated = db.execute(
                    "UPDATE _sync_control SET ready=1,baseline_seq=? WHERE id=1 AND ready=0",
                    (args.baseline_seq,),
                )
                if updated.rowcount != 1:
                    raise RuntimeError("capture already armed")
                db.execute(
                    "UPDATE _sync_outbox SET acked_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                    "WHERE seq<=? AND acked_at IS NULL",
                    (args.baseline_seq,),
                )
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
            print("delivery armed")
        finally:
            db.close()
    elif args.command == "worker":
        if not args.url_env or not args.secret_env:
            parser.error("worker requires --url-env and --secret-env")
        gateway = Gateway(os.environ[args.url_env], os.environ[args.secret_env])
        worker(args.db, gateway, args.once, args.poll_seconds, args.until_seq)


if __name__ == "__main__":
    main()
