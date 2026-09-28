from __future__ import annotations

import io
import json
from types import SimpleNamespace
from urllib.error import URLError

import pytest
from fastapi import HTTPException

from backend import turnstile


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def test_siteverify_requires_expected_hostname_and_action(monkeypatch):
    monkeypatch.setattr(
        turnstile,
        "settings",
        SimpleNamespace(
            turnstile_secret_key="test-secret",
            frontend_base_url="https://nethub.wiki",
        ),
    )

    def fake_open(_request, timeout):
        assert timeout == 4
        return Response(json.dumps({
            "success": True,
            "hostname": "nethub.wiki",
            "action": "comment",
        }).encode())

    monkeypatch.setattr(turnstile, "urlopen", fake_open)
    turnstile.verify_turnstile("token", "comment")
    with pytest.raises(HTTPException) as mismatch:
        turnstile.verify_turnstile("token", "message")
    assert mismatch.value.status_code == 400


def test_missing_token_and_outage_fail_closed(monkeypatch):
    with pytest.raises(HTTPException) as missing:
        turnstile.verify_turnstile(None, "comment")
    assert missing.value.status_code == 400

    monkeypatch.setattr(
        turnstile,
        "settings",
        SimpleNamespace(
            turnstile_secret_key="test-secret",
            frontend_base_url="https://nethub.wiki",
        ),
    )

    def offline(_request, timeout):
        raise URLError("offline")

    monkeypatch.setattr(turnstile, "urlopen", offline)
    with pytest.raises(HTTPException) as outage:
        turnstile.verify_turnstile("token", "comment")
    assert outage.value.status_code == 503
