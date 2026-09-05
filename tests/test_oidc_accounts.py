"""NetHub Accounts OIDC and Wiki-local session regression tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from authlib.jose import JsonWebKey, jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.auth import (
    SESSION_COOKIE_NAME,
    create_session,
    get_current_user_from_token,
    provision_oidc_user,
    revoke_sessions,
)
from backend.database import get_db_connection
from backend.grant_admin import set_admin_role
from backend.main import app
from backend.oidc_client import (
    OIDC_STATE_COOKIE,
    OidcClientError,
    _consume_attempt,
    _validate_id_token,
    begin_login,
    complete_login,
    safe_return_to,
    validate_logout_token,
)


class AccountsOidcTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "wiki.db"
        self.database_patch = patch(
            "backend.database.get_database_path", return_value=self.database_path
        )
        self.database_patch.start()
        self.fake_settings = SimpleNamespace(
            oidc_issuer="https://accounts.example.test",
            oidc_client_id="campus-wiki",
            oidc_client_secret="s" * 48,
            oidc_redirect_uri="https://wiki.example.test/api/auth/callback",
            frontend_base_url="https://wiki.example.test",
            auth_cookie_secure=True,
            auth_session_idle_seconds=7 * 24 * 60 * 60,
            auth_session_absolute_seconds=30 * 24 * 60 * 60,
            wiki_admin_auth_subs=(),
            cors_origins=("https://wiki.example.test",),
        )

    def tearDown(self) -> None:
        self.database_patch.stop()
        self.temp_dir.cleanup()

    def test_pkce_state_is_server_side_and_return_url_is_restricted(self) -> None:
        metadata = {
            "authorization_endpoint": "https://accounts.example.test/oauth/authorize"
        }
        with (
            patch("backend.oidc_client.settings", self.fake_settings),
            patch("backend.oidc_client.discovery", return_value=metadata),
        ):
            authorization_url, state = begin_login("/projects.html?year=2026")
            self.assertEqual(
                safe_return_to("https://attacker.example/phish"),
                "https://wiki.example.test/",
            )

        query = parse_qs(urlsplit(authorization_url).query)
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["scope"], ["openid profile"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["state"], [state])
        self.assertIn("nonce", query)
        self.assertIn("code_challenge", query)
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM oidc_login_attempts")
                attempt = cursor.fetchone()
        self.assertEqual(
            attempt["state_hash"], hashlib.sha256(state.encode()).hexdigest()
        )
        self.assertNotEqual(attempt["state_hash"], state)
        self.assertEqual(
            attempt["return_to"], "https://wiki.example.test/projects.html?year=2026"
        )
        consumed = _consume_attempt(state, state)
        self.assertEqual(consumed["nonce"], query["nonce"][0])
        with self.assertRaises(OidcClientError):
            _consume_attempt(state, state)

    def test_sub_creates_one_local_member_without_later_profile_sync(self) -> None:
        with patch("backend.auth.settings", self.fake_settings):
            first = provision_oidc_user(
                auth_sub="central-sub-1",
                preferred_username="central_name",
                display_name="Central Name",
            )
            second = provision_oidc_user(
                auth_sub="central-sub-1",
                preferred_username="renamed_centrally",
                display_name="Changed Centrally",
            )
            collision = provision_oidc_user(
                auth_sub="central-sub-2",
                preferred_username="central_name",
                display_name="Other User",
            )

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["username"], "central_name")
        self.assertEqual(second["displayName"], "Central Name")
        self.assertEqual(first["role"], "user")
        self.assertEqual(collision["role"], "user")
        self.assertNotEqual(collision["username"], first["username"])
        set_admin_role("central-sub-1")
        with patch("backend.auth.settings", self.fake_settings):
            third = provision_oidc_user(
                auth_sub="central-sub-1",
                preferred_username="another_central_name",
                display_name="Another Central Name",
            )
        self.assertEqual(third["role"], "admin")
        self.assertEqual(third["username"], "central_name")

    def test_admin_is_explicitly_granted_by_central_sub(self) -> None:
        admin_settings = SimpleNamespace(**vars(self.fake_settings))
        admin_settings.wiki_admin_auth_subs = ("central-admin",)
        with patch("backend.auth.settings", admin_settings):
            admin = provision_oidc_user(
                auth_sub="central-admin",
                preferred_username="site_admin",
                display_name="Site Admin",
            )
            regular = provision_oidc_user(
                auth_sub="first-visitor",
                preferred_username="first_visitor",
                display_name="First Visitor",
            )
        self.assertEqual(admin["role"], "admin")
        self.assertEqual(regular["role"], "user")
        self.assertEqual(set_admin_role("first-visitor")["role"], "admin")

    def test_opaque_session_is_hashed_and_revocable_by_sid(self) -> None:
        with patch("backend.auth.settings", self.fake_settings):
            user = provision_oidc_user(
                auth_sub="central-sub-session",
                preferred_username="session_user",
                display_name="Session User",
            )
            token = create_session(
                user["id"], auth_sub="central-sub-session", sid="central-session-id"
            )
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT token_hash FROM auth_sessions")
                stored = cursor.fetchone()["token_hash"]
        self.assertNotEqual(stored, token)
        self.assertEqual(stored, hashlib.sha256(token.encode()).hexdigest())
        self.assertEqual(get_current_user_from_token(token)["id"], user["id"])
        self.assertEqual(revoke_sessions(sid="central-session-id"), 1)
        with self.assertRaises(HTTPException) as raised:
            get_current_user_from_token(token)
        self.assertEqual(raised.exception.status_code, 401)

    def test_rs256_tokens_nonce_and_logout_replay(self) -> None:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        public_jwk = JsonWebKey.import_key(private_pem, {"kid": "test-key"}).as_dict(
            is_private=False
        )
        now = int(time.time())
        id_token = jwt.encode(
            {"alg": "RS256", "kid": "test-key"},
            {
                "iss": self.fake_settings.oidc_issuer,
                "aud": [self.fake_settings.oidc_client_id],
                "sub": "central-sub-token",
                "sid": "central-sid-token",
                "iat": now,
                "exp": now + 300,
                "nonce": "expected-nonce",
            },
            private_pem,
        ).decode()
        logout_token = jwt.encode(
            {"alg": "RS256", "kid": "test-key"},
            {
                "iss": self.fake_settings.oidc_issuer,
                "aud": [self.fake_settings.oidc_client_id],
                "sub": "central-sub-token",
                "sid": "central-sid-token",
                "iat": now,
                "jti": "logout-event-1",
                "events": {"http://schemas.openid.net/event/backchannel-logout": {}},
            },
            private_pem,
        ).decode()
        with (
            patch("backend.oidc_client.settings", self.fake_settings),
            patch(
                "backend.oidc_client.provider_jwks", return_value={"keys": [public_jwk]}
            ),
        ):
            claims = _validate_id_token(id_token, "expected-nonce")
            self.assertEqual(claims["sub"], "central-sub-token")
            with self.assertRaises(OidcClientError):
                _validate_id_token(id_token, "wrong-nonce")
            first = validate_logout_token(logout_token)
            repeated = validate_logout_token(logout_token)
        self.assertFalse(first["_replayed"])
        self.assertTrue(repeated["_replayed"])

    def test_code_exchange_uses_confidential_client_and_pkce_verifier(self) -> None:
        now = int(time.time())
        state = "callback-state"
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO oidc_login_attempts
                      (state_hash, code_verifier, nonce, return_to, created_at, expires_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        hashlib.sha256(state.encode()).hexdigest(),
                        "stored-pkce-verifier",
                        "stored-nonce",
                        "https://wiki.example.test/",
                        now,
                        now + 600,
                    ),
                )

        captured: dict = {}

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "sub": "central-code-user",
                    "preferred_username": "code_user",
                    "name": "Code User",
                }

        class FakeOAuth2Session:
            def __init__(self, **kwargs):
                captured["client"] = kwargs

            def fetch_token(self, endpoint, **kwargs):
                captured["token_endpoint"] = endpoint
                captured["exchange"] = kwargs
                return {"id_token": "signed-id-token", "access_token": "access"}

            def get(self, endpoint, **kwargs):
                captured["userinfo_endpoint"] = endpoint
                captured["userinfo"] = kwargs
                return FakeResponse()

        metadata = {
            "token_endpoint": "https://accounts.example.test/oauth/token",
            "userinfo_endpoint": "https://accounts.example.test/oauth/userinfo",
        }
        claims = {
            "sub": "central-code-user",
            "sid": "central-code-sid",
            "preferred_username": "fallback",
            "name": "Fallback",
        }
        with (
            patch("backend.oidc_client.settings", self.fake_settings),
            patch("backend.oidc_client.discovery", return_value=metadata),
            patch("backend.oidc_client.OAuth2Session", FakeOAuth2Session),
            patch("backend.oidc_client._validate_id_token", return_value=claims),
        ):
            identity = complete_login("authorization-code", state, state)

        self.assertEqual(captured["client"]["token_endpoint_auth_method"], "client_secret_basic")
        self.assertEqual(captured["exchange"]["code"], "authorization-code")
        self.assertEqual(captured["exchange"]["code_verifier"], "stored-pkce-verifier")
        self.assertEqual(captured["exchange"]["timeout"], 5)
        self.assertEqual(identity["sub"], "central-code-user")
        self.assertEqual(identity["sid"], "central-code-sid")
        self.assertEqual(identity["preferred_username"], "code_user")

    def test_callback_sets_http_only_cookie_and_logout_is_local(self) -> None:
        identity = {
            "sub": "central-callback-user",
            "sid": "central-callback-sid",
            "preferred_username": "callback_user",
            "name": "Callback User",
            "return_to": "https://wiki.example.test/projects.html",
        }
        with (
            patch("backend.main.settings", self.fake_settings),
            patch("backend.auth.settings", self.fake_settings),
            patch("backend.main.complete_login", return_value=identity),
            patch("backend.main.validate_runtime_settings"),
        ):
            with TestClient(app, base_url="https://wiki.example.test") as client:
                client.cookies.set(OIDC_STATE_COOKIE, "state-cookie", path="/api/auth")
                response = client.get(
                    "/api/auth/callback?code=code-1&state=state-1",
                    follow_redirects=False,
                )
                self.assertEqual(response.status_code, 303, response.text)
                cookie = response.headers["set-cookie"]
                self.assertIn(f"{SESSION_COOKIE_NAME}=", cookie)
                self.assertIn("HttpOnly", cookie)
                self.assertIn("Secure", cookie)
                self.assertIn("SameSite=lax", cookie)
                self.assertEqual(client.get("/api/auth/me").status_code, 200)
                denied = client.post("/api/auth/logout")
                self.assertEqual(denied.status_code, 403)
                logged_out = client.post(
                    "/api/auth/logout",
                    headers={"Origin": "https://wiki.example.test"},
                )
                self.assertEqual(logged_out.status_code, 204)
                self.assertEqual(client.get("/api/auth/me").status_code, 401)

    def test_local_password_endpoints_are_closed_with_oidc(self) -> None:
        with (
            patch("backend.main.settings", self.fake_settings),
            patch("backend.main.validate_runtime_settings"),
        ):
            with TestClient(app, base_url="https://wiki.example.test") as client:
                register = client.post(
                    "/api/auth/register",
                    json={"username": "local_user", "password": "password123"},
                )
                login = client.post(
                    "/api/auth/login",
                    json={"username": "local_user", "password": "password123"},
                )
        self.assertEqual(register.status_code, 410)
        self.assertEqual(login.status_code, 410)

    def test_backchannel_endpoint_revokes_matching_local_session(self) -> None:
        with patch("backend.auth.settings", self.fake_settings):
            user = provision_oidc_user(
                auth_sub="central-backchannel-user",
                preferred_username="backchannel_user",
                display_name="Backchannel User",
            )
            token = create_session(
                user["id"],
                auth_sub="central-backchannel-user",
                sid="central-backchannel-sid",
            )
        claims = {
            "sub": "central-backchannel-user",
            "sid": "central-backchannel-sid",
        }
        with (
            patch("backend.main.settings", self.fake_settings),
            patch("backend.main.validate_runtime_settings"),
            patch("backend.main.validate_logout_token", return_value=claims),
        ):
            with TestClient(app, base_url="https://wiki.example.test") as client:
                response = client.post(
                    "/api/auth/backchannel-logout",
                    data={"logout_token": "signed-token"},
                )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["revoked"], 1)
        with self.assertRaises(HTTPException):
            get_current_user_from_token(token)


if __name__ == "__main__":
    unittest.main()
