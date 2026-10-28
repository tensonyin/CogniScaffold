"""
知阶 CogniScaffold SQLite 数据库持久化层 (WAL 并发模式)
包含：
- 用户管理与凭据安全存储
- 会话与多轮消息持久化 (与原 dict 结构 100% 兼容)
- 会话令牌管理
- 审计日志
- 历史 JSON 数据自动迁移
"""

import os
import sqlite3
import json
import time
import uuid
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from core.auth import hash_password, generate_salt, hash_token

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_FILE = os.path.join(DATA_DIR, "cogni_scaffold.db")
LEGACY_STORAGE_FILE = os.path.join(DATA_DIR, "history_store.json")


def get_db_connection() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db():
    """初始化数据库表结构与默认初始账号"""
    conn = get_db_connection()
    cur = conn.cursor()

    # 1. 用户表
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        display_name TEXT,
        role TEXT DEFAULT 'student',
        status TEXT DEFAULT 'active',
        created_at TEXT NOT NULL,
        last_login_at TEXT
    );
    """)

    # 2. 认证令牌表
    cur.execute("""
    CREATE TABLE IF NOT EXISTS auth_tokens (
        token_hash TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        ip TEXT,
        user_agent TEXT,
        expires_at INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

    # 3. 会话主表
    cur.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        title TEXT NOT NULL,
        is_starred INTEGER DEFAULT 0,
        is_initialized INTEGER DEFAULT 0,
        question TEXT DEFAULT '',
        current_stage INTEGER DEFAULT 1,
        tutor_turns INTEGER DEFAULT 0,
        solver_blueprint TEXT DEFAULT '',
        diagnostic_result TEXT,
        transfer_eval_result TEXT,
        current_variant_tier INTEGER DEFAULT 1,
        title_stage INTEGER DEFAULT 0,
        is_archived INTEGER DEFAULT 0,
        sort_order INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

    # 4. 消息明细表
    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        timestamp TEXT,
        metadata TEXT,
        created_at INTEGER NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

    # 5. 用户个性化配置表 (活跃会话、主题风格等)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_preferences (
        user_id TEXT PRIMARY KEY,
        current_session_id TEXT,
        theme TEXT DEFAULT 'dark',
        custom_accent TEXT,
        session_order TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

    # 6. 安全审计日志表
    cur.execute("""
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        action TEXT NOT NULL,
        ip TEXT,
        details TEXT,
        created_at TEXT NOT NULL
    );
    """)

    # 7. 系统配置表 (全局限额、资费单价等)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS system_configs (
        config_key TEXT PRIMARY KEY,
        config_value TEXT NOT NULL,
        description TEXT,
        updated_at TEXT NOT NULL
    );
    """)

    # 8. Token 消耗统计明细表
    cur.execute("""
    CREATE TABLE IF NOT EXISTS token_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        session_id TEXT,
        task_type TEXT NOT NULL,
        prompt_tokens INTEGER DEFAULT 0,
        completion_tokens INTEGER DEFAULT 0,
        total_tokens INTEGER DEFAULT 0,
        date TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

    # 9. 敏感与违规拦截日志表
    cur.execute("""
    CREATE TABLE IF NOT EXISTS guardrail_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        username TEXT NOT NULL,
        session_id TEXT,
        matched_pattern TEXT NOT NULL,
        input_snippet TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """)

    # 10. 用户反馈与管理答复表
    cur.execute("""
    CREATE TABLE IF NOT EXISTS feedbacks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        username TEXT,
        category TEXT NOT NULL DEFAULT 'other',
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        contact TEXT,
        admin_reply TEXT,
        replied_by TEXT,
        replied_at TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    # 索引优化
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_archived ON sessions(user_id, is_archived);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id ASC);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tokens_expires ON auth_tokens(expires_at);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_token_user_date ON token_usage(user_id, date);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_token_session ON token_usage(session_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_guardrail_user ON guardrail_logs(user_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_feedbacks_user ON feedbacks(user_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_feedbacks_status ON feedbacks(status);")

    conn.commit()

    # 检查并扩展 users 表新字段
    _migrate_user_columns(conn)

    # 检查并初始化系统全局配置
    _seed_default_configs(conn)

    # 检查并创建内置账号
    _seed_default_users(conn)

    # 检查并迁移历史 JSON 数据
    _migrate_legacy_json_data(conn)

    # 检查并注入 student01 的 22 个学科与探索金牌实例 (全员置星与完成对话)
    _seed_student01_golden_presets(conn)

    conn.close()


def _migrate_user_columns(conn: sqlite3.Connection):
    """自动向 users 表迁移新增字段：封禁时间、封禁原因、自定义开题限额、自定义轮次限额"""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(users);")
    cols = [r["name"] for r in cur.fetchall()]
    if "banned_until" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN banned_until TEXT;")
    if "ban_reason" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN ban_reason TEXT;")
    if "custom_daily_limit" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN custom_daily_limit INTEGER;")
    if "custom_turn_limit" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN custom_turn_limit INTEGER;")
    conn.commit()


def _seed_default_configs(conn: sqlite3.Connection):
    """初始化全局限额与资费配置"""
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    defaults = [
        ("daily_question_limit", "15", "非管理员单日允许开题的最多题目数（道）"),
        ("session_turn_limit", "30", "单道题目允许进行的最多思维引导交互轮次（轮）"),
        ("deepseek_input_price_per_m", "1.0", "DeepSeek 每百万输入 Token 费用 (元)"),
        ("deepseek_output_price_per_m", "2.0", "DeepSeek 每百万输出 Token 费用 (元)")
    ]
    for key, val, desc in defaults:
        cur.execute("SELECT config_key FROM system_configs WHERE config_key = ?;", (key,))
        if not cur.fetchone():
            cur.execute("""
            INSERT INTO system_configs (config_key, config_value, description, updated_at)
            VALUES (?, ?, ?, ?);
            """, (key, val, desc, now))
    conn.commit()


def _seed_default_users(conn: sqlite3.Connection):
    """预置系统管理员 admin 与默认学生 student01, student02"""
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. 管理员 admin / Admin@Cogni2026!
    cur.execute("SELECT id FROM users WHERE username = 'admin';")
    if not cur.fetchone():
        salt_admin = generate_salt()
        pwd_hash_admin = hash_password("Admin@Cogni2026!", salt_admin)
        admin_id = str(uuid.uuid4())[:8]
        cur.execute("""
        INSERT INTO users (id, username, password_hash, salt, display_name, role, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """, (admin_id, "admin", pwd_hash_admin, salt_admin, "系统管理员", "admin", "active", now))
        print("Initialized user: admin")

    # 2. 学生 student01 / Student@2026!
    cur.execute("SELECT id FROM users WHERE username = 'student01';")
    if not cur.fetchone():
        salt_stu = generate_salt()
        pwd_hash_stu = hash_password("Student@2026!", salt_stu)
        stu_id = str(uuid.uuid4())[:8]
        cur.execute("""
        INSERT INTO users (id, username, password_hash, salt, display_name, role, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """, (stu_id, "student01", pwd_hash_stu, salt_stu, "知阶学者 01", "student", "active", now))
        print("Initialized user: student01")

    # 3. 学生 student02 / Student@2026!
    cur.execute("SELECT id FROM users WHERE username = 'student02';")
    if not cur.fetchone():
        salt_stu2 = generate_salt()
        pwd_hash_stu2 = hash_password("Student@2026!", salt_stu2)
        stu2_id = str(uuid.uuid4())[:8]
        cur.execute("""
        INSERT INTO users (id, username, password_hash, salt, display_name, role, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """, (stu2_id, "student02", pwd_hash_stu2, salt_stu2, "知阶学者 02", "student", "active", now))
        print("Initialized user: student02")

    conn.commit()


def _migrate_legacy_json_data(conn: sqlite3.Connection):
    """若存在 legacy history_store.json 且 student01 名下尚无会话，则将旧会话自动无缝导入"""
    if not os.path.exists(LEGACY_STORAGE_FILE):
        return

    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username = 'student01';")
    stu_row = cur.fetchone()
    if not stu_row:
        return
    stu_id = stu_row["id"]

    cur.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ?;", (stu_id,))
    if cur.fetchone()[0] > 0:
        return  # 已经有会话了，不再重复迁移

    try:
        with open(LEGACY_STORAGE_FILE, "r", encoding="utf-8") as f:
            legacy_data = json.load(f)

        active = legacy_data.get("active_sessions", {})
        archived = legacy_data.get("archived_sessions", {})
        cur_id = legacy_data.get("current_session_id")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 迁移 active sessions
        order_idx = 0
        for s_id, s_data in active.items():
            _insert_session_record(conn, stu_id, s_data, is_archived=0, sort_order=order_idx)
            order_idx += 1

        # 迁移 archived sessions
        for s_id, s_data in archived.items():
            _insert_session_record(conn, stu_id, s_data, is_archived=1, sort_order=0)

        # 记录用户默认会话偏好
        cur.execute("""
        INSERT OR REPLACE INTO user_preferences (user_id, current_session_id, theme, session_order)
        VALUES (?, ?, ?, ?);
        """, (stu_id, cur_id, "dark", json.dumps(list(active.keys()))))

        conn.commit()
        print(f"Successfully migrated {len(active)} active and {len(archived)} archived sessions to user student01.")
    except Exception as e:
        print(f"Error migrating legacy history data: {e}")


def _seed_student01_golden_presets(conn: sqlite3.Connection):
    """为 student01 账号注入全部 22 个学科与探索实例的完整对话，并默认置星收藏（追加保留现有记录）"""
    try:
        from core.presets import GOLDEN_PRESETS
    except Exception as e:
        print(f"Warning: could not import GOLDEN_PRESETS: {e}")
        return

    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username = 'student01';")
    stu_row = cur.fetchone()
    if not stu_row:
        return
    stu_id = stu_row["id"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 获取 student01 当前已有的题目
    cur.execute("SELECT question, id FROM sessions WHERE user_id = ?;", (stu_id,))
    existing = {row["question"]: row["id"] for row in cur.fetchall() if row["question"]}

    # 查询当前最大 sort_order
    cur.execute("SELECT COALESCE(MAX(sort_order), 0) FROM sessions WHERE user_id = ?;", (stu_id,))
    max_order = cur.fetchone()[0]

    first_preset_id = None
    inserted_count = 0

    for key, p in GOLDEN_PRESETS.items():
        q = p.get("question", "")
        if not q:
            continue
        max_order += 1
        
        # 提取 3 轮完整师生对话 (共 6 条消息)
        sim_list = p.get("offline_simulation", [])
        dialogue = []
        if p.get("initial_student_input"):
            dialogue.append({"role": "user", "content": p["initial_student_input"], "timestamp": now})
        for r in sim_list:
            if r.get("round") == 1:
                dialogue.append({"role": "assistant", "content": r.get("tutor_response", "").replace("[TRIGGER_DIAGNOSIS]", "").strip(), "timestamp": now})
            elif r.get("round") == 2:
                if r.get("student_reply"):
                    dialogue.append({"role": "user", "content": r["student_reply"], "timestamp": now})
                dialogue.append({"role": "assistant", "content": r.get("tutor_response", "").replace("[TRIGGER_DIAGNOSIS]", "").strip(), "timestamp": now})
            elif r.get("round") == 3:
                if r.get("student_reply"):
                    dialogue.append({"role": "user", "content": r["student_reply"], "timestamp": now})
                dialogue.append({"role": "assistant", "content": r.get("tutor_response", "").replace("[TRIGGER_DIAGNOSIS]", "").strip(), "timestamp": now})

        if q in existing:
            # 已经存在此实例：仅更新标题、阶段与诊断信息，严禁篡改或覆盖用户的 is_archived 与 is_starred 归档及收藏状态
            cur.execute("""
            UPDATE sessions 
            SET title = ?, tutor_turns = 3, current_stage = 2, diagnostic_result = NULL, transfer_eval_result = NULL 
            WHERE user_id = ? AND question = ?;
            """, (p.get("title", key), stu_id, q))

            # 遍历该题目的每个会话，确保至少有全量 6 条完成对话
            cur.execute("SELECT id FROM sessions WHERE user_id = ? AND question = ?;", (stu_id, q))
            matching_ids = [r["id"] for r in cur.fetchall()]
            for s_id in matching_ids:
                cur.execute("SELECT COUNT(*) FROM messages WHERE session_id = ?;", (s_id,))
                existing_msg_count = cur.fetchone()[0]
                if existing_msg_count < 6 and len(dialogue) >= 6:
                    cur.execute("DELETE FROM messages WHERE session_id = ?;", (s_id,))
                    for idx, msg in enumerate(dialogue):
                        cur.execute("""
                        INSERT INTO messages (session_id, user_id, role, content, timestamp, metadata, created_at)
                        VALUES (?, ?, ?, ?, ?, NULL, ?);
                        """, (s_id, stu_id, msg["role"], msg["content"], msg.get("timestamp", now), int(time.time() * 1000) + idx))
            if not first_preset_id and matching_ids:
                first_preset_id = matching_ids[0]
            continue

        # 新插入会话
        s_id = f"preset_{key}_{stu_id[:4]}"
        if not first_preset_id:
            first_preset_id = s_id
        cur.execute("""
        INSERT INTO sessions (
            id, user_id, title, is_starred, is_initialized, question,
            current_stage, tutor_turns, solver_blueprint, diagnostic_result,
            transfer_eval_result, current_variant_tier, title_stage,
            is_archived, sort_order, created_at, updated_at
        ) VALUES (?, ?, ?, 1, 1, ?, 2, 3, ?, NULL, NULL, 1, 2, 0, ?, ?, ?);
        """, (
            s_id,
            stu_id,
            p.get("title", key),
            q,
            p.get("solver_blueprint", ""),
            max_order,
            now,
            now
        ))

        for idx, msg in enumerate(dialogue):
            cur.execute("""
            INSERT INTO messages (session_id, user_id, role, content, timestamp, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, NULL, ?);
            """, (s_id, stu_id, msg["role"], msg["content"], msg.get("timestamp", now), int(time.time() * 1000) + idx))

        inserted_count += 1

    # 检查 student01 的 user_preferences 是否有当前活跃会话
    cur.execute("SELECT current_session_id FROM user_preferences WHERE user_id = ?;", (stu_id,))
    pref_row = cur.fetchone()
    if not pref_row or not pref_row["current_session_id"]:
        cur.execute("""
        INSERT OR REPLACE INTO user_preferences (user_id, current_session_id, theme, session_order)
        VALUES (?, ?, 'dark', NULL);
        """, (stu_id, first_preset_id))

    conn.commit()
    print(f"Seeded student01 with {inserted_count} new presets (all 22 starred and completed).")


def _insert_session_record(conn: sqlite3.Connection, user_id: str, s: Dict[str, Any], is_archived: int, sort_order: int):
    cur = conn.cursor()
    s_id = s.get("id") or str(uuid.uuid4())[:8]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
    INSERT OR REPLACE INTO sessions (
        id, user_id, title, is_starred, is_initialized, question,
        current_stage, tutor_turns, solver_blueprint, diagnostic_result,
        transfer_eval_result, current_variant_tier, title_stage,
        is_archived, sort_order, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, (
        s_id,
        user_id,
        s.get("title", "🧩 探索·新建会话"),
        1 if s.get("is_starred") else 0,
        1 if s.get("is_initialized") else 0,
        s.get("question", ""),
        s.get("current_stage", 1),
        s.get("tutor_turns", 0),
        s.get("solver_blueprint", ""),
        json.dumps(s.get("diagnostic_result")) if s.get("diagnostic_result") else None,
        json.dumps(s.get("transfer_eval_result")) if s.get("transfer_eval_result") else None,
        s.get("current_variant_tier", 1),
        s.get("title_stage", 0),
        is_archived,
        sort_order,
        s.get("created_at", now),
        now
    ))

    # 迁移消息
    history = s.get("dialogue_history", [])
    for msg_idx, msg in enumerate(history):
        cur.execute("""
        INSERT INTO messages (session_id, user_id, role, content, timestamp, metadata, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """, (
            s_id,
            user_id,
            msg.get("role", "user"),
            msg.get("content", ""),
            msg.get("timestamp", ""),
            json.dumps(msg.get("metadata", {})) if msg.get("metadata") else None,
            int(time.time() * 1000) + msg_idx
        ))


# ============================================================
# 用户与认证操作
# ============================================================

def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = ?;", (username,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    d = dict(row)
    # 自动解封检查
    if d.get("status") == "locked" and d.get("banned_until") and d.get("banned_until") != "permanent":
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if now_str >= d["banned_until"]:
            cur.execute("UPDATE users SET status = 'active', banned_until = NULL, ban_reason = NULL WHERE id = ?;", (d["id"],))
            conn.commit()
            d["status"] = "active"
            d["banned_until"] = None
            d["ban_reason"] = None
    conn.close()
    return d


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?;", (user_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    d = dict(row)
    # 自动解封检查
    if d.get("status") == "locked" and d.get("banned_until") and d.get("banned_until") != "permanent":
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if now_str >= d["banned_until"]:
            cur.execute("UPDATE users SET status = 'active', banned_until = NULL, ban_reason = NULL WHERE id = ?;", (d["id"],))
            conn.commit()
            d["status"] = "active"
            d["banned_until"] = None
            d["ban_reason"] = None
    conn.close()
    return d


def create_user(username: str, plain_password: str, display_name: str = "", role: str = "student") -> Dict[str, Any]:
    salt = generate_salt()
    pwd_hash = hash_password(plain_password, salt)
    user_id = str(uuid.uuid4())[:8]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    disp = display_name if display_name else f"知阶学者 {username}"

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO users (id, username, password_hash, salt, display_name, role, status, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
    """, (user_id, username, pwd_hash, salt, disp, role, "active", now))
    conn.commit()
    conn.close()

    return {
        "id": user_id,
        "username": username,
        "display_name": disp,
        "role": role,
        "status": "active",
        "created_at": now
    }


def update_user_password(user_id: str, new_plain_password: str):
    new_salt = generate_salt()
    new_hash = hash_password(new_plain_password, new_salt)

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    UPDATE users SET password_hash = ?, salt = ? WHERE id = ?;
    """, (new_hash, new_salt, user_id))
    # 密码修改后将该用户所有旧令牌注销，强制重新登录
    cur.execute("DELETE FROM auth_tokens WHERE user_id = ?;", (user_id,))
    conn.commit()
    conn.close()


def set_user_status(user_id: str, status: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET status = ? WHERE id = ?;", (status, user_id))
    if status == "locked":
        cur.execute("DELETE FROM auth_tokens WHERE user_id = ?;", (user_id,))
    conn.commit()
    conn.close()


def list_all_users() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, username, display_name, role, status, created_at, last_login_at FROM users ORDER BY created_at ASC;")
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_auth_token_session(user_id: str, ip: str = "", user_agent: str = "", expire_days: int = 7) -> str:
    raw_token = generate_salt(32)  # 64 位字符高熵 Token
    hashed = hash_token(raw_token)
    expires_at = int(time.time()) + (expire_days * 86400)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO auth_tokens (token_hash, user_id, ip, user_agent, expires_at, created_at)
    VALUES (?, ?, ?, ?, ?, ?);
    """, (hashed, user_id, ip, user_agent[:255] if user_agent else "", expires_at, now))

    # 更新用户的 last_login_at
    cur.execute("UPDATE users SET last_login_at = ? WHERE id = ?;", (now, user_id))
    conn.commit()
    conn.close()
    return raw_token


def get_user_from_token(raw_token: str) -> Optional[Dict[str, Any]]:
    if not raw_token:
        return None
    hashed = hash_token(raw_token)
    now_ts = int(time.time())

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT t.expires_at, u.id, u.username, u.display_name, u.role, u.status
    FROM auth_tokens t
    JOIN users u ON t.user_id = u.id
    WHERE t.token_hash = ? AND t.expires_at > ? AND u.status = 'active';
    """, (hashed, now_ts))
    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "status": row["status"]
    }


def delete_auth_token(raw_token: str):
    if not raw_token:
        return
    hashed = hash_token(raw_token)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM auth_tokens WHERE token_hash = ?;", (hashed,))
    conn.commit()
    conn.close()


def log_audit_event(user_id: Optional[str], action: str, ip: str, details: str):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO audit_logs (user_id, action, ip, details, created_at)
    VALUES (?, ?, ?, ?, ?);
    """, (user_id, action, ip, details, now))
    conn.commit()
    conn.close()


# ============================================================
# 用户多会话 CRUD 引擎 (与核心推理引擎完全兼容)
# ============================================================

def get_user_store(user_id: str) -> Dict[str, Any]:
    """
    获取指定用户完整的会话集（包含活跃会话、归档会话、当前选中会话 ID 等）
    格式与原有 load_all_data() 保持一致，无需改动现有上层逻辑
    """
    conn = get_db_connection()
    cur = conn.cursor()

    # 1. 查询偏好
    cur.execute("SELECT current_session_id, theme, session_order FROM user_preferences WHERE user_id = ?;", (user_id,))
    pref_row = cur.fetchone()
    current_session_id = pref_row["current_session_id"] if pref_row else None
    theme = pref_row["theme"] if pref_row else "dark"
    session_order = json.loads(pref_row["session_order"]) if pref_row and pref_row["session_order"] else []

    # 2. 查询活跃会话
    cur.execute("""
    SELECT * FROM sessions WHERE user_id = ? AND is_archived = 0 ORDER BY sort_order ASC, created_at ASC;
    """, (user_id,))
    active_rows = cur.fetchall()

    active_sessions = {}
    for r in active_rows:
        s_id = r["id"]
        active_sessions[s_id] = _assemble_session_dict(conn, r)

    # 3. 查询归档会话
    cur.execute("""
    SELECT * FROM sessions WHERE user_id = ? AND is_archived = 1 ORDER BY updated_at DESC;
    """, (user_id,))
    archived_rows = cur.fetchall()

    archived_sessions = {}
    for r in archived_rows:
        s_id = r["id"]
        archived_sessions[s_id] = _assemble_session_dict(conn, r)

    # 若当前无任何活跃会话，为该用户创建 1 个默认的新探索会话
    if not active_sessions:
        default_sess = {
            "id": str(uuid.uuid4())[:8],
            "title": "🧩 探索·新建会话",
            "is_starred": False,
            "is_initialized": False,
            "question": "",
            "current_stage": 1,
            "tutor_turns": 0,
            "dialogue_history": [],
            "solver_blueprint": "",
            "diagnostic_result": None,
            "transfer_eval_result": None,
            "current_variant_tier": 1,
            "title_stage": 0,
            "created_at": datetime.now().strftime("%m-%d %H:%M")
        }
        _insert_session_record(conn, user_id, default_sess, is_archived=0, sort_order=0)
        active_sessions[default_sess["id"]] = default_sess
        current_session_id = default_sess["id"]
        cur.execute("""
        INSERT OR REPLACE INTO user_preferences (user_id, current_session_id, theme, session_order)
        VALUES (?, ?, ?, ?);
        """, (user_id, current_session_id, "dark", json.dumps([current_session_id])))
        conn.commit()

    if not current_session_id or current_session_id not in active_sessions:
        current_session_id = next(iter(active_sessions)) if active_sessions else None
        cur.execute("UPDATE user_preferences SET current_session_id = ? WHERE user_id = ?;", (current_session_id, user_id))
        conn.commit()

    conn.close()

    return {
        "active_sessions": active_sessions,
        "archived_sessions": archived_sessions,
        "current_session_id": current_session_id,
        "session_counter": len(active_sessions) + len(archived_sessions),
        "theme": theme
    }


def _assemble_session_dict(conn: sqlite3.Connection, r: sqlite3.Row) -> Dict[str, Any]:
    s_id = r["id"]
    cur = conn.cursor()
    cur.execute("SELECT role, content, timestamp, metadata FROM messages WHERE session_id = ? ORDER BY id ASC;", (s_id,))
    msg_rows = cur.fetchall()

    history = []
    for m in msg_rows:
        item = {
            "role": m["role"],
            "content": m["content"],
            "timestamp": m["timestamp"] or ""
        }
        if m["metadata"]:
            try:
                item["metadata"] = json.loads(m["metadata"])
            except Exception:
                pass
        history.append(item)

    diag = json.loads(r["diagnostic_result"]) if r["diagnostic_result"] else None
    eval_res = json.loads(r["transfer_eval_result"]) if r["transfer_eval_result"] else None

    return {
        "id": s_id,
        "title": r["title"],
        "is_starred": bool(r["is_starred"]),
        "is_initialized": bool(r["is_initialized"]),
        "is_archived": bool(r["is_archived"]),
        "question": r["question"] or "",
        "current_stage": r["current_stage"],
        "tutor_turns": r["tutor_turns"],
        "dialogue_history": history,
        "solver_blueprint": r["solver_blueprint"] or "",
        "diagnostic_result": diag,
        "transfer_eval_result": eval_res,
        "current_variant_tier": r["current_variant_tier"],
        "created_at": r["created_at"],
        "title_stage": r["title_stage"]
    }


def save_user_session(user_id: str, session_data: Dict[str, Any]):
    """保存或更新单个会话数据"""
    conn = get_db_connection()
    cur = conn.cursor()
    s_id = session_data["id"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    diag_json = json.dumps(session_data.get("diagnostic_result")) if session_data.get("diagnostic_result") else None
    eval_json = json.dumps(session_data.get("transfer_eval_result")) if session_data.get("transfer_eval_result") else None

    raw_created = session_data.get("created_at")
    if not raw_created:
        created_at_db = now
    elif len(raw_created) <= 12 and "-" in raw_created:  # e.g. "10-28 13:45"
        year = datetime.now().strftime("%Y")
        created_at_db = f"{year}-{raw_created}:00"
    else:
        created_at_db = raw_created

    cur.execute("""
    INSERT INTO sessions (
        id, user_id, title, is_starred, is_initialized, question,
        current_stage, tutor_turns, solver_blueprint, diagnostic_result,
        transfer_eval_result, current_variant_tier, title_stage,
        is_archived, sort_order, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
        title = excluded.title,
        is_starred = excluded.is_starred,
        is_initialized = excluded.is_initialized,
        question = excluded.question,
        current_stage = excluded.current_stage,
        tutor_turns = excluded.tutor_turns,
        solver_blueprint = excluded.solver_blueprint,
        diagnostic_result = excluded.diagnostic_result,
        transfer_eval_result = excluded.transfer_eval_result,
        current_variant_tier = excluded.current_variant_tier,
        title_stage = excluded.title_stage,
        updated_at = excluded.updated_at;
    """, (
        s_id,
        user_id,
        session_data.get("title", "🧩 探索·新建会话"),
        1 if session_data.get("is_starred") else 0,
        1 if session_data.get("is_initialized") else 0,
        session_data.get("question", ""),
        session_data.get("current_stage", 1),
        session_data.get("tutor_turns", 0),
        session_data.get("solver_blueprint", ""),
        diag_json,
        eval_json,
        session_data.get("current_variant_tier", 1),
        session_data.get("title_stage", 0),
        created_at_db,
        now
    ))

    # 更新消息：重写当前会话消息列表
    cur.execute("DELETE FROM messages WHERE session_id = ?;", (s_id,))
    history = session_data.get("dialogue_history", [])
    now_ts = int(time.time() * 1000)
    for idx, msg in enumerate(history):
        cur.execute("""
        INSERT INTO messages (session_id, user_id, role, content, timestamp, metadata, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """, (
            s_id,
            user_id,
            msg.get("role", "user"),
            msg.get("content", ""),
            msg.get("timestamp", ""),
            json.dumps(msg.get("metadata")) if msg.get("metadata") else None,
            now_ts + idx
        ))

    conn.commit()
    conn.close()


def set_user_current_session(user_id: str, session_id: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO user_preferences (user_id, current_session_id)
    VALUES (?, ?)
    ON CONFLICT(user_id) DO UPDATE SET current_session_id = excluded.current_session_id;
    """, (user_id, session_id))
    conn.commit()
    conn.close()


def set_user_session_order(user_id: str, order_list: List[str]):
    conn = get_db_connection()
    cur = conn.cursor()
    for idx, s_id in enumerate(order_list):
        cur.execute("UPDATE sessions SET sort_order = ? WHERE id = ? AND user_id = ?;", (idx, s_id, user_id))
    cur.execute("""
    INSERT INTO user_preferences (user_id, session_order)
    VALUES (?, ?)
    ON CONFLICT(user_id) DO UPDATE SET session_order = excluded.session_order;
    """, (user_id, json.dumps(order_list)))
    conn.commit()
    conn.close()


def archive_user_session(user_id: str, session_id: str):
    conn = get_db_connection()
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("UPDATE sessions SET is_archived = 1, updated_at = ? WHERE id = ? AND user_id = ?;",
                (now, session_id, user_id))

    # 同步清理偏好：若当前选中的是此会话，重定向至其他活跃会话；并从 session_order 剔除该会话
    cur.execute("SELECT current_session_id, session_order FROM user_preferences WHERE user_id = ?;", (user_id,))
    pref_row = cur.fetchone()
    if pref_row:
        cur_sid = pref_row["current_session_id"]
        order = json.loads(pref_row["session_order"]) if pref_row["session_order"] else []
        new_order = [s for s in order if s != session_id]

        cur.execute("SELECT id FROM sessions WHERE user_id = ? AND is_archived = 0 ORDER BY sort_order ASC, created_at ASC;", (user_id,))
        active_ids = [row["id"] for row in cur.fetchall()]

        new_cur_sid = cur_sid
        if cur_sid == session_id or cur_sid not in active_ids:
            new_cur_sid = active_ids[0] if active_ids else None

        cur.execute("""
        UPDATE user_preferences 
        SET current_session_id = ?, session_order = ? 
        WHERE user_id = ?;
        """, (new_cur_sid, json.dumps(new_order), user_id))

    conn.commit()
    conn.close()


def restore_user_session(user_id: str, session_id: str):
    conn = get_db_connection()
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("UPDATE sessions SET is_archived = 0, updated_at = ? WHERE id = ? AND user_id = ?;",
                (now, session_id, user_id))

    # 恢复后将其设为当前会话，并追加进 session_order
    cur.execute("SELECT current_session_id, session_order FROM user_preferences WHERE user_id = ?;", (user_id,))
    pref_row = cur.fetchone()
    order = json.loads(pref_row["session_order"]) if (pref_row and pref_row["session_order"]) else []
    if session_id not in order:
        order.append(session_id)
    cur.execute("""
    INSERT INTO user_preferences (user_id, current_session_id, session_order)
    VALUES (?, ?, ?)
    ON CONFLICT(user_id) DO UPDATE SET current_session_id = excluded.current_session_id, session_order = excluded.session_order;
    """, (user_id, session_id, json.dumps(order)))

    conn.commit()
    conn.close()


def delete_archived_user_session(user_id: str, session_id: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM sessions WHERE id = ? AND user_id = ? AND is_archived = 1;", (session_id, user_id))
    conn.commit()
    conn.close()


def toggle_user_session_star(user_id: str, session_id: str) -> bool:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT is_starred FROM sessions WHERE id = ? AND user_id = ?;", (session_id, user_id))
    row = cur.fetchone()
    if not row:
        conn.close()
        return False
    new_starred = 0 if row["is_starred"] else 1
    cur.execute("UPDATE sessions SET is_starred = ? WHERE id = ? AND user_id = ?;", (new_starred, session_id, user_id))
    conn.commit()
    conn.close()
    return bool(new_starred)


# ============================================================
# 系统全局配置管理 (System Configurations)
# ============================================================

def get_system_config(key: str, default: str = "") -> str:
    """获取指定系统配置"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT config_value FROM system_configs WHERE config_key = ?;", (key,))
    row = cur.fetchone()
    conn.close()
    return row["config_value"] if row else default


def get_all_system_configs() -> Dict[str, Any]:
    """获取全部系统配置字典"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT config_key, config_value, description, updated_at FROM system_configs;")
    rows = cur.fetchall()
    conn.close()
    return {r["config_key"]: {"value": r["config_value"], "desc": r["description"], "updated_at": r["updated_at"]} for r in rows}


def set_system_config(key: str, value: str, description: str = ""):
    """设置系统配置项"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO system_configs (config_key, config_value, description, updated_at)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(config_key) DO UPDATE SET 
        config_value = excluded.config_value,
        description = CASE WHEN excluded.description != '' THEN excluded.description ELSE system_configs.description END,
        updated_at = excluded.updated_at;
    """, (key, str(value), description, now))
    conn.commit()
    conn.close()


# ============================================================
# Token 消耗追踪与成本统计 (Token Usage & Cost Analytics)
# ============================================================

def record_token_usage(
    user_id: str,
    session_id: Optional[str] = None,
    task_type: str = "chat_tutor",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    model_name: str = "",
    call_type: Optional[str] = None,
    **kwargs
):
    """记录一次大模型调用的 Token 消耗"""
    if call_type and not task_type:
        task_type = call_type
    elif call_type:
        task_type = call_type

    if total_tokens <= 0:
        total_tokens = prompt_tokens + completion_tokens
    now_dt = datetime.now()
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    today_str = now_dt.strftime("%Y-%m-%d")

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO token_usage (user_id, session_id, task_type, prompt_tokens, completion_tokens, total_tokens, date, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
    """, (str(user_id), session_id, task_type, prompt_tokens, completion_tokens, total_tokens, today_str, now_str))
    conn.commit()
    conn.close()


def get_token_stats_overview() -> Dict[str, Any]:
    """汇总今日 Token、总 Token、估算费用与学生消耗排行"""
    today_str = datetime.now().strftime("%Y-%m-%d")
    conn = get_db_connection()
    cur = conn.cursor()

    # 今日总消耗
    cur.execute("""
    SELECT 
        COALESCE(SUM(prompt_tokens), 0) as today_prompt,
        COALESCE(SUM(completion_tokens), 0) as today_completion,
        COALESCE(SUM(total_tokens), 0) as today_total
    FROM token_usage WHERE date = ?;
    """, (today_str,))
    today_row = cur.fetchone()

    # 历史全量总消耗
    cur.execute("""
    SELECT 
        COALESCE(SUM(prompt_tokens), 0) as total_prompt,
        COALESCE(SUM(completion_tokens), 0) as total_completion,
        COALESCE(SUM(total_tokens), 0) as all_total
    FROM token_usage;
    """)
    all_row = cur.fetchone()

    # 资费单价 (默认 DeepSeek 现行资费: 输入 1元/1M, 输出 2元/1M)
    input_price = float(get_system_config("deepseek_input_price_per_m", "1.0"))
    output_price = float(get_system_config("deepseek_output_price_per_m", "2.0"))

    today_cost = (today_row["today_prompt"] * input_price / 1_000_000) + (today_row["today_completion"] * output_price / 1_000_000)
    all_cost = (all_row["total_prompt"] * input_price / 1_000_000) + (all_row["total_completion"] * output_price / 1_000_000)

    # Top 10 学生排行
    cur.execute("""
    SELECT u.id, u.username, u.display_name, u.status,
           COALESCE(SUM(t.total_tokens), 0) as student_total_tokens,
           COUNT(DISTINCT t.session_id) as session_count
    FROM users u
    LEFT JOIN token_usage t ON u.id = t.user_id
    WHERE u.role != 'admin'
    GROUP BY u.id
    ORDER BY student_total_tokens DESC
    LIMIT 10;
    """)
    top_students = [dict(r) for r in cur.fetchall()]

    conn.close()
    return {
        "today_tokens": today_row["today_total"],
        "today_prompt": today_row["today_prompt"],
        "today_completion": today_row["today_completion"],
        "today_cost_rmb": round(today_cost, 4),
        "all_tokens": all_row["all_total"],
        "all_prompt": all_row["total_prompt"],
        "all_completion": all_row["total_completion"],
        "all_cost_rmb": round(all_cost, 4),
        "top_students": top_students
    }


# ============================================================
# 敏感违规与合规审计日志 (Guardrail Logging)
# ============================================================

def record_guardrail_log(
    user_id: str,
    username: str = "",
    session_id: Optional[str] = None,
    matched_pattern: str = "",
    input_snippet: str = "",
    input_text: str = "",
    **kwargs
):
    """记录学生触发敏感合规拦截的日志"""
    snippet = input_snippet or input_text
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    cur = conn.cursor()
    if not username:
        cur.execute("SELECT username FROM users WHERE id = ?;", (str(user_id),))
        row = cur.fetchone()
        if row:
            username = row["username"]
    cur.execute("""
    INSERT INTO guardrail_logs (user_id, username, session_id, matched_pattern, input_snippet, created_at)
    VALUES (?, ?, ?, ?, ?, ?);
    """, (str(user_id), username, session_id, matched_pattern, snippet[:300], now))
    conn.commit()
    conn.close()


def get_guardrail_logs(limit: int = 50) -> List[Dict[str, Any]]:
    """获取最近的违规拦截日志"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT id, user_id, username, session_id, matched_pattern, input_snippet, created_at
    FROM guardrail_logs
    ORDER BY id DESC LIMIT ?;
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============================================================
# 账号封禁、特批限额与管理员重置密码
# ============================================================

def check_user_ban_status(user_id: str) -> Tuple[bool, str, Optional[str]]:
    """
    检查指定用户是否处于封禁状态
    返回: (is_banned: bool, ban_reason: str, banned_until: Optional[str])
    若临时封禁已到期，自动解除封禁并恢复 active
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT status, banned_until, ban_reason FROM users WHERE id = ?;", (user_id,))
    row = cur.fetchone()
    if not row or row["status"] != "locked":
        conn.close()
        return False, "", None

    b_until = row["banned_until"]
    reason = row["ban_reason"] or "管理员封禁"

    if b_until and b_until != "permanent":
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if now_str >= b_until:
            # 自动解封
            cur.execute("UPDATE users SET status = 'active', banned_until = NULL, ban_reason = NULL WHERE id = ?;", (user_id,))
            conn.commit()
            conn.close()
            return False, "", None

    conn.close()
    return True, reason, b_until


def ban_user(user_id: str, banned_until: Optional[str] = "permanent", reason: str = "违规使用", admin_id: Optional[str] = None):
    """封禁指定用户，并立即清退其全部在线 Token"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    UPDATE users 
    SET status = 'locked', ban_reason = ?, banned_until = ?
    WHERE id = ?;
    """, (reason, banned_until or "permanent", str(user_id)))
    # 吊销全部在线 token
    cur.execute("DELETE FROM auth_tokens WHERE user_id = ?;", (str(user_id),))
    conn.commit()
    conn.close()


def unban_user(user_id: str):
    """解除用户封禁"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    UPDATE users 
    SET status = 'active', ban_reason = NULL, banned_until = NULL
    WHERE id = ?;
    """, (str(user_id),))
    conn.commit()
    conn.close()


def reset_user_password_by_admin(user_id: str, new_password: str, admin_id: Optional[str] = None):
    """管理员强制重置用户密码"""
    new_salt = generate_salt()
    new_hash = hash_password(new_password, new_salt)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    UPDATE users SET password_hash = ?, salt = ? WHERE id = ?;
    """, (new_hash, new_salt, str(user_id)))
    # 密码修改后将该用户所有旧令牌注销
    cur.execute("DELETE FROM auth_tokens WHERE user_id = ?;", (str(user_id),))
    conn.commit()
    conn.close()
    return True


def set_user_custom_quota(user_id: str, daily_limit: Optional[int], turn_limit: Optional[int]):
    """设置用户个性化特批限额 (None 则清除恢复全局限额)"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    UPDATE users 
    SET custom_daily_limit = ?, custom_turn_limit = ?
    WHERE id = ?;
    """, (daily_limit, turn_limit, str(user_id)))
    conn.commit()
    conn.close()


def reset_user_today_questions(user_id: str):
    """管理员特批：一键重置某学生今日已用开题次数"""
    today_full = datetime.now().strftime("%Y-%m-%d")
    today_short = datetime.now().strftime("%m-%d")
    conn = get_db_connection()
    cur = conn.cursor()
    # 将今日创建的会话 created_at 日期前移一天，从而绕过当日 00:00 计数
    cur.execute("""
    UPDATE sessions 
    SET created_at = '2000-01-01 00:00:00'
    WHERE user_id = ? AND (created_at LIKE ? OR created_at LIKE ?);
    """, (str(user_id), f"{today_full}%", f"{today_short}%"))
    conn.commit()
    conn.close()


# ============================================================
# 批量创建账号 (Batch Account Creation)
# ============================================================

def batch_create_users(user_list: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    批量添加账号
    user_list: [{"username": "...", "password": "...", "display_name": "..."}]
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    created = []
    skipped = []
    errors = []

    conn = get_db_connection()
    cur = conn.cursor()

    for item in user_list:
        uname = (item.get("username") or "").strip()
        pwd = (item.get("password") or "").strip()
        disp = (item.get("display_name") or uname).strip()

        if not uname or not pwd:
            errors.append(f"账号或密码为空：{uname}")
            continue

        # 检查是否重复
        cur.execute("SELECT id FROM users WHERE username = ?;", (uname,))
        if cur.fetchone():
            skipped.append(uname)
            continue

        salt = generate_salt()
        pwd_hash = hash_password(pwd, salt)
        u_id = str(uuid.uuid4())[:8]

        try:
            cur.execute("""
            INSERT INTO users (id, username, password_hash, salt, display_name, role, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'student', 'active', ?);
            """, (u_id, uname, pwd_hash, salt, disp, now))
            created.append(uname)
        except Exception as e:
            errors.append(f"{uname}: {str(e)}")

    conn.commit()
    conn.close()

    return {
        "success_count": len(created),
        "skipped_count": len(skipped),
        "created_users": created,
        "skipped_users": skipped,
        "errors": errors
    }


# ============================================================
# 限额判定与门禁 (Quota Check & Enforcement)
# ============================================================

def get_user_effective_limits(user_id: str) -> Tuple[int, int]:
    """获取某用户的生效限额：(单日开题上限, 单题轮次上限)"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT role, custom_daily_limit, custom_turn_limit FROM users WHERE id = ?;", (user_id,))
    row = cur.fetchone()
    conn.close()

    if not row or row["role"] == "admin":
        return 99999, 99999  # 管理员无限制

    default_daily = int(get_system_config("daily_question_limit", "15"))
    default_turns = int(get_system_config("session_turn_limit", "30"))

    daily = row["custom_daily_limit"] if (row["custom_daily_limit"] is not None and row["custom_daily_limit"] > 0) else default_daily
    turns = row["custom_turn_limit"] if (row["custom_turn_limit"] is not None and row["custom_turn_limit"] > 0) else default_turns

    return daily, turns


def get_user_today_questions_count(user_id: str) -> int:
    """获取某用户今日已开题数量"""
    today_full = datetime.now().strftime("%Y-%m-%d")
    today_short = datetime.now().strftime("%m-%d")
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT COUNT(1) as cnt 
    FROM sessions 
    WHERE user_id = ? AND is_initialized = 1 AND (created_at LIKE ? OR created_at LIKE ?);
    """, (user_id, f"{today_full}%", f"{today_short}%"))
    row = cur.fetchone()
    conn.close()
    return row["cnt"] if row else 0


def check_can_create_question(user_id: str, is_admin: bool = False) -> Tuple[bool, int, int]:
    """检查是否允许开题: 返回 (允许与否, 今日已用, 上限)"""
    if is_admin:
        return True, 0, 99999
    daily_limit, _ = get_user_effective_limits(user_id)
    today_count = get_user_today_questions_count(user_id)
    return (today_count < daily_limit), today_count, daily_limit


def check_can_continue_chat(user_id: str, session: Dict[str, Any], is_admin: bool = False) -> Tuple[bool, int, int]:
    """检查单题是否已达轮次上限: 返回 (允许与否, 当前轮次, 上限)"""
    if is_admin:
        return True, session.get("tutor_turns", 0), 99999
    _, turn_limit = get_user_effective_limits(user_id)
    current_turns = session.get("tutor_turns", 0)
    return (current_turns < turn_limit), current_turns, turn_limit


# ============================================================
# 管理员数据大屏与列表查询聚合
# ============================================================

def get_admin_overview() -> Dict[str, Any]:
    """控制台概览总指标"""
    today_str = datetime.now().strftime("%Y-%m-%d")
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(1) as total_users, SUM(CASE WHEN status='locked' THEN 1 ELSE 0 END) as locked_users FROM users WHERE role != 'admin';")
    u_row = cur.fetchone()

    cur.execute("SELECT COUNT(1) as total_sessions FROM sessions WHERE is_initialized = 1;")
    s_row = cur.fetchone()

    cur.execute("SELECT COUNT(1) as today_sessions FROM sessions WHERE is_initialized = 1 AND created_at LIKE ?;", (f"{today_str}%",))
    ts_row = cur.fetchone()

    cur.execute("SELECT COUNT(1) as total_messages FROM messages;")
    m_row = cur.fetchone()

    conn.close()

    token_stats = get_token_stats_overview()
    daily_limit = int(get_system_config("daily_question_limit", "15"))
    turn_limit = int(get_system_config("session_turn_limit", "30"))

    return {
        "total_students": u_row["total_users"] if u_row else 0,
        "locked_students": u_row["locked_users"] if u_row else 0,
        "total_sessions": s_row["total_sessions"] if s_row else 0,
        "today_sessions": ts_row["today_sessions"] if ts_row else 0,
        "total_messages": m_row["total_messages"] if m_row else 0,
        "daily_limit_config": daily_limit,
        "turn_limit_config": turn_limit,
        "token_stats": token_stats
    }


def get_admin_users_list(search: str = "", status: str = "") -> List[Dict[str, Any]]:
    """管理员账号列表检索与详细聚合"""
    today_str = datetime.now().strftime("%Y-%m-%d")
    conn = get_db_connection()
    cur = conn.cursor()

    sql = """
    SELECT 
        u.id, u.username, u.display_name, u.role, u.status, u.banned_until, u.ban_reason,
        u.created_at, u.last_login_at, u.custom_daily_limit, u.custom_turn_limit,
        (SELECT COUNT(1) FROM sessions WHERE user_id = u.id AND is_initialized = 1) as session_count,
        (SELECT COUNT(1) FROM sessions WHERE user_id = u.id AND is_initialized = 1 AND created_at LIKE ?) as today_questions,
        (SELECT COALESCE(SUM(total_tokens), 0) FROM token_usage WHERE user_id = u.id) as total_tokens
    FROM users u
    WHERE 1=1
    """
    params: List[Any] = [f"{today_str}%"]

    if search:
        sql += " AND (u.username LIKE ? OR u.display_name LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])

    if status:
        sql += " AND u.status = ?"
        params.append(status)

    sql += " ORDER BY u.role DESC, u.created_at ASC;"

    cur.execute(sql, tuple(params))
    rows = cur.fetchall()
    conn.close()

    res = []
    for r in rows:
        d = dict(r)
        # 自动校验解封状态
        b_until = d.get("banned_until")
        if d["status"] == "locked" and b_until and b_until != "permanent":
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if now_str >= b_until:
                d["status"] = "active"
                d["banned_until"] = None
                d["ban_reason"] = None
        res.append(d)
    return res


def get_admin_sessions_list(user_id: Optional[str] = None, search: str = "", limit: int = 100) -> List[Dict[str, Any]]:
    """全局会话时间流或指定学生会话列表"""
    conn = get_db_connection()
    cur = conn.cursor()

    sql = """
    SELECT 
        s.id, s.user_id, s.title, s.question, s.current_stage, s.tutor_turns,
        s.is_starred, s.is_archived, s.created_at, s.updated_at,
        u.username, u.display_name,
        (SELECT COALESCE(SUM(total_tokens), 0) FROM token_usage WHERE session_id = s.id) as session_tokens
    FROM sessions s
    JOIN users u ON s.user_id = u.id
    WHERE s.is_initialized = 1
    """
    params: List[Any] = []

    if user_id:
        sql += " AND s.user_id = ?"
        params.append(user_id)

    if search:
        sql += " AND (s.title LIKE ? OR s.question LIKE ? OR u.username LIKE ? OR u.display_name LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%", f"%{search}%"])

    sql += " ORDER BY s.updated_at DESC LIMIT ?;"
    params.append(limit)

    cur.execute(sql, tuple(params))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_admin_session_detail(session_id: str) -> Optional[Dict[str, Any]]:
    """获取单个会话的完整审计详情与对话记录"""
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
    SELECT 
        s.*, u.username, u.display_name,
        (SELECT COALESCE(SUM(total_tokens), 0) FROM token_usage WHERE session_id = s.id) as session_tokens
    FROM sessions s
    JOIN users u ON s.user_id = u.id
    WHERE s.id = ?;
    """, (session_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None

    sess = _assemble_session_dict(conn, row)
    sess["username"] = row["username"]
    sess["display_name"] = row["display_name"]
    sess["user"] = {
        "id": sess.get("user_id"),
        "username": row["username"],
        "display_name": row["display_name"]
    }
    sess["session_tokens"] = row["session_tokens"]

    # 查每条消息明细
    cur.execute("SELECT id, role, content, timestamp, metadata, created_at FROM messages WHERE session_id = ? ORDER BY id ASC;", (session_id,))
    msg_rows = cur.fetchall()
    conn.close()

    sess["messages"] = [dict(m) for m in msg_rows]
    return sess


# ============================================================
# 用户反馈与管理回复 (Feedback & Admin Replies)
# ============================================================

def submit_user_feedback(user_id: Optional[str], username: Optional[str], category: str, title: str, content: str, contact: str = "") -> Dict[str, Any]:
    """学生或用户提交反馈"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO feedbacks (user_id, username, category, title, content, contact, status, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?);
    """, (user_id, username, category or "other", title.strip(), content.strip(), contact.strip() if contact else "", now, now))
    fid = cur.lastrowid
    conn.commit()
    conn.close()
    return {
        "id": fid,
        "user_id": user_id,
        "username": username,
        "category": category,
        "title": title,
        "content": content,
        "contact": contact,
        "status": "pending",
        "created_at": now
    }


def get_user_feedbacks(user_id: str) -> List[Dict[str, Any]]:
    """获取指定用户提交的历史反馈及管理员答复"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT id, user_id, username, category, title, content, contact, admin_reply, replied_by, replied_at, status, created_at, updated_at
    FROM feedbacks
    WHERE user_id = ?
    ORDER BY id DESC;
    """, (user_id,))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_admin_feedbacks(status: Optional[str] = None, search: str = "", limit: int = 100) -> List[Dict[str, Any]]:
    """管理员全量检索反馈列表"""
    conn = get_db_connection()
    cur = conn.cursor()
    sql = """
    SELECT f.id, f.user_id, f.username, f.category, f.title, f.content, f.contact, 
           f.admin_reply, f.replied_by, f.replied_at, f.status, f.created_at, f.updated_at,
           u.display_name
    FROM feedbacks f
    LEFT JOIN users u ON f.user_id = u.id
    WHERE 1=1
    """
    params: List[Any] = []
    if status and status != "all":
        sql += " AND f.status = ?"
        params.append(status)
    if search:
        sql += " AND (f.title LIKE ? OR f.content LIKE ? OR f.username LIKE ? OR u.display_name LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%", f"%{search}%"])
    sql += " ORDER BY CASE WHEN f.status='pending' THEN 0 ELSE 1 END, f.id DESC LIMIT ?;"
    params.append(limit)
    cur.execute(sql, tuple(params))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def reply_user_feedback(feedback_id: int, admin_reply: str, admin_name: str, status: str = "replied") -> bool:
    """管理员回复学生反馈"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    UPDATE feedbacks
    SET admin_reply = ?, replied_by = ?, replied_at = ?, status = ?, updated_at = ?
    WHERE id = ?;
    """, (admin_reply.strip(), admin_name, now, status, now, feedback_id))
    affected = cur.rowcount
    conn.commit()
    conn.close()
    return affected > 0
