#!/usr/bin/env python3
"""
知阶 CogniScaffold 管理员用户控制台
用于在封闭式准入体系下安全地创建学生/教师账号、重置密码、锁定/解锁以及查看账户状态。
使用示例：
  python scripts/manage_users.py list
  python scripts/manage_users.py create --username stu02 --password "Stu2026!Pass" --display-name "李同学"
  python scripts/manage_users.py reset --username stu02 --password "NewPass@2026"
  python scripts/manage_users.py lock --username stu02
  python scripts/manage_users.py unlock --username stu02
"""

import sys
import os
import argparse

# 确保能加载工程根目录模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db import (
    init_db,
    list_all_users,
    get_user_by_username,
    create_user,
    update_user_password,
    set_user_status,
)
from core.auth import validate_password_strength


def cmd_list(args):
    users = list_all_users()
    print("=" * 75)
    print(f"{'ID':<10} {'用户名':<15} {'姓名/身份':<18} {'角色':<10} {'状态':<10} {'最后登录'}")
    print("-" * 75)
    for u in users:
        last_login = u.get("last_login_at") or "从未登录"
        print(f"{u['id']:<10} {u['username']:<15} {u['display_name']:<18} {u['role']:<10} {u['status']:<10} {last_login}")
    print("=" * 75)
    print(f"总计用户数: {len(users)}")


def cmd_create(args):
    username = args.username.strip()
    password = args.password.strip()
    display_name = args.display_name.strip() if args.display_name else ""
    role = args.role.strip()

    if not username:
        print("[错误] 用户名不能为空")
        sys.exit(1)

    existing = get_user_by_username(username)
    if existing:
        print(f"[错误] 用户名 '{username}' 已存在，请使用其他用户名或执行 reset 命令。")
        sys.exit(1)

    valid, err_msg = validate_password_strength(password)
    if not valid:
        print(f"[错误] 密码强度不达标: {err_msg}")
        sys.exit(1)

    user = create_user(username, password, display_name=display_name, role=role)
    print(f"[成功] 成功创建用户 '{username}' (ID: {user['id']}, 角色: {role})")


def cmd_reset(args):
    username = args.username.strip()
    password = args.password.strip()

    existing = get_user_by_username(username)
    if not existing:
        print(f"[错误] 用户 '{username}' 不存在")
        sys.exit(1)

    valid, err_msg = validate_password_strength(password)
    if not valid:
        print(f"[错误] 密码强度不达标: {err_msg}")
        sys.exit(1)

    update_user_password(existing["id"], password)
    print(f"[成功] 用户 '{username}' 密码已重置，该用户现有的所有登录会话已被强制下线。")


def cmd_lock(args):
    username = args.username.strip()
    existing = get_user_by_username(username)
    if not existing:
        print(f"[错误] 用户 '{username}' 不存在")
        sys.exit(1)

    set_user_status(existing["id"], "locked")
    print(f"[成功] 用户 '{username}' 已被锁定，禁止登录。")


def cmd_unlock(args):
    username = args.username.strip()
    existing = get_user_by_username(username)
    if not existing:
        print(f"[错误] 用户 '{username}' 不存在")
        sys.exit(1)

    set_user_status(existing["id"], "active")
    print(f"[成功] 用户 '{username}' 已解锁，恢复正常使用。")


def main():
    init_db()
    parser = argparse.ArgumentParser(description="知阶 CogniScaffold 账号管理工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list
    p_list = subparsers.add_parser("list", help="查看所有已分发账号")
    p_list.set_defaults(func=cmd_list)

    # create
    p_create = subparsers.add_parser("create", help="分发并创建新账号")
    p_create.add_argument("--username", "-u", required=True, help="用户名")
    p_create.add_argument("--password", "-p", required=True, help="初始密码 (需符合复杂度要求)")
    p_create.add_argument("--display-name", "-n", default="", help="显示昵称/学生真实姓名")
    p_create.add_argument("--role", "-r", default="student", choices=["student", "admin"], help="角色权限")
    p_create.set_defaults(func=cmd_create)

    # reset
    p_reset = subparsers.add_parser("reset", help="重置用户密码")
    p_reset.add_argument("--username", "-u", required=True, help="用户名")
    p_reset.add_argument("--password", "-p", required=True, help="新密码")
    p_reset.set_defaults(func=cmd_reset)

    # lock
    p_lock = subparsers.add_parser("lock", help="锁定指定账号")
    p_lock.add_argument("--username", "-u", required=True, help="用户名")
    p_lock.set_defaults(func=cmd_lock)

    # unlock
    p_unlock = subparsers.add_parser("unlock", help="解锁指定账号")
    p_unlock.add_argument("--username", "-u", required=True, help="用户名")
    p_unlock.set_defaults(func=cmd_unlock)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
