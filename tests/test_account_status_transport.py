import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from nethub_status import AccountStatusUnavailable, read_account_status


def test_redirect_is_blocked_before_credentials_leave_endpoint():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            received.append((self.path, self.headers.get("Authorization")))
            self.send_response(302)
            self.send_header("Location", "/credential-leak")
            self.end_headers()

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(AccountStatusUnavailable):
            read_account_status(
                f"http://127.0.0.1:{server.server_port}", "wiki", "secret", "member"
            )
        assert len(received) == 1
        assert received[0][0].startswith("/api/client/account-status?")
        assert received[0][1].startswith("Basic ")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize(
    "body", [b"[]", b'{"active":1,"emailVerified":true}', b"x" * 4097]
)
def test_invalid_status_payload_is_unavailable(monkeypatch, body):
    from contextlib import nullcontext

    class Response:
        def read(self, limit):
            return body[:limit]

        def geturl(self):
            return "https://accounts.test/api/client/account-status?sub=member"

    class Opener:
        def open(self, request, timeout):
            return nullcontext(Response())

    monkeypatch.setattr("nethub_status.build_opener", lambda *args: Opener())
    with pytest.raises(AccountStatusUnavailable):
        read_account_status("https://accounts.test", "wiki", "secret", "member")
