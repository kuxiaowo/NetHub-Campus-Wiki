"""用户认证和用户数据访问。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
from typing import Any, Literal

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pymysql.err import IntegrityError

from backend.config import settings
from backend.database import get_db_connection

UserRole = Literal["admin", "user"]

PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 260_000
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,32}$")
bearer_scheme = HTTPBearer(auto_error=False)


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def hash_password(password: str) -> str:
    """使用 PBKDF2-HMAC-SHA256 生成带盐密码哈希。"""

    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return "$".join(
        [
            PASSWORD_ALGORITHM,
            str(PASSWORD_ITERATIONS),
            _base64url_encode(salt),
            _base64url_encode(digest),
        ]
    )


def verify_password(password: str, password_hash: str) -> bool:
    """校验明文密码是否匹配存储的 PBKDF2 哈希。"""

    try:
        algorithm, iterations, salt_value, digest_value = password_hash.split("$", 3)
        if algorithm != PASSWORD_ALGORITHM:
            return False
        salt = _base64url_decode(salt_value)
        expected = _base64url_decode(digest_value)
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(iterations),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def format_user(row: dict[str, Any]) -> dict[str, Any]:
    """把 users 表行转换为 API 约定的 User JSON。"""

    return {
        "id": row["id"],
        "username": row["username"],
        "displayName": row.get("display_name"),
        "role": row["role"],
        "isActive": bool(row.get("is_active")),
        "createdAt": row.get("created_at"),
    }


def validate_username(username: str) -> str:
    normalized = username.strip()
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise HTTPException(status_code=422, detail="用户名只能包含字母、数字和下划线，长度为 3-32 位")
    return normalized


def validate_password(password: str) -> None:
    if len(password) < 8:
        raise HTTPException(status_code=422, detail="密码长度至少为 8 位")


def create_user(username: str, password: str, display_name: str | None = None) -> dict[str, Any]:
    """注册普通用户；重复用户名返回 409。"""

    username = validate_username(username)
    validate_password(password)
    clean_display_name = display_name.strip() if display_name else None

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (username, password_hash, display_name, role)
                    VALUES (%s, %s, %s, 'user')
                    """,
                    (username, hash_password(password), clean_display_name),
                )
                user_id = cursor.lastrowid
                cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
                row = cursor.fetchone()
    except IntegrityError as exc:
        if exc.args and exc.args[0] == 1062:
            raise HTTPException(status_code=409, detail="用户名已存在") from exc
        raise

    return format_user(row)


def authenticate_user(username: str, password: str) -> dict[str, Any]:
    """校验用户名密码并返回用户。"""

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE username = %s LIMIT 1", (username.strip(),))
            row = cursor.fetchone()

    if row is None or not verify_password(password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not row.get("is_active"):
        raise HTTPException(status_code=403, detail="账号已被禁用")
    return format_user(row)


def create_access_token(user: dict[str, Any]) -> str:
    """创建 HMAC-SHA256 签名的 Bearer Token。"""

    now = int(time.time())
    payload = {
        "sub": str(user["id"]),
        "role": user["role"],
        "exp": now + settings.auth_token_expire_minutes * 60,
    }
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = ".".join(
        [
            _base64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8")),
            _base64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
        ]
    )
    signature = hmac.new(
        settings.auth_secret_key.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{_base64url_encode(signature)}"


def decode_access_token(token: str) -> dict[str, Any]:
    """验证 token 签名和过期时间。"""

    try:
        header_value, payload_value, signature_value = token.split(".", 2)
        signing_input = f"{header_value}.{payload_value}"
        expected = hmac.new(
            settings.auth_secret_key.encode("utf-8"),
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()
        actual = _base64url_decode(signature_value)
        if not hmac.compare_digest(actual, expected):
            raise ValueError("invalid signature")
        payload = json.loads(_base64url_decode(payload_value))
        if int(payload.get("exp", 0)) < int(time.time()):
            raise ValueError("expired token")
        return payload
    except (ValueError, json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=401, detail="登录状态无效或已过期") from None


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE id = %s LIMIT 1", (user_id,))
            row = cursor.fetchone()
    return None if row is None else format_user(row)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="需要登录")

    payload = decode_access_token(credentials.credentials)
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="登录状态无效或已过期") from None

    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    if not user["isActive"]:
        raise HTTPException(status_code=403, detail="账号已被禁用")
    return user
