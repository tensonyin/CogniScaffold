"""
知阶 CogniScaffold 认证与安全核心模块
- 密码学安全的加盐哈希（PBKDF2-HMAC-SHA256 600,000次迭代）
- 时序攻击防御（hmac.compare_digest）
- 密码复杂度校验
- 暴力破解防护（单账号/IP 频次限制与自适应锁定）
- 会话令牌生成与校验
"""

import hashlib
import hmac
import secrets
import re
import time
from typing import Tuple, Optional, Dict, Any

PBKDF2_ITERATIONS = 600_000
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_SECONDS = 15 * 60  # 锁定 15 分钟
ATTEMPT_WINDOW_SECONDS = 10 * 60    # 10 分钟内窗口

# 内存快速限流跟踪字典: key -> {"attempts": count, "first_attempt": timestamp, "locked_until": timestamp}
_attempt_tracker: Dict[str, Dict[str, Any]] = {}


def generate_salt(length: int = 16) -> str:
    """生成密码学安全的十六进制随机盐"""
    return secrets.token_hex(length)


def hash_password(password: str, salt: str) -> str:
    """使用 PBKDF2-HMAC-SHA256 进行单向加盐哈希"""
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS
    )
    return key.hex()


def verify_password(plain_password: str, salt: str, password_hash: str) -> bool:
    """常量时间比对明文密码与存储哈希，杜绝时序侧信道攻击"""
    computed = hash_password(plain_password, salt)
    return hmac.compare_digest(computed, password_hash)


def validate_password_strength(password: str) -> Tuple[bool, str]:
    """
    密码复杂度要求：
    - 至少 8 位长度
    - 至少包含 1 个英文字母
    - 至少包含 1 个数字
    """
    if len(password) < 8:
        return False, "密码长度至少需要 8 个字符"
    if not re.search(r"[a-zA-Z]", password):
        return False, "密码必须包含英文字符"
    if not re.search(r"[0-9]", password):
        return False, "密码必须包含数字字符"
    return True, ""


def _prune_tracker(now: Optional[float] = None):
    """清理已过期或已解锁的限流记录，防止攻击者用海量随机用户名/IP 撑爆内存"""
    global _attempt_tracker
    if len(_attempt_tracker) < 5000:
        return
    current = now if now is not None else time.time()
    expired = [
        key for key, rec in _attempt_tracker.items()
        if (rec.get("locked_until", 0) and current >= rec["locked_until"])
        or (current - rec.get("first_attempt", 0) > ATTEMPT_WINDOW_SECONDS and current >= rec.get("locked_until", 0))
    ]
    for key in expired:
        _attempt_tracker.pop(key, None)


def check_rate_limit(key: str) -> Tuple[bool, int]:
    """
    检查指定键（如 'user:username' 或 'ip:1.2.3.4'）是否已被临时锁定
    返回: (is_locked, remaining_seconds)
    """
    now = time.time()
    record = _attempt_tracker.get(key)
    if not record:
        return False, 0

    locked_until = record.get("locked_until", 0)
    if now < locked_until:
        return True, int(locked_until - now)

    # 如果窗口过期，重置记录
    if now - record.get("first_attempt", 0) > ATTEMPT_WINDOW_SECONDS:
        _attempt_tracker.pop(key, None)
        return False, 0

    return False, 0


def record_failed_attempt(key: str, max_attempts: int = MAX_FAILED_ATTEMPTS) -> Tuple[bool, int, int]:
    """
    记录一次失败尝试
    返回: (is_now_locked, attempts_count, remaining_lock_seconds)
    max_attempts 可针对 IP 等共享出口设置更高阈值，避免少数错误输入锁死整个 NAT 网关。
    """
    now = time.time()
    _prune_tracker(now)
    record = _attempt_tracker.setdefault(key, {
        "attempts": 0,
        "first_attempt": now,
        "locked_until": 0
    })

    # 若之前窗口超时则重置
    if now - record["first_attempt"] > ATTEMPT_WINDOW_SECONDS:
        record["attempts"] = 0
        record["first_attempt"] = now
        record["locked_until"] = 0

    record["attempts"] += 1
    attempts = record["attempts"]

    if attempts >= max(1, max_attempts):
        record["locked_until"] = now + LOCKOUT_DURATION_SECONDS
        return True, attempts, LOCKOUT_DURATION_SECONDS

    return False, attempts, 0


def reset_failed_attempts(key: str):
    """登录成功后清除失败计数"""
    _attempt_tracker.pop(key, None)


# ============================================================
# 通用滑动窗口限流（用于反馈提交、密保查询等非登录动作）
# ============================================================
_action_tracker: Dict[str, list] = {}


def check_action_rate(key: str, max_events: int = 20, window_seconds: int = 600) -> Tuple[bool, int]:
    """
    滑动窗口限流：返回 (allowed, retry_after_seconds)。
    记录每次被允许的动作时间戳，超过阈值时拒绝并返回等待秒数。
    """
    now = time.time()
    events = [t for t in _action_tracker.get(key, []) if now - t < window_seconds]
    if len(events) >= max_events:
        retry_after = max(1, int(window_seconds - (now - events[0])) + 1)
        _action_tracker[key] = events
        return False, retry_after
    events.append(now)
    _action_tracker[key] = events

    if len(_action_tracker) > 5000:
        for k in [k for k, v in _action_tracker.items() if not v or now - v[-1] > window_seconds]:
            _action_tracker.pop(k, None)
    return True, 0


def generate_session_token() -> str:
    """生成 64 位高熵安全令牌"""
    return secrets.token_hex(32)


def hash_token(raw_token: str) -> str:
    """在数据库中仅保存 Token 的 SHA-256 散列值，防止数据库被盗导致所有活跃 Token 泄露"""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
