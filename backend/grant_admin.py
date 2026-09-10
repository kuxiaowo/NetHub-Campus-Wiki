"""Grant or revoke the Wiki-local admin role by central OIDC ``sub``."""

from __future__ import annotations

import argparse

from backend.database import get_db_connection


class AdminRoleError(RuntimeError):
    pass


def set_admin_role(auth_sub: str, *, enabled: bool = True) -> dict:
    normalized = auth_sub.strip()
    if not normalized:
        raise AdminRoleError("auth_sub 不能为空")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, username, role, is_active, deleted_at FROM users WHERE auth_sub = %s",
                (normalized,),
            )
            user = cursor.fetchone()
            if user is None:
                raise AdminRoleError("该中央账号尚未访问 Wiki；请先完成一次统一登录")
            if user.get("deleted_at") or not user.get("is_active"):
                raise AdminRoleError("不能授权已删除或已停用的本地成员")
            role = "admin" if enabled else "user"
            cursor.execute(
                "UPDATE users SET role = %s WHERE id = %s", (role, user["id"])
            )
    return {"id": user["id"], "username": user["username"], "role": role}


def main() -> int:
    parser = argparse.ArgumentParser(description="按中央 sub 管理 Wiki 本地管理员角色")
    parser.add_argument("--auth-sub", required=True, help="NetHub Accounts 的稳定 sub")
    parser.add_argument("--revoke", action="store_true", help="撤销管理员角色")
    args = parser.parse_args()
    try:
        user = set_admin_role(args.auth_sub, enabled=not args.revoke)
    except AdminRoleError as exc:
        print(f"操作失败：{exc}")
        return 1
    print(f"已更新：{user['username']}（本地 ID {user['id']}）=> {user['role']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
