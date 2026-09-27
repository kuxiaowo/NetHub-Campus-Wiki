import hashlib
import hmac
import json
from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

from backend.database import Connection, D1GatewayAdapter, D1GatewayError
from backend import auth_rate_limit, comments, database, projects, resources


def test_d1_gateway_uses_shared_canonical_signature():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"results": [{"rows": [{"ok": 1}], "meta": {"changes": 0, "last_row_id": None}}]}
    with patch("backend.database.uuid.uuid4", return_value="req-1"), patch(
        "backend.database.time.time", return_value=1700000000
    ), patch("backend.database.requests.post", return_value=response) as post:
        result = D1GatewayAdapter("https://db.example", "secret", 3).execute(
            "SELECT %s AS ok", (1,)
        )

    body = post.call_args.kwargs["data"]
    headers = post.call_args.kwargs["headers"]
    digest = hashlib.sha256(body).hexdigest()
    canonical = "\n".join(("v1", "POST", "/internal/db", "req-1", "1700000000", digest))
    expected = hmac.new(b"secret", canonical.encode(), hashlib.sha256).hexdigest()
    assert result["rows"] == [{"ok": 1}]
    assert headers["X-DB-Request-ID"] == "req-1"
    assert headers["X-DB-Timestamp"] == "1700000000"
    assert headers["X-DB-Signature"] == expected
    assert json.loads(body)["statements"][0]["sql"] == "SELECT ? AS ok"


def test_d1_cursor_maps_changes_and_last_row_id():
    adapter = D1GatewayAdapter("https://db.example", "secret", 3)
    with patch.object(adapter, "_request", return_value=[{"rows": [], "meta": {"changes": 2, "last_row_id": 9}}]):
        from backend.database import Cursor

        cursor = Cursor(adapter=adapter).execute("UPDATE items SET x = %s", (1,))
        assert cursor.rowcount == 2
        assert cursor.lastrowid == 9


def test_d1_gateway_preserves_structured_http_error():
    response = Mock()
    response.ok = False
    response.status_code = 503
    response.json.return_value = {
        "error": "database_unavailable",
        "code": "database_unavailable",
        "message": "D1 unavailable",
    }
    with patch("backend.database.requests.post", return_value=response):
        try:
            D1GatewayAdapter("https://db.example", "secret", 3).execute("SELECT 1")
        except D1GatewayError as exc:
            assert exc.status == 503
            assert exc.code == "database_unavailable"
            assert str(exc) == "D1 unavailable"
        else:
            raise AssertionError("expected D1GatewayError")


class _CursorContext:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _D1Connection:
    _adapter = object()

    def __init__(self, attempt_count):
        self.attempt_count = attempt_count
        self.batches = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return _CursorContext()

    def batch(self, statements):
        self.batches.append(statements)
        return [
            {"rows": [], "meta": {"changes": 0}},
            {
                "rows": [{"window_started_at": 1_700_000_000, "attempt_count": self.attempt_count}],
                "meta": {"changes": 1},
            },
        ]


def test_d1_fixed_window_consumes_quota_with_atomic_upsert(monkeypatch):
    connection = _D1Connection(attempt_count=2)
    monkeypatch.setattr(auth_rate_limit, "get_db_connection", lambda: connection)
    monkeypatch.setattr(auth_rate_limit.time, "time", lambda: 1_700_000_001)

    auth_rate_limit._consume_fixed_window(
        "login-ip", "127.0.0.1", limit=2, window_seconds=60, detail="limited"
    )

    assert len(connection.batches) == 1
    upsert_sql = connection.batches[0][1][0]
    assert "ON CONFLICT(bucket_key) DO UPDATE" in upsert_sql
    assert "RETURNING window_started_at, attempt_count" in upsert_sql


class _SQLiteBackedGateway(D1GatewayAdapter):
    """Execute gateway statements against SQLite while counting HTTP roundtrips."""

    def __init__(self, database_path):
        super().__init__("https://db.example", "test-secret", 3)
        self.database_path = database_path
        self.calls = []

    def _request(self, statements, mode):
        self.calls.append((mode, statements))
        connection = database._open_connection(self.database_path)
        try:
            results = []
            for statement in statements:
                cursor = connection.execute(statement["sql"], statement["params"])
                rows = cursor.fetchall() if cursor.description else []
                results.append({
                    "rows": rows,
                    "meta": {"changes": max(cursor.rowcount, 0), "last_row_id": cursor.lastrowid},
                })
            connection.commit()
            return results
        finally:
            connection.close()


def _create_page_database(path):
    database._initialize_database(path)
    with closing(database._open_connection(path)) as connection:
        connection.executescript("""
            INSERT INTO users (id, username, password_hash, display_name)
              VALUES (1, 'reader', 'test', 'Reader');
            INSERT INTO project_categories (name, sort_order) VALUES ('CAS', 1);
            INSERT INTO projects (id, name, leader, members, category, year, description)
              VALUES (1, 'Project', 'Reader', 'Reader', 'CAS', 2026, 'Project description');
            INSERT INTO people (id, display_name, user_id) VALUES (1, 'Reader', 1);
            INSERT INTO project_members (project_id, person_id, role, display_name_snapshot)
              VALUES (1, 1, 'leader', 'Reader');
            INSERT INTO resources (id, title, year, category, label, image, resource_url)
              VALUES (1, 'Resource', 2025, 'other', 'Other', '', 'https://example.com/file');
            INSERT INTO photo_activities (id, activity, description, year)
              VALUES (1, 'Photos', 'Activity', 2024);
            INSERT INTO photo_items (activity_id, title, image_url, sort_order)
              VALUES (1, 'Later', 'https://example.com/later.jpg', 20),
                     (1, 'First', 'https://example.com/first.jpg', 10);
            INSERT INTO comments (id, target_type, target_id, user_id, content)
              VALUES (1, 'project', 1, 1, 'Root');
            INSERT INTO comments (id, target_type, target_id, user_id, parent_id, root_id, content)
              VALUES (2, 'project', 1, 1, 1, 1, 'Reply');
            INSERT INTO comments (id, target_type, target_id, user_id, content, status)
              VALUES (3, 'project', 1, 1, '', 'deleted'),
                     (4, 'project', 1, 1, 'Hidden', 'hidden');
        """)


class PageReadRoundtripTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database_path = Path(temporary.name) / "page-reads.db"
        _create_page_database(self.database_path)
        self.gateway = _SQLiteBackedGateway(self.database_path)

    def test_page_reads_match_sqlite_with_fewer_gateway_roundtrips(self):
        sqlite_factory = lambda: Connection(database._open_connection(self.database_path))
        d1_factory = lambda: Connection(adapter=self.gateway)
        calls = [
            (projects, projects.list_meta, 1),
            (projects, lambda: projects.get_project(1, track_view=False), 1),
            (resources, resources.list_resource_meta, 1),
            (resources, resources.list_photo_activities, 1),
            (resources, lambda: resources.get_resource(1, track_view=False), 1),
            (comments, lambda: comments.list_comments('project', 1, 'hot', 1, 10, None), 2),
        ]
        for module, call, expected_roundtrips in calls:
            with patch.object(module, 'get_db_connection', sqlite_factory):
                expected = call()
            with patch.object(module, 'get_db_connection', d1_factory):
                self.gateway.calls.clear()
                self.assertEqual(call(), expected)
                self.assertEqual(len(self.gateway.calls), expected_roundtrips)

        with patch.object(comments, 'get_db_connection', d1_factory):
            self.gateway.calls.clear()
            empty = comments.list_comments('resource', 1, 'hot', 1, 10, None)
            self.assertEqual(empty['data'], [])
            self.assertEqual(len(self.gateway.calls), 1)
            with self.assertRaises(HTTPException) as error:
                comments.list_comments('project', 999, 'hot', 1, 10, None)
            self.assertEqual(error.exception.status_code, 404)

    def test_tracked_details_batch_write_and_read(self):
        d1_factory = lambda: Connection(adapter=self.gateway)
        with patch.object(projects, 'get_db_connection', d1_factory), patch.object(
            resources, 'get_db_connection', d1_factory
        ):
            self.assertEqual(projects.get_project(1, track_view=True)['popularity'], 1)
            self.assertEqual(len(self.gateway.calls), 1)
            self.assertEqual(len(self.gateway.calls[0][1]), 3)
            self.gateway.calls.clear()
            self.assertEqual(resources.get_resource(1, track_view=True)['hot'], 1)
            self.assertEqual(len(self.gateway.calls), 1)
            self.assertEqual(len(self.gateway.calls[0][1]), 2)

            self.gateway.calls.clear()
            activity = resources.get_activity_photo_detail(1, track_view=True)
            self.assertEqual(activity['activity']['hot'], 1)
            self.assertEqual(len(self.gateway.calls[0][1]), 2)

            self.gateway.calls.clear()
            self.assertIsNone(projects.get_project(999, track_view=True))
            self.assertEqual(len(self.gateway.calls), 1)
