"""Persistent, runtime-configurable rate limits for authentication endpoints."""

from __future__ import annotations

import hashlib
import ipaddress
import math
import time
from typing import Any

from fastapi import HTTPException, Request

from backend.database import get_db_connection

MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR
# Keep buckets long enough for the largest configurable failure cooldown.
BUCKET_RETENTION_SECONDS = 31 * DAY

SETTING_FIELDS = {
    "loginIpLimit": ("login_ip_limit", 1, 100_000),
    "adminLoginIpLimit": ("admin_login_ip_limit", 1, 100_000),
    "loginFailureLimit": ("login_failure_limit", 1, 100_000),
    "loginFailureCooldownMinutes": (
        "login_failure_cooldown_minutes",
        1,
        43_200,
    ),
    "registerHourlyLimit": ("register_hourly_limit", 1, 100_000),
    "registerDailyLimit": ("register_daily_limit", 1, 1_000_000),
    "passwordChangeHourlyLimit": (
        "password_change_hourly_limit",
        1,
        100_000,
    ),
}


def _format_settings(row: dict[str, Any]) -> dict[str, Any]:
    result = {
        api_name: int(row[column])
        for api_name, (column, _, _) in SETTING_FIELDS.items()
    }
    result["updatedAt"] = row.get("updated_at")
    result["updatedBy"] = row.get("updated_by")
    return result


def get_auth_security_settings() -> dict[str, Any]:
    """Read settings for every request so admin updates take effect immediately."""

    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM auth_security_settings WHERE id = 1")
            row = cursor.fetchone()
    if row is None:
        raise RuntimeError("认证限流配置不存在，请检查数据库迁移")
    return _format_settings(row)


def update_auth_security_settings(
    payload: dict[str, Any],
    *,
    admin_user_id: int,
) -> dict[str, Any]:
    unknown = sorted(set(payload) - set(SETTING_FIELDS))
    if unknown:
        raise HTTPException(status_code=422, detail=f"不支持的配置项：{', '.join(unknown)}")
    if not payload:
        raise HTTPException(status_code=422, detail="请求体不能为空")

    updates: list[str] = []
    parameters: list[Any] = []
    for api_name, raw_value in payload.items():
        column, minimum, maximum = SETTING_FIELDS[api_name]
        if not isinstance(raw_value, int) or isinstance(raw_value, bool):
            raise HTTPException(status_code=422, detail=f"{api_name} 必须是整数")
        value = raw_value
        if not minimum <= value <= maximum:
            raise HTTPException(
                status_code=422,
                detail=f"{api_name} 必须是 {minimum}-{maximum} 之间的整数",
            )
        updates.append(f"{column} = %s")
        parameters.append(value)

    updates.extend(["updated_by = %s", "updated_at = CURRENT_TIMESTAMP"])
    parameters.extend([admin_user_id, 1])
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE auth_security_settings SET {', '.join(updates)} WHERE id = %s",
                parameters,
            )
            cursor.execute("SELECT * FROM auth_security_settings WHERE id = 1")
            row = cursor.fetchone()
    return _format_settings(row)


def _client_ip(request: Request) -> str:
    """Use ASGI's client address; trusted proxy handling belongs in Uvicorn."""

    raw_value = request.client.host if request.client else "unknown"
    try:
        return ipaddress.ip_address(raw_value).compressed
    except ValueError:
        return raw_value.strip().casefold() or "unknown"


def _bucket_key(scope: str, identity: str) -> str:
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"{scope}:{digest}"


def _too_many_requests(detail: str, retry_after: int) -> HTTPException:
    retry_after = max(1, int(math.ceil(retry_after)))
    return HTTPException(
        status_code=429,
        detail=detail,
        headers={"Retry-After": str(retry_after)},
    )


def _consume_fixed_window(
    scope: str,
    identity: str,
    *,
    limit: int,
    window_seconds: int,
    detail: str,
) -> None:
    now = int(time.time())
    key = _bucket_key(scope, identity)
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                "DELETE FROM auth_rate_limit_buckets WHERE updated_at < %s",
                (now - BUCKET_RETENTION_SECONDS,),
            )
            cursor.execute(
                "SELECT * FROM auth_rate_limit_buckets WHERE bucket_key = %s",
                (key,),
            )
            row = cursor.fetchone()
            if row is None or now - int(row["window_started_at"]) >= window_seconds:
                cursor.execute(
                    """
                    INSERT INTO auth_rate_limit_buckets
                      (bucket_key, window_started_at, attempt_count, updated_at)
                    VALUES (%s, %s, 1, %s)
                    ON CONFLICT(bucket_key) DO UPDATE SET
                      window_started_at = excluded.window_started_at,
                      attempt_count = 1,
                      updated_at = excluded.updated_at
                    """,
                    (key, now, now),
                )
                return

            elapsed = now - int(row["window_started_at"])
            if int(row["attempt_count"]) >= limit:
                raise _too_many_requests(detail, window_seconds - elapsed)
            cursor.execute(
                """
                UPDATE auth_rate_limit_buckets
                SET attempt_count = attempt_count + 1, updated_at = %s
                WHERE bucket_key = %s
                """,
                (now, key),
            )


def _is_admin_username(username: str) -> bool:
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT role FROM users
                WHERE username = %s AND deleted_at IS NULL
                LIMIT 1
                """,
                (username.strip(),),
            )
            row = cursor.fetchone()
    return bool(row and row["role"] == "admin")


def enforce_login_request(request: Request, username: str) -> dict[str, Any]:
    config = get_auth_security_settings()
    client_ip = _client_ip(request)
    _consume_fixed_window(
        "login-ip",
        client_ip,
        limit=config["loginIpLimit"],
        window_seconds=MINUTE,
        detail="登录请求过于频繁，请稍后再试",
    )
    if _is_admin_username(username):
        _consume_fixed_window(
            "admin-login-ip",
            client_ip,
            limit=config["adminLoginIpLimit"],
            window_seconds=MINUTE,
            detail="登录请求过于频繁，请稍后再试",
        )
    enforce_username_not_blocked(username, config)
    return config


def enforce_username_not_blocked(username: str, config: dict[str, Any]) -> None:
    now = int(time.time())
    cooldown = config["loginFailureCooldownMinutes"] * MINUTE
    key = _bucket_key("login-failure", username.strip().casefold())
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM auth_rate_limit_buckets WHERE bucket_key = %s",
                (key,),
            )
            row = cursor.fetchone()
            if row is None:
                return
            elapsed = now - int(row["updated_at"])
            if elapsed >= cooldown:
                cursor.execute(
                    "DELETE FROM auth_rate_limit_buckets WHERE bucket_key = %s",
                    (key,),
                )
                return
            if int(row["attempt_count"]) >= config["loginFailureLimit"]:
                raise _too_many_requests("登录失败次数过多，请稍后再试", cooldown - elapsed)


def record_login_failure(username: str, config: dict[str, Any]) -> None:
    now = int(time.time())
    cooldown = config["loginFailureCooldownMinutes"] * MINUTE
    key = _bucket_key("login-failure", username.strip().casefold())
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                "SELECT * FROM auth_rate_limit_buckets WHERE bucket_key = %s",
                (key,),
            )
            row = cursor.fetchone()
            if row is None or now - int(row["updated_at"]) >= cooldown:
                attempts = 1
                cursor.execute(
                    """
                    INSERT INTO auth_rate_limit_buckets
                      (bucket_key, window_started_at, attempt_count, updated_at)
                    VALUES (%s, %s, 1, %s)
                    ON CONFLICT(bucket_key) DO UPDATE SET
                      window_started_at = excluded.window_started_at,
                      attempt_count = 1,
                      updated_at = excluded.updated_at
                    """,
                    (key, now, now),
                )
            else:
                attempts = int(row["attempt_count"]) + 1
                cursor.execute(
                    """
                    UPDATE auth_rate_limit_buckets
                    SET attempt_count = %s, updated_at = %s
                    WHERE bucket_key = %s
                    """,
                    (attempts, now, key),
                )
    if attempts >= config["loginFailureLimit"]:
        raise _too_many_requests("登录失败次数过多，请稍后再试", cooldown)


def clear_login_failures(username: str) -> None:
    key = _bucket_key("login-failure", username.strip().casefold())
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM auth_rate_limit_buckets WHERE bucket_key = %s",
                (key,),
            )


def enforce_register_request(request: Request) -> None:
    config = get_auth_security_settings()
    client_ip = _client_ip(request)
    _consume_fixed_window(
        "register-hour-ip",
        client_ip,
        limit=config["registerHourlyLimit"],
        window_seconds=HOUR,
        detail="注册请求过于频繁，请稍后再试",
    )
    _consume_fixed_window(
        "register-day-ip",
        client_ip,
        limit=config["registerDailyLimit"],
        window_seconds=DAY,
        detail="今日注册请求次数过多，请稍后再试",
    )


def enforce_password_change_request(request: Request, user_id: int) -> None:
    config = get_auth_security_settings()
    limit = config["passwordChangeHourlyLimit"]
    _consume_fixed_window(
        "password-user",
        str(user_id),
        limit=limit,
        window_seconds=HOUR,
        detail="修改密码请求过于频繁，请稍后再试",
    )
    _consume_fixed_window(
        "password-ip",
        _client_ip(request),
        limit=limit,
        window_seconds=HOUR,
        detail="修改密码请求过于频繁，请稍后再试",
    )
