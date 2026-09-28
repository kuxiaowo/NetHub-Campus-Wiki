from __future__ import annotations

import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import URLError

from fastapi import HTTPException

from backend import turnstile


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class TurnstileTest(unittest.TestCase):
    settings = SimpleNamespace(
        turnstile_secret_key="test-secret",
        frontend_base_url="https://nethub.wiki",
    )

    def test_siteverify_requires_expected_hostname_and_action(self):
        def fake_open(_request, timeout):
            self.assertEqual(timeout, 4)
            return Response(json.dumps({
                "success": True,
                "hostname": "nethub.wiki",
                "action": "comment",
            }).encode())

        with patch.object(turnstile, "settings", self.settings), patch.object(
            turnstile, "urlopen", fake_open
        ):
            turnstile.verify_turnstile("token", "comment")
            with self.assertRaises(HTTPException) as mismatch:
                turnstile.verify_turnstile("token", "message")
        self.assertEqual(mismatch.exception.status_code, 400)

    def test_missing_token_and_outage_fail_closed(self):
        with self.assertRaises(HTTPException) as missing:
            turnstile.verify_turnstile(None, "comment")
        self.assertEqual(missing.exception.status_code, 400)

        def offline(_request, timeout):
            raise URLError("offline")

        with patch.object(turnstile, "settings", self.settings), patch.object(
            turnstile, "urlopen", offline
        ), self.assertRaises(HTTPException) as outage:
            turnstile.verify_turnstile("token", "comment")
        self.assertEqual(outage.exception.status_code, 503)
