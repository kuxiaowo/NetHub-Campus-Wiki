"""Password length policy unit tests independent from database setup."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from backend.auth import validate_password, verify_password
from backend.auth_policy import PASSWORD_MAX_LENGTH
from backend.schemas import ChangePasswordRequest, LoginRequest, RegisterRequest


class PasswordPolicyTest(unittest.TestCase):
    def test_128_characters_are_accepted(self) -> None:
        password = "a" * PASSWORD_MAX_LENGTH

        RegisterRequest(username="password_user", password=password)
        LoginRequest(username="password_user", password=password)
        ChangePasswordRequest(currentPassword=password, newPassword=password)
        validate_password(password)

    def test_129_characters_are_rejected_before_hashing(self) -> None:
        password = "a" * (PASSWORD_MAX_LENGTH + 1)

        with self.assertRaises(ValidationError):
            RegisterRequest(username="password_user", password=password)
        with self.assertRaises(ValidationError):
            LoginRequest(username="password_user", password=password)
        with self.assertRaises(ValidationError):
            ChangePasswordRequest(currentPassword=password, newPassword="valid-password")
        with self.assertRaises(ValidationError):
            ChangePasswordRequest(currentPassword="valid-password", newPassword=password)
        with self.assertRaises(HTTPException) as context:
            validate_password(password)
        self.assertEqual(context.exception.status_code, 422)

        with patch("backend.auth.hashlib.pbkdf2_hmac") as derive:
            self.assertFalse(verify_password(password, "invalid-hash"))
            derive.assert_not_called()


if __name__ == "__main__":
    unittest.main()
