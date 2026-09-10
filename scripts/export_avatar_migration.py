"""Read-only exporter for importing legacy Wiki user avatars into Accounts."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.avatars import managed_avatar_path  # noqa: E402
from backend.config import get_database_path  # noqa: E402


def build_manifest(database_path: Path) -> dict:
    connection = sqlite3.connect(
        f"file:{database_path.resolve().as_posix()}?mode=ro",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT id, auth_sub, avatar_url FROM users "
            "WHERE avatar_url IS NOT NULL AND TRIM(avatar_url) <> '' ORDER BY id"
        ).fetchall()
    finally:
        connection.close()

    avatars = []
    errors = []
    for row in rows:
        source = f"wiki:{row['id']}"
        subject = str(row["auth_sub"] or "").strip()
        if not subject:
            errors.append({"source": source, "reason": "missing_central_sub"})
            continue
        path = managed_avatar_path(row["avatar_url"])
        if path is None:
            errors.append({"source": source, "reason": "avatar_not_locally_managed"})
        elif not path.is_file():
            errors.append({"source": source, "reason": "missing_avatar_file"})
        else:
            avatars.append(
                {
                    "source_user_id": str(row["id"]),
                    "central_sub": subject,
                    "avatar_path": str(path.resolve()),
                }
            )
    return {"version": 1, "avatars": avatars, "errors": errors}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=get_database_path())
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    manifest = build_manifest(arguments.database)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"ready": len(manifest["avatars"]), "errors": len(manifest["errors"])}))


if __name__ == "__main__":
    main()
