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

    # 索引优化
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_archived ON sessions(user_id, is_archived);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id ASC);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tokens_expires ON auth_tokens(expires_at);")

    conn.commit()

    # 检查并创建内置账号
    _seed_default_users(conn)

    # 检查并迁移历史 JSON 数据
    _migrate_legacy_json_data(conn)

    conn.close()


def _seed_default_users(conn: sqlite3.Connection):
    """预置系统管理员 admin 与默认学生 student01"""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users;")
    count = cur.fetchone()[0]

    if count == 0:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1. 管理员 admin / Admin@Cogni2026!
        salt_admin = generate_salt()
        pwd_hash_admin = hash_password("Admin@Cogni2026!", salt_admin)
        admin_id = str(uuid.uuid4())[:8]
        cur.execute("""
        INSERT INTO users (id, username, password_hash, salt, display_name, role, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """, (admin_id, "admin", pwd_hash_admin, salt_admin, "系统管理员", "admin", "active", now))

        # 2. 学生 student01 / Student@2026!
        salt_stu = generate_salt()
        pwd_hash_stu = hash_password("Student@2026!", salt_stu)
        stu_id = str(uuid.uuid4())[:8]
        cur.execute("""
        INSERT INTO users (id, username, password_hash, salt, display_name, role, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """, (stu_id, "student01", pwd_hash_stu, salt_stu, "知阶学者 01", "student", "active", now))

        conn.commit()
        print("Initialized default users: admin and student01")


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
        s.get("title", "💡 新建探索"),
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
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?;", (user_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


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
    if not active_sessions and not archived_sessions:
        default_sess = {
            "id": str(uuid.uuid4())[:8],
            "title": "💡 新建探索",
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
        session_data.get("title", "💡 新建探索"),
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
        session_data.get("created_at", now),
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
    cur.execute("UPDATE sessions SET is_archived = 1, updated_at = ? WHERE id = ? AND user_id = ?;",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), session_id, user_id))
    conn.commit()
    conn.close()


def restore_user_session(user_id: str, session_id: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE sessions SET is_archived = 0, updated_at = ? WHERE id = ? AND user_id = ?;",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), session_id, user_id))
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
