"""Reconcile a captured SQLite snapshot to D1 before arming the mirror.

The source is a consistent snapshot produced by d1_mirror.py snapshot.  This
tool reports counts only; it never prints row contents or gateway credentials.
Delivery must remain disarmed throughout reconciliation.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections import defaultdict, deque
from pathlib import Path

if __package__:
    from . import d1_mirror
else:
    import d1_mirror


def normalized(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def same_row(left: dict, right: dict) -> bool:
    return all(normalized(left[key]) == normalized(right[key]) for key in left)


def select_rows(
    gateway: d1_mirror.Gateway, table: str, names: list[str], pk: list[str]
) -> dict[tuple, dict]:
    fields = ",".join(map(d1_mirror.quote, names))
    order = ",".join(map(d1_mirror.quote, pk))
    rows = {}
    last_key = None
    while True:
        where = ""
        params = []
        if last_key is not None:
            # Match SQLite's ascending NULL order and avoid rescanning every
            # earlier page of large tables with OFFSET.
            after = []
            for index, name in enumerate(pk):
                prefix = []
                for earlier, value in zip(pk[:index], last_key[:index], strict=True):
                    prefix.append(f"{d1_mirror.quote(earlier)} IS ?")
                    params.append(value)
                if last_key[index] is None:
                    greater = f"{d1_mirror.quote(name)} IS NOT NULL"
                else:
                    greater = f"{d1_mirror.quote(name)} > ?"
                    params.append(last_key[index])
                after.append("(" + " AND ".join([*prefix, greater]) + ")")
            where = " WHERE " + " OR ".join(after)
        sql = (
            f"SELECT {fields} FROM {d1_mirror.quote(table)}{where} "
            f"ORDER BY {order} LIMIT 200"
        )
        page = gateway.request([(sql, params)])[0]["rows"]
        for row in page:
            key = tuple(row[name] for name in pk)
            if key in rows:
                raise RuntimeError(f"{table}: duplicate D1 primary key")
            rows[key] = row
        if len(page) < 200:
            break
        last_key = tuple(page[-1][name] for name in pk)
    return rows


def dependency_order(db: sqlite3.Connection, tables: list[str]) -> list[str]:
    names = set(tables)
    parents = defaultdict(set)
    children = defaultdict(set)
    for table in tables:
        for row in db.execute(f"PRAGMA foreign_key_list({d1_mirror.quote(table)})"):
            parent = row[2]
            if parent in names and parent != table:
                parents[table].add(parent)
                children[parent].add(table)
    queue = deque(sorted(table for table in tables if not parents[table]))
    order = []
    while queue:
        table = queue.popleft()
        order.append(table)
        for child in sorted(children[table]):
            parents[child].remove(table)
            if not parents[child]:
                queue.append(child)
    if len(order) != len(tables):
        raise RuntimeError("cross-table foreign key cycle needs manual baseline ordering")
    return order


def inspect_schema(db: sqlite3.Connection, gateway: d1_mirror.Gateway, site: str) -> list[str]:
    local = set(d1_mirror.tables(db))
    remote = {
        row["name"]
        for row in gateway.request([("SELECT name FROM sqlite_master WHERE type='table'", [])])[0][
            "rows"
        ]
        if not row["name"].startswith(d1_mirror.RESERVED)
    }
    old_todo = {"visit_logs", "registration_attempt_logs"} if site == "todo" else set()
    if local != remote - old_todo:
        raise RuntimeError(
            f"table mismatch: local_only={sorted(local - remote)} "
            f"d1_only={sorted(remote - local - old_todo)}"
        )
    for table in sorted(old_todo & remote):
        count = gateway.request([(f"SELECT COUNT(*) AS n FROM {d1_mirror.quote(table)}", [])])[0][
            "rows"
        ][0]["n"]
        if count:
            raise RuntimeError(f"{table}: retired D1 table must remain empty")
    for table in sorted(local):
        names, pk, _ = d1_mirror.columns(db, table)
        result = gateway.request(
            [(f"SELECT name,pk,\"notnull\",dflt_value FROM pragma_table_info('{table}')", [])]
        )[0]["rows"]
        d1_cols = {row["name"]: row for row in result}
        if set(names) - set(d1_cols):
            raise RuntimeError(f"{table}: D1 missing SQLite columns")
        d1_pk = [row["name"] for row in sorted(result, key=lambda row: row["pk"]) if row["pk"]]
        if d1_pk != pk:
            raise RuntimeError(f"{table}: primary key differs")
        extras = set(d1_cols) - set(names)
        expected_extras = (
            {"ip"}
            if site == "todo" and table in ("operation_logs", "installer_download_logs")
            else set()
        )
        if extras != expected_extras:
            raise RuntimeError(f"{table}: unexpected D1-only columns {sorted(extras)}")
        for name in extras:
            if d1_cols[name]["notnull"] and d1_cols[name]["dflt_value"] is None:
                raise RuntimeError(f"{table}: D1-only column lacks default")
    return dependency_order(db, sorted(local))


def differences(db: sqlite3.Connection, gateway: d1_mirror.Gateway, order: list[str]):
    deletes = {}
    upserts = {}
    summary = {}
    for table in order:
        names, pk, _ = d1_mirror.columns(db, table)
        local = {
            tuple(row[name] for name in pk): dict(row)
            for row in db.execute(f"SELECT * FROM {d1_mirror.quote(table)}")
        }
        remote = select_rows(gateway, table, names, pk)
        missing = sorted(local.keys() - remote.keys())
        extra = sorted(remote.keys() - local.keys())
        changed = sorted(
            key for key in local.keys() & remote.keys() if not same_row(local[key], remote[key])
        )
        deletes[table] = [(pk, key) for key in extra]
        upserts[table] = [(names, local[key], pk) for key in missing + changed]
        summary[table] = {
            "sqlite_only": len(missing),
            "d1_only": len(extra),
            "changed": len(changed),
        }
    return deletes, upserts, summary


def delete_statement(table: str, pk: list[str], key: tuple) -> tuple[str, list]:
    where = " AND ".join(f"{d1_mirror.quote(name)} IS ?" for name in pk)
    return f"DELETE FROM {d1_mirror.quote(table)} WHERE {where}", list(key)


def upsert_statement(table: str, names: list[str], row: dict, pk: list[str]) -> tuple[str, list]:
    updates = [name for name in names if name not in pk]
    conflict = (
        " DO UPDATE SET "
        + ",".join(f"{d1_mirror.quote(name)}=excluded.{d1_mirror.quote(name)}" for name in updates)
        if updates
        else " DO NOTHING"
    )
    sql = (
        f"INSERT INTO {d1_mirror.quote(table)} ({','.join(map(d1_mirror.quote, names))}) "
        f"VALUES ({','.join('?' for _ in names)}) "
        f"ON CONFLICT ({','.join(map(d1_mirror.quote, pk))}){conflict}"
    )
    return sql, [row[name] for name in names]


def apply_batches(gateway: d1_mirror.Gateway, statements: list[tuple[str, list]]) -> None:
    for start in range(0, len(statements), 40):
        batch = statements[start : start + 40]
        if any(len(sql) > 10_000 or len(params) > 100 for sql, params in batch):
            raise RuntimeError("baseline statement exceeds D1 gateway limits")
        gateway.request(batch)


def reconcile(snapshot: Path, gateway: d1_mirror.Gateway, site: str, apply: bool, migration_watermark: int | None = None) -> dict:
    db = d1_mirror.connect(snapshot)
    try:
        d1_mirror.verify_capture(db)
        control = db.execute("SELECT ready FROM _sync_control WHERE id=1").fetchone()
        if control[0]:
            raise RuntimeError("snapshot was taken after delivery was armed")
        baseline_seq = db.execute("SELECT seq FROM _sync_clock WHERE id=1").fetchone()[0]
        d1_state = gateway.request([("SELECT seq FROM _sync_watermark WHERE id=1", [])])[0]["rows"]
        previous_seq = 0 if migration_watermark is None else migration_watermark
        if previous_seq < 0 or previous_seq > baseline_seq:
            raise RuntimeError("Migration watermark exceeds snapshot sequence")
        if len(d1_state) != 1 or d1_state[0]["seq"] not in (previous_seq, baseline_seq):
            raise RuntimeError("D1 watermark is incompatible with this baseline")
        applied = gateway.request([("SELECT COUNT(*) AS n FROM _sync_events", [])])[0]["rows"][0][
            "n"
        ]
        if applied and migration_watermark is None:
            raise RuntimeError("D1 already contains live sync events")
        order = inspect_schema(db, gateway, site)
        deletes, upserts, before = differences(db, gateway, order)
        result = {"snapshot_seq": baseline_seq, "before": before, "applied": False}
        if not apply:
            return result
        for table in reversed(order):
            apply_batches(gateway, [delete_statement(table, pk, key) for pk, key in deletes[table]])
        for table in order:
            apply_batches(
                gateway,
                [upsert_statement(table, names, row, pk) for names, row, pk in upserts[table]],
            )
        if site == "todo":
            for table in ("operation_logs", "installer_download_logs"):
                gateway.request([(f"UPDATE {d1_mirror.quote(table)} SET ip='' WHERE ip<>''", [])])
                remaining = gateway.request(
                    [(f"SELECT COUNT(*) AS n FROM {d1_mirror.quote(table)} WHERE ip<>''", [])]
                )[0]["rows"][0]["n"]
                if remaining:
                    raise RuntimeError(f"{table}: old D1 IP values remain")
        _, _, after = differences(db, gateway, order)
        if any(any(count for count in row.values()) for row in after.values()):
            raise RuntimeError("D1 baseline verification failed")
        if d1_state[0]["seq"] == previous_seq:
            gateway.request(
                [("UPDATE _sync_watermark SET seq=? WHERE id=1 AND seq=?", [baseline_seq, previous_seq])]
            )
        state = gateway.request([("SELECT seq FROM _sync_watermark WHERE id=1", [])])[0]["rows"][0][
            "seq"
        ]
        if state != baseline_seq:
            raise RuntimeError("D1 baseline watermark not confirmed")
        result["after"] = after
        result["applied"] = True
        return result
    finally:
        db.close()


def verify(snapshot: Path, gateway: d1_mirror.Gateway, site: str) -> dict:
    db = d1_mirror.connect(snapshot)
    try:
        d1_mirror.verify_capture(db)
        seq = db.execute("SELECT seq FROM _sync_clock WHERE id=1").fetchone()[0]
        rows = gateway.request([("SELECT seq FROM _sync_watermark WHERE id=1", [])])[0]["rows"]
        if len(rows) != 1 or rows[0]["seq"] != seq:
            raise RuntimeError("D1 watermark does not match verification snapshot")
        order = inspect_schema(db, gateway, site)
        _, _, summary = differences(db, gateway, order)
        return {
            "snapshot_seq": seq,
            "matches": not any(any(row.values()) for row in summary.values()),
            "differences": summary,
        }
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument(
        "--site", choices=("accounts", "wiki", "todo", "cas", "techx"), required=True
    )
    parser.add_argument("--url-env")
    parser.add_argument("--secret-env")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--migration-watermark", type=int, help="Confirmed D1 sequence after stopping delivery; retain existing event history during schema migration")
    args = parser.parse_args()
    url_env, secret_env = d1_mirror.SITE_ENV[args.site]
    gateway = d1_mirror.Gateway(
        os.environ[args.url_env or url_env], os.environ[args.secret_env or secret_env]
    )
    if args.verify_only and args.apply:
        parser.error("--verify-only cannot be combined with --apply")
    result = (
        verify(args.snapshot, gateway, args.site)
        if args.verify_only
        else reconcile(args.snapshot, gateway, args.site, args.apply, args.migration_watermark)
    )
    print(json.dumps(result, sort_keys=True))
    if args.verify_only and not result["matches"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
