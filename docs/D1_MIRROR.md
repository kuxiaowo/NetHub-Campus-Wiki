# SQLite → D1 mirror rollout

SQLite remains the only online read/write database. The mirror never changes
application routing, DNS, or failover behavior. Each site's outbox and trigger
set lives in that site's existing SQLite database. The worker polls every
second, applies events in sequence, and retries the oldest failed event with
exponential backoff. It does not delete acknowledged events.

## Required order

1. Merge the tested `developing` PR and deploy that merged commit. Do not enable
   `nethub-d1-mirror@SITE.service` yet. The application remains on SQLite.
2. Apply `scripts/d1_sync_migration.sql` to the **existing D1 database** using
   an authenticated Cloudflare D1 migration command. The HMAC runtime gateway
   intentionally rejects DDL and PRAGMA. Verify `_sync_watermark.seq = 0` and
   `_sync_events` is empty before the first baseline.
3. Run `d1_mirror.py install --db /srv/nethub/data/databases/SITE.sqlite3`
   with the site's venv Python. This takes a short SQLite write lock while it
   atomically installs triggers for every application table. Existing requests
   may briefly wait. Delivery remains disarmed. Re-run `verify` after any
   application schema migration; schema changes require trigger review and a
   fresh baseline before writes to newly added tables.
4. Run `d1_mirror.py snapshot --db ... --snapshot /srv/nethub/data/sqlite-sync-baselines/SITE-UTC.sqlite3`.
   The online backup contains a consistent `_sync_clock.seq`. Retain it until
   the site has passed verification. Keep the existing daily SQLite backups.
5. Run `d1_reconcile.py --snapshot SNAPSHOT --site SITE` for a count-only dry
   run. Inspect table and column differences. Then run with `--apply`. It
   deletes D1-only rows, upserts missing/changed rows, verifies every table,
   and sets the D1 watermark to the snapshot sequence. It does not mutate
   SQLite. For Todo, it leaves the two retired D1 tables empty and clears the
   old `ip` columns to empty strings; those values never return to SQLite.
   Full content audits consume D1 read quota. The reconciler pages by primary
   key so large tables are scanned once per audit instead of repeatedly reading
   earlier pages with `OFFSET`.
6. Run `d1_mirror.py arm --db ... --snapshot SNAPSHOT --baseline-seq SEQ --site SITE`.
   This checks the snapshot sequence and D1 watermark. Enable and start the
   `nethub-d1-mirror@SITE.service` and health timer. Confirm that local and D1
   sequences converge, all pending events are acknowledged, and row contents
   match. Repeat separately for the five sites.

Arming marks captured events through the verified snapshot sequence as covered
by that baseline. Later events retain their original sequence and are sent in
order.

For a content audit while SQLite remains live, stop only the mirror service,
take a new online SQLite snapshot at sequence `S`, then run
`d1_mirror.py worker --site SITE --db ... --until-seq S`. This bounded process
stops with D1 at exactly `S`; newer SQLite writes remain queued. Run
`d1_reconcile.py --snapshot SNAPSHOT --site SITE --verify-only` to compare
every application table and confirm the D1 watermark. Restart the regular
mirror service immediately afterward. No application service is stopped.

The D1 names are in each site's `cloudflare/nethub-d1-gateway/wrangler.toml`.
Do not print or log the gateway secret. Each unit reads the existing production
environment file. Do not start a service before its baseline is reconciled.

## Delivery and failure behavior

The SQLite row mutation and trigger-generated event commit together. A rollback
removes both. The event contains a durable sequence, random event ID, table,
primary key, row image or deletion marker, SQLite schema digest, and timestamp.
The D1 batch conditionally applies the row image, inserts its event marker, and
advances the watermark in one D1 transaction. A repeated delivery after a lost
response skips the row mutation and confirms the existing marker. D1 batch
transactions roll back all statements when one fails.

The worker uses current row images, so counters are set to their committed
value rather than incremented again. Failed events stay at the queue head.
Rows from one local multi-table transaction are delivered in order but may be
visible in D1 one row at a time while the worker catches up. D1 must not serve
reads or be used for failover during this stage.
HTTP failures, schema mismatches, and oversized events are visible in
`_sync_outbox.attempts` and `last_error_code`. The health service fails when
the oldest pending event exceeds 120 seconds or the queue exceeds 10,000.
`d1_mirror.py status` reports sequence, pending count, oldest age, and failure
attempts without exposing row contents. A failed health unit is a local
systemd alarm; an external paging destination must be configured separately.

WAL `synchronous=FULL` is set on each application's SQLite write connection.
This increases write latency but protects committed local transactions better
across sudden power loss. It does not make an asynchronous D1 copy zero-RPO:
loss of the whole server and disk before D1 application can still lose queued
events. No read routing or automatic switch to D1 is included.

## Limits and schema changes

The current HMAC gateway accepts at most 100 statements, 100 parameters and
10,000 SQL characters per statement, and a 1 MiB request body. Current
production rows were below 5 KiB at audit time. An event beyond these limits
blocks the queue and needs explicit repair; it is never skipped. Binary SQLite
values also block delivery until a reviewed BLOB transport is added. Current
application tables have no declared BLOB columns. Schema migrations must be
coordinated with trigger installation and D1 migration before the new schema
receives writes.
