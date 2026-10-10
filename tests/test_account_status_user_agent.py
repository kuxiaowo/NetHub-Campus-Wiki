"""Exercise the status client against an edge that rejects generic urllib clients."""

import base64
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from nethub_status import read_account_status


class AccountStatusUserAgentTests(unittest.TestCase):
    def test_edge_accepts_status_client_without_bypassing_account_restrictions(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                requests.append((self.headers.get("User-Agent"), self.headers.get("Authorization")))
                if self.headers.get("User-Agent") != "NetHub-AccountStatus/1.0":
                    self.send_response(403)
                    self.end_headers()
                    return
                body = json.dumps({"active": False, "emailVerified": True}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status = read_account_status(
                f"http://127.0.0.1:{server.server_port}", "wiki", "test-secret", "member"
            )
            self.assertEqual(status, {"active": False, "emailVerified": True})
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0][1], "Basic " + base64.b64encode(b"wiki:test-secret").decode())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
