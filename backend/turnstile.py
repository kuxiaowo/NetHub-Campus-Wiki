"""Cloudflare Turnstile verification for user-authored content."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from fastapi import HTTPException

from backend.config import settings


def verify_turnstile(token: str | None, action: str) -> None:
    if not token or len(token) > 2048:
        raise HTTPException(status_code=400, detail="请完成人机验证")
    if not settings.turnstile_secret_key:
        raise HTTPException(status_code=503, detail="人机验证暂不可用")
    body = urlencode(
        {"secret": settings.turnstile_secret_key, "response": token}
    ).encode("ascii")
    submission = UrlRequest(
        "https://challenges.cloudflare.com/turnstile/v0/siteverify",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(submission, timeout=4) as response:
            result = json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="人机验证暂不可用") from exc
    if not (
        result.get("success") is True
        and result.get("hostname") == urlsplit(settings.frontend_base_url).hostname
        and result.get("action") == action
    ):
        raise HTTPException(status_code=400, detail="人机验证未通过，请重试")
