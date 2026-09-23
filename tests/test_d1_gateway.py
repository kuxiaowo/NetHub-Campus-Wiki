import hashlib
import hmac
import json
from unittest.mock import Mock, patch

from backend.database import D1GatewayAdapter, D1GatewayError
from backend import auth_rate_limit


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
