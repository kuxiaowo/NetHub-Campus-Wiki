"""Authentication rate-limit and live admin-setting integration tests."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.bootstrap_admin import create_initial_admin
from backend.auth import create_user
from backend.main import app


class AuthRateLimitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "rate-limit.db"
        self.database_patcher = patch(
            "backend.database.get_database_path",
            return_value=self.database_path,
        )
        self.database_patcher.start()
        create_initial_admin("rate_admin", "admin-password-123", "Rate Admin")
        create_user("rate_user", "user-password-123", "Rate User")
        self.client = TestClient(app)
        response = self.client.post(
            "/api/auth/login",
            json={"username": "rate_admin", "password": "admin-password-123"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.admin_token = response.json()["accessToken"]
        self.admin_headers = {"Authorization": f"Bearer {self.admin_token}"}
        defaults_response = self.client.get(
            "/api/admin/auth-security-settings",
            headers=self.admin_headers,
        )
        self.assertEqual(defaults_response.status_code, 200, defaults_response.text)
        self.default_settings = defaults_response.json()
        response = self.client.patch(
            "/api/admin/auth-security-settings",
            headers=self.admin_headers,
            json={
                "loginIpLimit": 100,
                "adminLoginIpLimit": 100,
                "loginFailureLimit": 100,
                "registerHourlyLimit": 100,
                "registerDailyLimit": 100,
                "passwordChangeHourlyLimit": 100,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)

    def tearDown(self) -> None:
        self.client.close()
        self.database_patcher.stop()
        self.temp_dir.cleanup()

    def update_settings(self, **values: int) -> dict:
        response = self.client.patch(
            "/api/admin/auth-security-settings",
            headers=self.admin_headers,
            json=values,
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_admin_settings_require_admin_and_validate_values(self) -> None:
        response = self.client.get("/api/admin/auth-security-settings")
        self.assertEqual(response.status_code, 401)

        response = self.client.get(
            "/api/admin/auth-security-settings",
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["registerHourlyLimit"], 100)
        self.assertEqual(self.default_settings["loginIpLimit"], 10)
        self.assertEqual(self.default_settings["adminLoginIpLimit"], 5)
        self.assertEqual(self.default_settings["loginFailureLimit"], 5)
        self.assertEqual(self.default_settings["loginFailureCooldownMinutes"], 10)
        self.assertEqual(self.default_settings["registerHourlyLimit"], 3)
        self.assertEqual(self.default_settings["registerDailyLimit"], 10)
        self.assertEqual(self.default_settings["passwordChangeHourlyLimit"], 5)

        response = self.client.patch(
            "/api/admin/auth-security-settings",
            headers=self.admin_headers,
            json={"loginIpLimit": 0},
        )
        self.assertEqual(response.status_code, 422)

    def test_registration_limit_update_is_immediate(self) -> None:
        self.update_settings(registerHourlyLimit=1, registerDailyLimit=10)
        first = self.client.post(
            "/api/auth/register",
            json={"username": "first_limited", "password": "password123"},
        )
        limited = self.client.post(
            "/api/auth/register",
            json={"username": "second_limited", "password": "password123"},
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(limited.status_code, 429, limited.text)
        self.assertGreaterEqual(int(limited.headers["Retry-After"]), 1)

        self.update_settings(registerHourlyLimit=2)
        allowed = self.client.post(
            "/api/auth/register",
            json={"username": "second_limited", "password": "password123"},
        )
        self.assertEqual(allowed.status_code, 200, allowed.text)

        self.update_settings(registerHourlyLimit=3, registerDailyLimit=2)
        daily_limited = self.client.post(
            "/api/auth/register",
            json={"username": "third_limited", "password": "password123"},
        )
        self.assertEqual(daily_limited.status_code, 429, daily_limited.text)

    def test_login_ip_and_admin_ip_limits_apply_immediately(self) -> None:
        self.update_settings(loginIpLimit=1)
        normal_limited = self.client.post(
            "/api/auth/login",
            json={"username": "rate_user", "password": "user-password-123"},
        )
        self.assertEqual(normal_limited.status_code, 429, normal_limited.text)

        self.update_settings(loginIpLimit=100, adminLoginIpLimit=1)
        admin_limited = self.client.post(
            "/api/auth/login",
            json={"username": "rate_admin", "password": "admin-password-123"},
        )
        self.assertEqual(admin_limited.status_code, 429, admin_limited.text)

    def test_username_failure_limit_and_successful_reset(self) -> None:
        self.update_settings(loginFailureLimit=2, loginFailureCooldownMinutes=10)
        first = self.client.post(
            "/api/auth/login",
            json={"username": "rate_user", "password": "wrong-password"},
        )
        second = self.client.post(
            "/api/auth/login",
            json={"username": "rate_user", "password": "wrong-password"},
        )
        blocked = self.client.post(
            "/api/auth/login",
            json={"username": "rate_user", "password": "user-password-123"},
        )
        self.assertEqual(first.status_code, 401, first.text)
        self.assertEqual(second.status_code, 429, second.text)
        self.assertEqual(blocked.status_code, 429, blocked.text)

        self.update_settings(loginFailureLimit=3)
        allowed = self.client.post(
            "/api/auth/login",
            json={"username": "rate_user", "password": "user-password-123"},
        )
        self.assertEqual(allowed.status_code, 200, allowed.text)

        after_reset = self.client.post(
            "/api/auth/login",
            json={"username": "rate_user", "password": "wrong-password"},
        )
        self.assertEqual(after_reset.status_code, 401, after_reset.text)

    def test_password_change_is_limited_by_user_and_ip(self) -> None:
        login = self.client.post(
            "/api/auth/login",
            json={"username": "rate_user", "password": "user-password-123"},
        )
        token = login.json()["accessToken"]
        headers = {"Authorization": f"Bearer {token}"}
        self.update_settings(passwordChangeHourlyLimit=1)

        wrong = self.client.patch(
            "/api/auth/password",
            headers=headers,
            json={
                "currentPassword": "wrong-password",
                "newPassword": "replacement-password-123",
            },
        )
        limited = self.client.patch(
            "/api/auth/password",
            headers=headers,
            json={
                "currentPassword": "user-password-123",
                "newPassword": "replacement-password-123",
            },
        )
        self.assertEqual(wrong.status_code, 400, wrong.text)
        self.assertEqual(limited.status_code, 429, limited.text)


if __name__ == "__main__":
    unittest.main()
