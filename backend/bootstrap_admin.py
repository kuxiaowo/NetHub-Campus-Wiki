"""交互式创建首个管理员账号。"""

from __future__ import annotations

import argparse
from getpass import getpass
from sqlite3 import IntegrityError
from typing import Any

from backend.auth import USERNAME_PATTERN, hash_password
from backend.auth_policy import PASSWORD_MAX_LENGTH
from backend.database import get_db_connection

ADMIN_PASSWORD_MIN_LENGTH = 12


class AdminBootstrapError(RuntimeError):
    """管理员引导因安全约束或数据冲突失败。"""


def create_initial_admin(
    username: str,
    password: str,
    display_name: str | None = None,
) -> dict[str, Any]:
    """仅在没有启用中管理员时创建一个管理员。"""

    normalized_username = username.strip()
    if not USERNAME_PATTERN.fullmatch(normalized_username):
        raise AdminBootstrapError("昵称只能包含字母、数字和下划线，长度为 3-32 位")
    if len(password) < ADMIN_PASSWORD_MIN_LENGTH:
        raise AdminBootstrapError(
            f"管理员密码长度至少为 {ADMIN_PASSWORD_MIN_LENGTH} 位"
        )
    if len(password) > PASSWORD_MAX_LENGTH:
        raise AdminBootstrapError(f"管理员密码长度不能超过 {PASSWORD_MAX_LENGTH} 位")

    normalized_display_name = display_name.strip() if display_name else None
    if normalized_display_name and len(normalized_display_name) > 80:
        raise AdminBootstrapError("姓名长度不能超过 80 位")

    connection = get_db_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM users WHERE role = 'admin' AND is_active = 1 LIMIT 1"
                )
                if cursor.fetchone() is not None:
                    raise AdminBootstrapError(
                        "数据库中已存在启用中的管理员，已拒绝再次执行首次引导"
                    )

                cursor.execute(
                    """
                    INSERT INTO users
                      (username, password_hash, display_name, role, is_active)
                    VALUES (%s, %s, %s, 'admin', 1)
                    """,
                    (
                        normalized_username,
                        hash_password(password),
                        normalized_display_name,
                    ),
                )
                user_id = cursor.lastrowid
    except IntegrityError as exc:
        raise AdminBootstrapError("昵称已存在，请换一个昵称") from exc

    return {
        "id": user_id,
        "username": normalized_username,
        "displayName": normalized_display_name,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="安全创建数据库中的首个管理员")
    parser.add_argument("--username", required=True, help="管理员登录昵称")
    parser.add_argument("--display-name", help="管理员显示姓名")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    password = getpass(f"管理员密码（至少 {ADMIN_PASSWORD_MIN_LENGTH} 位）: ")
    confirmation = getpass("再次输入管理员密码: ")
    if password != confirmation:
        print("两次输入的密码不一致")
        return 1

    try:
        user = create_initial_admin(args.username, password, args.display_name)
    except AdminBootstrapError as exc:
        print(f"创建失败：{exc}")
        return 1

    print(f"管理员已创建：{user['username']}（ID: {user['id']}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
