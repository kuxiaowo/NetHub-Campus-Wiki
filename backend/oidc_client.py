"""NetHub Accounts OIDC client and back-channel logout verification."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from sqlite3 import IntegrityError
import threading
import time
from typing import Any
from urllib.parse import urlsplit

from authlib.integrations.requests_client import OAuth2Session
from authlib.jose import JoseError, jwt
from authlib.oauth2 import OAuth2Error
import requests

from backend.config import settings
from backend.database import get_db_connection

OIDC_STATE_COOKIE = "campus_wiki_oidc_state"
LOGIN_ATTEMPT_TTL_SECONDS = 600
_CACHE_TTL_SECONDS = 300
_cache_lock = threading.Lock()
_discovery_cache: tuple[float, dict[str, Any]] | None = None
_jwks_cache: tuple[float, dict[str, Any]] | None = None


class OidcClientError(RuntimeError):
    """An identity-provider response could not be trusted or completed."""


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def safe_return_to(value: str | None) -> str:
    base = settings.frontend_base_url
    if not value:
        return base + "/"
    candidate = value.strip()
    if candidate.startswith("/") and not candidate.startswith("//"):
        return base + candidate
    parsed = urlsplit(candidate)
    allowed = urlsplit(base)
    if (
        parsed.scheme == allowed.scheme
        and parsed.netloc == allowed.netloc
        and not parsed.username
        and not parsed.password
    ):
        return candidate
    return base + "/"


def _trusted_provider_url(value: str, name: str) -> str:
    parsed = urlsplit(value)
    issuer = urlsplit(settings.oidc_issuer)
    if parsed.scheme != "https" or parsed.netloc != issuer.netloc:
        raise OidcClientError(f"账号中心发现文档中的 {name} 不可信")
    return value


def discovery(*, force: bool = False) -> dict[str, Any]:
    global _discovery_cache
    now = time.time()
    with _cache_lock:
        if not force and _discovery_cache and _discovery_cache[0] > now:
            return _discovery_cache[1]
    try:
        response = requests.get(
            settings.oidc_issuer + "/.well-known/openid-configuration",
            timeout=5,
            headers={
                "Accept": "application/json",
                "User-Agent": "NetHub-Campus-Wiki/1.0",
            },
        )
        response.raise_for_status()
        metadata = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise OidcClientError("暂时无法读取账号中心配置") from exc
    if metadata.get("issuer") != settings.oidc_issuer:
        raise OidcClientError("账号中心 Issuer 与本地配置不一致")
    for name in (
        "authorization_endpoint",
        "token_endpoint",
        "userinfo_endpoint",
        "jwks_uri",
    ):
        value = metadata.get(name)
        if not isinstance(value, str):
            raise OidcClientError(f"账号中心缺少 {name}")
        _trusted_provider_url(value, name)
    with _cache_lock:
        _discovery_cache = (now + _CACHE_TTL_SECONDS, metadata)
    return metadata


def provider_jwks(*, force: bool = False) -> dict[str, Any]:
    global _jwks_cache
    now = time.time()
    with _cache_lock:
        if not force and _jwks_cache and _jwks_cache[0] > now:
            return _jwks_cache[1]
    metadata = discovery(force=force)
    try:
        response = requests.get(
            metadata["jwks_uri"],
            timeout=5,
            headers={
                "Accept": "application/json",
                "User-Agent": "NetHub-Campus-Wiki/1.0",
            },
        )
        response.raise_for_status()
        keys = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise OidcClientError("暂时无法读取账号中心公钥") from exc
    if not isinstance(keys.get("keys"), list) or not keys["keys"]:
        raise OidcClientError("账号中心没有可用公钥")
    with _cache_lock:
        _jwks_cache = (now + _CACHE_TTL_SECONDS, keys)
    return keys


def begin_login(return_to: str | None) -> tuple[str, str]:
    metadata = discovery()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    now = int(time.time())
    destination = safe_return_to(return_to)
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM oidc_login_attempts WHERE expires_at <= %s", (now,)
            )
            cursor.execute(
                """
                INSERT INTO oidc_login_attempts
                  (state_hash, code_verifier, nonce, return_to, created_at, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    _digest(state),
                    verifier,
                    nonce,
                    destination,
                    now,
                    now + LOGIN_ATTEMPT_TTL_SECONDS,
                ),
            )
    client = OAuth2Session(
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        token_endpoint_auth_method="client_secret_basic",
        scope="openid profile",
        redirect_uri=settings.oidc_redirect_uri,
    )
    authorization_url, _ = client.create_authorization_url(
        metadata["authorization_endpoint"],
        state=state,
        nonce=nonce,
        code_challenge=challenge,
        code_challenge_method="S256",
    )
    return authorization_url, state


def _consume_attempt(state: str, cookie_state: str) -> dict[str, Any]:
    if not state or not cookie_state or not hmac.compare_digest(state, cookie_state):
        raise OidcClientError("登录 state 校验失败，请重新发起登录")
    now = int(time.time())
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM oidc_login_attempts WHERE state_hash = %s LIMIT 1",
                (_digest(state),),
            )
            attempt = cursor.fetchone()
            cursor.execute(
                "DELETE FROM oidc_login_attempts WHERE state_hash = %s",
                (_digest(state),),
            )
    if attempt is None or int(attempt["expires_at"]) <= now:
        raise OidcClientError("登录请求不存在或已过期，请重新发起登录")
    return attempt


def _validate_id_token(id_token: str, nonce: str) -> dict[str, Any]:
    claims_options = {
        "iss": {"essential": True, "value": settings.oidc_issuer},
        "aud": {"essential": True, "value": settings.oidc_client_id},
        "sub": {"essential": True},
        "exp": {"essential": True},
        "iat": {"essential": True},
        "nonce": {"essential": True, "value": nonce},
        "sid": {"essential": True},
    }
    last_error: Exception | None = None
    for force in (False, True):
        try:
            claims = jwt.decode(
                id_token,
                provider_jwks(force=force),
                claims_options=claims_options,
                claims_params={"nonce": nonce},
            )
            if claims.header.get("alg") != "RS256":
                raise ValueError("unexpected ID Token algorithm")
            claims.validate(leeway=30)
            return dict(claims)
        except (JoseError, ValueError) as exc:
            last_error = exc
    raise OidcClientError("账号中心 ID Token 校验失败") from last_error


def complete_login(code: str, state: str, cookie_state: str) -> dict[str, Any]:
    attempt = _consume_attempt(state, cookie_state)
    metadata = discovery()
    client = OAuth2Session(
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        token_endpoint_auth_method="client_secret_basic",
        scope="openid profile",
        redirect_uri=settings.oidc_redirect_uri,
    )
    try:
        token = client.fetch_token(
            metadata["token_endpoint"],
            code=code,
            code_verifier=attempt["code_verifier"],
            timeout=5,
        )
        id_token = token.get("id_token")
        if not isinstance(id_token, str):
            raise OidcClientError("账号中心未返回 ID Token")
        claims = _validate_id_token(id_token, attempt["nonce"])
        response = client.get(metadata["userinfo_endpoint"], timeout=5)
        response.raise_for_status()
        userinfo = response.json()
    except OidcClientError:
        raise
    except (OAuth2Error, requests.RequestException, ValueError) as exc:
        raise OidcClientError("账号中心暂时无法完成登录") from exc
    if not isinstance(userinfo, dict) or userinfo.get("sub") != claims.get("sub"):
        raise OidcClientError("UserInfo 与 ID Token 用户不一致")
    return {
        "sub": str(claims["sub"]),
        "sid": str(claims["sid"]),
        "preferred_username": str(
            userinfo.get("preferred_username") or claims.get("preferred_username") or ""
        ),
        "name": str(userinfo.get("name") or claims.get("name") or ""),
        "return_to": attempt["return_to"],
    }


def validate_logout_token(encoded_token: str) -> dict[str, Any]:
    options = {
        "iss": {"essential": True, "value": settings.oidc_issuer},
        "aud": {"essential": True, "value": settings.oidc_client_id},
        "iat": {"essential": True},
        "jti": {"essential": True},
        "events": {"essential": True},
    }
    try:
        claims = jwt.decode(encoded_token, provider_jwks(), claims_options=options)
        if claims.header.get("alg") != "RS256":
            raise ValueError("unexpected logout token algorithm")
        claims.validate(leeway=30)
    except (JoseError, ValueError) as exc:
        raise OidcClientError("退出通知签名无效") from exc
    events = claims.get("events") or {}
    event_name = "http://schemas.openid.net/event/backchannel-logout"
    if event_name not in events or not (claims.get("sub") or claims.get("sid")):
        raise OidcClientError("退出通知缺少必要声明")
    if "nonce" in claims:
        raise OidcClientError("退出通知不得包含 nonce")
    now = int(time.time())
    if abs(now - int(claims["iat"])) > 300:
        raise OidcClientError("退出通知已过期")
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO backchannel_logout_events (jti, received_at) VALUES (%s, %s)",
                    (str(claims["jti"]), now),
                )
                cursor.execute(
                    "DELETE FROM backchannel_logout_events WHERE received_at < %s",
                    (now - 86400,),
                )
    except IntegrityError:
        # A provider retries when its first successful response was lost. Treat
        # a verified duplicate as success so the retry queue can settle.
        result = dict(claims)
        result["_replayed"] = True
        return result
    result = dict(claims)
    result["_replayed"] = False
    return result
