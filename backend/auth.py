"""用户认证和用户数据访问。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
from sqlite3 import IntegrityError
import time
from typing import Any, Literal

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from backend.auth_policy import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH
from backend.config import settings
from backend.database import get_db_connection
from backend.media import public_media_url

UserRole = Literal["admin", "user"]
DELETED_USER_DISPLAY_NAME = "已注销用户"

PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 260_000
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,32}$")
bearer_scheme = HTTPBearer(auto_error=False)
SESSION_COOKIE_NAME = "campus_wiki_session"


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def hash_password(password: str) -> str:
    """使用 PBKDF2-HMAC-SHA256 生成带盐密码哈希。"""

    validate_password(password)
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

    # Avoid spending CPU and memory on oversized credentials even when this
    # function is called outside the validated HTTP request models.
    if len(password) > PASSWORD_MAX_LENGTH:
        return False

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
        "avatarUrl": central_avatar_url(row.get("auth_sub")) or public_media_url(row.get("avatar_url")),
        "accountUrl": f"{settings.oidc_issuer}/account",
        "bio": row.get("bio") or "",
        "role": row["role"],
        "isActive": bool(row.get("is_active")),
        "campusVerified": bool(row.get("campus_verified")),
        "messagingPermission": row.get("messaging_permission") or "everyone",
        "linkedPersonId": row.get("person_id"),
        "createdAt": row.get("created_at"),
    }


def public_user_identity(
    row: dict[str, Any],
    *,
    id_key: str,
    username_key: str,
    display_name_key: str,
    avatar_url_key: str,
    deleted_at_key: str,
    auth_sub_key: str | None = None,
    campus_verified_key: str | None = None,
) -> dict[str, Any]:
    """格式化可嵌入留言、私信等响应的公开用户身份。"""

    deleted = bool(row.get(deleted_at_key))
    result = {
        "id": row.get(id_key),
        "username": None if deleted else row.get(username_key),
        "displayName": DELETED_USER_DISPLAY_NAME if deleted else row.get(display_name_key),
        "avatarUrl": (
            None
            if deleted
            else central_avatar_url(row.get(auth_sub_key))
            or public_media_url(row.get(avatar_url_key))
        ),
        "deleted": deleted,
    }
    if campus_verified_key is not None:
        result["campusVerified"] = False if deleted else bool(row.get(campus_verified_key))
    return result


def central_avatar_url(auth_sub: Any) -> str | None:
    subject = str(auth_sub or "").strip()
    return f"{settings.oidc_issuer}/avatars/{subject}" if subject else None


def validate_username(username: str) -> str:
    normalized = username.strip()
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise HTTPException(status_code=422, detail="昵称只能包含字母、数字和下划线，长度为 3-32 位")
    return normalized


def validate_password(password: str) -> None:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise HTTPException(status_code=422, detail=f"密码长度至少为 {PASSWORD_MIN_LENGTH} 个字符")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise HTTPException(status_code=422, detail=f"密码长度不能超过 {PASSWORD_MAX_LENGTH} 个字符")


def create_user(username: str, password: str, display_name: str | None = None) -> dict[str, Any]:
    """注册普通用户；重复昵称返回 409。"""

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
        raise HTTPException(status_code=409, detail="昵称已存在") from exc

    return format_user(row)


def update_username(user_id: int, username: str) -> dict[str, Any]:
    """Update the current user's nickname/login username."""

    username = validate_username(username)

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM users WHERE id = %s LIMIT 1", (user_id,))
                current_row = cursor.fetchone()
                if current_row is None:
                    raise HTTPException(status_code=404, detail="用户不存在")
                if current_row["username"] == username:
                    return format_user(current_row)
                cursor.execute(
                    "UPDATE users SET username = %s WHERE id = %s",
                    (username, user_id),
                )
                cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
                row = cursor.fetchone()
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="昵称已存在") from exc

    return format_user(row)


def authenticate_user(username: str, password: str) -> dict[str, Any]:
    """校验昵称密码并返回用户。"""

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE username = %s LIMIT 1", (username.strip(),))
            row = cursor.fetchone()

    if row is None or not verify_password(password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="昵称或密码错误")
    if not row.get("is_active"):
        raise HTTPException(status_code=403, detail="账号已被禁用")
    return format_user(row)


def change_user_password(user_id: int, current_password: str, new_password: str) -> dict[str, Any]:
    """使用原密码校验后更新当前用户密码。"""

    validate_password(new_password)

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE id = %s LIMIT 1", (user_id,))
            row = cursor.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="用户不存在")
            if not verify_password(current_password, row["password_hash"]):
                raise HTTPException(status_code=400, detail="原密码错误")
            if not row.get("is_active"):
                raise HTTPException(status_code=403, detail="账号已被禁用")

            cursor.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s",
                (hash_password(new_password), user_id),
            )
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            updated_row = cursor.fetchone()

    return format_user(updated_row)


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(
    user_id: int,
    *,
    auth_sub: str | None = None,
    sid: str | None = None,
) -> str:
    """Create a database-backed opaque session and return its raw token."""

    now = int(time.time())
    token = secrets.token_urlsafe(48)
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO auth_sessions
                  (token_hash, user_id, auth_sub, sid, created_at, last_seen_at,
                   idle_expires_at, absolute_expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    _token_digest(token),
                    user_id,
                    auth_sub,
                    sid,
                    now,
                    now,
                    now + settings.auth_session_idle_seconds,
                    now + settings.auth_session_absolute_seconds,
                ),
            )
    return token


def create_access_token(user: dict[str, Any]) -> str:
    """Compatibility helper for tests; the token is an opaque DB session."""

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT auth_sub FROM users WHERE id = %s", (user["id"],))
            row = cursor.fetchone()
    return create_session(
        int(user["id"]),
        auth_sub=row.get("auth_sub") if row else None,
    )


def _session_record(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    now = int(time.time())
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT s.id AS auth_session_id, s.auth_sub AS session_auth_sub,
                       s.sid AS auth_sid, s.idle_expires_at, s.absolute_expires_at,
                       s.revoked_at, u.*,
                       (SELECT MIN(p.id) FROM people p WHERE p.user_id = u.id) AS person_id
                FROM auth_sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = %s
                LIMIT 1
                """,
                (_token_digest(token),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            if (
                row.get("revoked_at") is not None
                or int(row["idle_expires_at"]) <= now
                or int(row["absolute_expires_at"]) <= now
            ):
                cursor.execute(
                    "DELETE FROM auth_sessions WHERE id = %s", (row["auth_session_id"],)
                )
                return None
            next_idle = min(
                now + settings.auth_session_idle_seconds,
                int(row["absolute_expires_at"]),
            )
            cursor.execute(
                "UPDATE auth_sessions SET last_seen_at = %s, idle_expires_at = %s WHERE id = %s",
                (now, next_idle, row["auth_session_id"]),
            )
    return row


def decode_access_token(token: str) -> dict[str, Any]:
    """Resolve an opaque session token; former self-signed JWTs are rejected."""

    row = _session_record(token)
    if row is None:
        raise HTTPException(status_code=401, detail="登录状态无效或已过期")
    return {"sub": str(row["id"]), "sid": row.get("auth_sid")}


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT u.*,
                       (SELECT MIN(p.id) FROM people p WHERE p.user_id = u.id) AS person_id
                FROM users u
                WHERE u.id = %s
                LIMIT 1
                """,
                (user_id,),
            )
            row = cursor.fetchone()
    return None if row is None else format_user(row)


def get_current_user_from_token(token: str) -> dict[str, Any]:
    row = _session_record(token)
    if row is None:
        raise HTTPException(status_code=401, detail="登录状态无效或已过期")
    user = format_user(row)
    if not user["isActive"]:
        raise HTTPException(status_code=403, detail="账号已被禁用")
    return user


def revoke_session(token: str) -> None:
    if not token:
        return
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE auth_sessions SET revoked_at = %s WHERE token_hash = %s AND revoked_at IS NULL",
                (int(time.time()), _token_digest(token)),
            )


def revoke_sessions(
    *,
    user_id: int | None = None,
    auth_sub: str | None = None,
    sid: str | None = None,
) -> int:
    filters = ["revoked_at IS NULL"]
    params: list[Any] = [int(time.time())]
    if user_id is not None:
        filters.append("user_id = %s")
        params.append(user_id)
    if auth_sub is not None:
        filters.append("auth_sub = %s")
        params.append(auth_sub)
    if sid is not None:
        filters.append("sid = %s")
        params.append(sid)
    if len(filters) == 1:
        return 0
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"UPDATE auth_sessions SET revoked_at = %s WHERE {' AND '.join(filters)}",
                params,
            )
            return cursor.rowcount


def provision_oidc_user(
    *,
    auth_sub: str,
    preferred_username: str,
    display_name: str,
) -> dict[str, Any]:
    """Return an existing local member or create one on first OIDC login."""

    auth_sub = auth_sub.strip()
    if not auth_sub or len(auth_sub) > 128:
        raise HTTPException(status_code=502, detail="账号中心返回了无效的用户标识")
    username = preferred_username.strip()[:64] or f"user-{auth_sub[:8]}"
    name = display_name.strip()[:80] or username
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM users WHERE auth_sub = %s LIMIT 1", (auth_sub,))
                row = cursor.fetchone()
                if row is None:
                    candidate = username
                    cursor.execute(
                        "SELECT id FROM users WHERE username = %s COLLATE NOCASE LIMIT 1",
                        (candidate,),
                    )
                    if cursor.fetchone() is not None:
                        suffix = hashlib.sha256(auth_sub.encode("utf-8")).hexdigest()[:12]
                        candidate = f"{username[:51]}-{suffix}"
                    role = "admin" if auth_sub in settings.wiki_admin_auth_subs else "user"
                    cursor.execute(
                        """
                        INSERT INTO users
                          (username, password_hash, display_name, role, is_active, auth_sub)
                        VALUES (%s, '', %s, %s, 1, %s)
                        """,
                        (candidate, name, role, auth_sub),
                    )
                    user_id = cursor.lastrowid
                    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
                    row = cursor.fetchone()
    except IntegrityError as exc:
        # Concurrent callbacks for the same central identity may both observe no
        # member before one insert wins. Resolve that race by reading the winner.
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM users WHERE auth_sub = %s LIMIT 1", (auth_sub,))
                row = cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=409, detail="本地成员创建冲突，请联系管理员") from exc
    if not row.get("is_active"):
        raise HTTPException(status_code=403, detail="本网站成员资格已被停用")
    return format_user(row)


def _request_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> str:
    cookie = request.cookies.get(SESSION_COOKIE_NAME, "")
    if cookie:
        return cookie
    # The compatibility Bearer path exists only for old isolated tests and
    # local development without an OIDC client. Production uses HttpOnly cookies.
    if (
        not settings.oidc_client_secret
        and credentials is not None
        and credentials.scheme.lower() == "bearer"
    ):
        return credentials.credentials
    return ""


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any]:
    token = _request_token(request, credentials)
    if not token:
        raise HTTPException(status_code=401, detail="需要登录")
    row = _session_record(token)
    if row is None:
        raise HTTPException(status_code=401, detail="登录状态无效或已过期")
    user = format_user(row)
    if not user["isActive"]:
        raise HTTPException(status_code=403, detail="账号已被禁用")
    return user


def get_optional_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any] | None:
    """Return the current user when a valid opaque session is present."""

    token = _request_token(request, credentials)
    if not token:
        return None
    row = _session_record(token)
    if row is None or not row.get("is_active"):
        return None
    return format_user(row)
