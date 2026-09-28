"""Transactional schema changes used by deployment and CAS startup."""

import sqlite3

from .site import SCHEMA

CAS_COMMENTS = """
CREATE TABLE comments_new (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 gallery_id INTEGER NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 parent_id INTEGER REFERENCES comments(id) ON DELETE CASCADE,
 content TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'visible' CHECK(status IN ('visible','hidden','deleted')),
 created_at TEXT NOT NULL
);
INSERT INTO comments_new SELECT * FROM comments;
DROP TABLE comments;
ALTER TABLE comments_new RENAME TO comments;
CREATE INDEX idx_comments_gallery_status ON comments(gallery_id,status);
"""
CAS_MIGRATION = (
    "PRAGMA foreign_keys=OFF; BEGIN IMMEDIATE;\n"
    + CAS_COMMENTS
    + SCHEMA
    + "PRAGMA user_version=5; COMMIT; PRAGMA foreign_keys=ON;"
)


def statements(sql):
    """Run a script without sqlite3.executescript's implicit transaction commit."""
    buffer = ""
    for char in sql:
        buffer += char
        if char == ";" and sqlite3.complete_statement(buffer):
            yield buffer
            buffer = ""
    if buffer.strip():
        raise ValueError("Incomplete migration statement")


def apply(connection, site):
    if not connection.in_transaction:
        raise RuntimeError("Migration requires an explicit write transaction")
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if site == "wiki":
        if version not in {15, 16, 17}:
            raise ValueError("Wiki requires schema version 15, 16 or 17")
        if version == 15:
            connection.execute(
                "ALTER TABLE auth_sessions ADD COLUMN turnstile_verified_at INTEGER"
            )
        sql, target = SCHEMA, 17
    elif site == "cas":
        if version not in {4, 5}:
            raise ValueError("CAS requires schema version 4 or 5")
        sql, target = (CAS_COMMENTS if version == 4 else "") + SCHEMA, 5
    else:
        raise ValueError("Unknown site")
    for statement in statements(sql):
        connection.execute(statement)
    connection.execute(f"PRAGMA user_version={target}")
    if connection.execute("PRAGMA foreign_key_check").fetchone():
        raise RuntimeError("Migration foreign key check failed")
