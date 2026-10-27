import os
import re
import json
import asyncio
import mimetypes
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv(override=True)

from core.presets import GOLDEN_PRESETS
from core.storage import (
    create_new_session_data,
    generate_session_title,
    to_chinese_num,
    build_tier_completion_report
)
from core.engine import (
    generate_solver_blueprint,
    stream_tutor_response,
    generate_diagnostic_report,
    evaluate_transfer_answer,
    is_transfer_eval_passed,
    generate_next_tier_variant,
    analyze_image_input
)
from core.latex_presets import LATEX_PRESETS_TREE
from core.guardrails import check_input_guardrail, check_output_refusal
from core.intent import classify_user_intent

# 导入 SQLite 持久化与认证安全模块
from core.db import (
    init_db,
    get_user_by_username,
    get_user_by_id,
    create_auth_token_session,
    get_user_from_token,
    delete_auth_token,
    update_user_password,
    log_audit_event,
    get_user_store,
    save_user_session,
    set_user_current_session,
    set_user_session_order,
    archive_user_session,
    restore_user_session,
    delete_archived_user_session,
    toggle_user_session_star
)
from core.auth import (
    verify_password,
    validate_password_strength,
    check_rate_limit,
    record_failed_attempt,
    reset_failed_attempts
)

app = FastAPI(title="CogniScaffold API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 确保 static 目录及 vendor 目录存在
os.makedirs("static", exist_ok=True)
os.makedirs("static/vendor", exist_ok=True)

# 注册 Web 字体 MIME 类型，避免浏览器将 woff/woff2 拦截
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")
mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("font/otf", ".otf")

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/vendor", StaticFiles(directory="static/vendor"), name="vendor")
app.mount("/cogni-scaffold/static", StaticFiles(directory="static"), name="static_subpath")


api_config = {
    "api_key": os.getenv("OPENAI_API_KEY", ""),
    "base_url": os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"),
    "model": os.getenv("MODEL_NAME", "deepseek-chat"),
    "temperature": 0.3
}


@app.on_event("startup")
async def startup_event():
    init_db()


def get_client_ip(request: Request) -> str:
    """提取客户端真实 IP，优先解析反向代理转发头"""
    forwarded = request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    """从 Bearer Header、Cookie 或 Query Param 解析已鉴权用户"""
    auth_header = request.headers.get("Authorization", "")
    token = ""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    if not token:
        token = request.cookies.get("cogni_token", "")
    if not token:
        token = request.query_params.get("token", "")
    if not token:
        return None
    return get_user_from_token(token)


def dispatch_variant_tier_data(session: dict, tier_num: int):
    diag = session.get("diagnostic_result") or {}
    tier_key = f"tier{tier_num}_variant"
    tier_data = diag.get(tier_key, {})
    
    raw_title = tier_data.get("title", f"第{to_chinese_num(tier_num)}关变式挑战")
    clean_title = re.sub(r'^(?:Tier\s*\d+\s*[:：]|第\s*\d+\s*关\s*[:：]|第\s*[一二三四五六七八九十]+\s*关\s*[:：])\s*', '', raw_title)
    full_title = f"第{to_chinese_num(tier_num)}关：{clean_title}"

    question = tier_data.get("question", diag.get("variant_question", "请分析约束反转后的系统动量或导数单调性。"))
    hint = tier_data.get("hint", diag.get("variant_hint", "注意边界与受力方向的矢量分解。"))

    def unescape_newlines(txt: str) -> str:
        if not isinstance(txt, str): return txt
        latex_n_cmds = {'neq', 'nabla', 'notin', 'nu', 'ne', 'natural', 'nparallel', 'neg', 'normalsize', 'newcommand', 'nolimits'}
        return re.sub(r'\\n([a-zA-Z]*)', lambda m: m.group(0) if m.group(1) in latex_n_cmds else f"\n{m.group(1)}", txt).replace('\\r', '')

    question = unescape_newlines(question)
    hint = unescape_newlines(hint)
    
    session["dialogue_history"].append({
        "role": "divider",
        "content": f"阶段 4 · {full_title}"
    })
    
    prompt_msg = (
        f"**📝 {full_title}**\n\n"
        f"{question}\n\n"
        f"> 💡 **考查要点与暗坑提示**：{hint}\n\n"
        f"**请在下方写出你的推导思路或结论（若觉得太简单可直接表明）：**"
    )
    session["dialogue_history"].append({
        "role": "assistant_variant",
        "content": prompt_msg
    })
    session["current_stage"] = 4
    session["current_variant_tier"] = tier_num
    return prompt_msg


def trigger_diagnosis_for_session(session: dict):
    session["diagnostic_result"] = generate_diagnostic_report(
        session["dialogue_history"],
        session["question"],
        api_config
    )
    session["current_stage"] = 4
    session["current_variant_tier"] = 1
    
    if session.get("title_stage", 0) < 2:
        new_title = generate_session_title(
            session["question"],
            session["dialogue_history"],
            session["diagnostic_result"],
            session.get("title", "会话"),
            title_stage=2,
            api_config=api_config
        )
        session["title"] = new_title
        session["title_stage"] = 2
    
    dispatch_variant_tier_data(session, 1)


# ============================================================
# 静态首页与基础 Bootstrap
# ============================================================

@app.get("/cogni-scaffold")
async def redirect_to_trailing_slash(request: Request):
    """强制重定向无末尾斜杠路径，避免移动端/平板浏览器将相对静态资源解析至根域名"""
    query_str = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(url=f"/cogni-scaffold/{query_str}", status_code=301)


@app.get("/", response_class=HTMLResponse)
@app.get("/cogni-scaffold/", response_class=HTMLResponse)
async def serve_index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/api/bootstrap")
@app.get("/cogni-scaffold/api/bootstrap")
async def get_bootstrap(request: Request):
    user = get_current_user(request)
    user_store = get_user_store(user["id"]) if user else None
    user_info = {
        "id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "role": user["role"]
    } if user else None

    return {
        "user": user_info,
        "store": user_store,
        "golden_presets": {
            k: {
                "title": v.get("title", k),
                "subject": v.get("subject", ""),
                "category": v.get("category", "stem"),
                "question": v.get("question", ""),
                "description": v.get("solver_blueprint", "")[:120]
            } for k, v in GOLDEN_PRESETS.items()
        },
        "latex_presets_tree": LATEX_PRESETS_TREE
    }





# ============================================================
# 认证体系 API: 登录 / 登出 / 状态 / 改密 (严防盗号与暴力破解)
# ============================================================

@app.post("/api/auth/login")
@app.post("/cogni-scaffold/api/auth/login")
async def auth_login(request: Request, data: dict):
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    client_ip = get_client_ip(request)

    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")

    # 1. 暴力破解防御：校验用户账号与 IP 是否锁定
    is_locked, remaining = check_rate_limit(f"user:{username}")
    if not is_locked:
        is_locked, remaining = check_rate_limit(f"ip:{client_ip}")
    if is_locked:
        log_audit_event(None, "login_locked_attempt", client_ip, f"username: {username}")
        return JSONResponse(
            status_code=429,
            content={"status": "error", "message": f"尝试次数过多，账号已临时锁定，请等待 {remaining} 秒后再试"}
        )

    # 2. 查询用户并校验密码（PBKDF2-HMAC 常量时间比对）
    user = get_user_by_username(username)
    if not user or user.get("status") != "active" or not verify_password(password, user["salt"], user["password_hash"]):
        is_now_locked, attempts, lock_sec = record_failed_attempt(f"user:{username}")
        record_failed_attempt(f"ip:{client_ip}")
        log_audit_event(user["id"] if user else None, "login_failed", client_ip, f"username: {username}, attempts: {attempts}")
        await asyncio.sleep(0.6)  # 渐进式延迟阻断暴力试凑
        if is_now_locked:
            return JSONResponse(
                status_code=429,
                content={"status": "error", "message": f"密码连续错误 5 次，账号已被临时锁定 15 分钟"}
            )
        rem = max(0, 5 - attempts)
        return JSONResponse(
            status_code=401,
            content={"status": "error", "message": f"用户名或密码错误（剩余尝试次数：{rem}）"}
        )

    # 3. 登录成功：清除失败频次，签发高熵会话令牌
    reset_failed_attempts(f"user:{username}")
    reset_failed_attempts(f"ip:{client_ip}")

    ua = request.headers.get("user-agent", "")
    token = create_auth_token_session(user["id"], ip=client_ip, user_agent=ua)
    log_audit_event(user["id"], "login_success", client_ip, "Success")

    user_info = {
        "id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "role": user["role"]
    }
    user_store = get_user_store(user["id"])

    response = JSONResponse(content={
        "status": "ok",
        "user": user_info,
        "token": token,
        "store": user_store
    })
    response.set_cookie(
        key="cogni_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=7 * 86400,
        path="/"
    )
    return response


@app.post("/api/auth/logout")
@app.post("/cogni-scaffold/api/auth/logout")
async def auth_logout(request: Request):
    token = request.cookies.get("cogni_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
    if token:
        delete_auth_token(token)
    response = JSONResponse(content={"status": "ok"})
    response.delete_cookie(key="cogni_token", path="/")
    return response


@app.get("/api/auth/me")
@app.get("/cogni-scaffold/api/auth/me")
async def auth_me(request: Request):
    user = get_current_user(request)
    if not user:
        return {"user": None}
    return {
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "role": user["role"]
        }
    }


@app.post("/api/auth/change_password")
@app.post("/cogni-scaffold/api/auth/change_password")
async def auth_change_password(request: Request, data: dict):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")

    old_password = data.get("old_password", "").strip()
    new_password = data.get("new_password", "").strip()
    client_ip = get_client_ip(request)

    db_user = get_user_by_id(user["id"])
    if not db_user or not verify_password(old_password, db_user["salt"], db_user["password_hash"]):
        log_audit_event(user["id"], "change_password_failed", client_ip, "Old password invalid")
        return JSONResponse(status_code=400, content={"status": "error", "message": "原密码不正确"})

    valid, err_msg = validate_password_strength(new_password)
    if not valid:
        return JSONResponse(status_code=400, content={"status": "error", "message": err_msg})

    update_user_password(user["id"], new_password)
    # 签发新会话令牌
    new_token = create_auth_token_session(user["id"], ip=client_ip, user_agent=request.headers.get("user-agent", ""))
    log_audit_event(user["id"], "change_password_success", client_ip, "Success")

    response = JSONResponse(content={"status": "ok", "message": "密码修改成功", "token": new_token})
    response.set_cookie(
        key="cogni_token",
        value=new_token,
        httponly=True,
        samesite="lax",
        max_age=7 * 86400,
        path="/"
    )
    return response


# ============================================================
# 会话管理 API (多用户严格隔离与鉴权门禁)
# ============================================================

@app.post("/api/sessions/create")
@app.post("/cogni-scaffold/api/sessions/create")
async def create_session(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="问答功能需先登录账号")

    user_id = user["id"]
    store = get_user_store(user_id)
    active = store.setdefault("active_sessions", {})

    # 仅允许存在一个未初始化的空白新建会话
    for s_id, s in active.items():
        if not s.get("is_initialized", False) and not s.get("question", "").strip():
            set_user_current_session(user_id, s_id)
            store["current_session_id"] = s_id
            return {"status": "ok", "store": store, "already_exists": True}

    new_s = create_new_session_data(is_initialized=False, store=store)
    save_user_session(user_id, new_s)
    set_user_current_session(user_id, new_s["id"])
    return {"status": "ok", "store": get_user_store(user_id)}


@app.post("/api/sessions/switch")
@app.post("/cogni-scaffold/api/sessions/switch")
async def switch_session(request: Request, data: dict):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")

    s_id = data.get("session_id")
    user_id = user["id"]
    store = get_user_store(user_id)
    if s_id in store.get("active_sessions", {}):
        set_user_current_session(user_id, s_id)
        store["current_session_id"] = s_id
        return {"status": "ok", "store": store}
    raise HTTPException(status_code=404, detail="Session not found")


@app.get("/api/sessions/{session_id}")
@app.get("/cogni-scaffold/api/sessions/{session_id}")
async def get_single_session(session_id: str, request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")

    user_id = user["id"]
    store = get_user_store(user_id)
    sess = store.get("active_sessions", {}).get(session_id) or store.get("archived_sessions", {}).get(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"status": "ok", "session": sess}


@app.post("/api/sessions/reorder")
@app.post("/cogni-scaffold/api/sessions/reorder")
async def reorder_sessions(request: Request, data: dict):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")

    user_id = user["id"]
    new_order = data.get("order", [])
    if new_order and isinstance(new_order, list):
        set_user_session_order(user_id, new_order)
    return {"status": "ok", "store": get_user_store(user_id)}


@app.post("/api/sessions/close")
@app.post("/cogni-scaffold/api/sessions/close")
async def close_session(request: Request, data: dict):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")

    user_id = user["id"]
    s_id = data.get("session_id")
    archive_user_session(user_id, s_id)
    return {"status": "ok", "store": get_user_store(user_id)}


@app.post("/api/sessions/toggle_star")
@app.post("/cogni-scaffold/api/sessions/toggle_star")
async def toggle_star(request: Request, data: dict):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")

    user_id = user["id"]
    s_id = data.get("session_id")
    is_starred = toggle_user_session_star(user_id, s_id)
    return {"status": "ok", "is_starred": is_starred, "store": get_user_store(user_id)}


@app.post("/api/sessions/restore")
@app.post("/cogni-scaffold/api/sessions/restore")
async def restore_session(request: Request, data: dict):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")

    user_id = user["id"]
    s_id = data.get("session_id")
    restore_user_session(user_id, s_id)
    set_user_current_session(user_id, s_id)
    return {"status": "ok", "store": get_user_store(user_id)}


@app.post("/api/sessions/delete_archived")
@app.post("/cogni-scaffold/api/sessions/delete_archived")
async def delete_archived(request: Request, data: dict):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")

    user_id = user["id"]
    s_id = data.get("session_id")
    delete_archived_user_session(user_id, s_id)
    return {"status": "ok", "store": get_user_store(user_id)}


@app.post("/api/theme")
@app.post("/cogni-scaffold/api/theme")
async def set_theme(request: Request, data: dict):
    theme = data.get("theme", "dark")
    user = get_current_user(request)
    if user:
        from core.db import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
        INSERT INTO user_preferences (user_id, theme) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET theme = excluded.theme;
        """, (user["id"], theme))
        conn.commit()
        conn.close()
    return {"status": "ok", "theme": theme}


@app.post("/api/sessions/init_question")
@app.post("/cogni-scaffold/api/sessions/init_question")
async def init_question(request: Request, data: dict):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="问答功能需先登录账号")

    user_id = user["id"]
    s_id = data.get("session_id")
    question_text = data.get("question", "").strip()
    preset_key = data.get("preset_key")
    
    store = get_user_store(user_id)
    active = store.get("active_sessions", {})
    sess = active.get(s_id)
    if not sess:
        sess = create_new_session_data(is_initialized=False, store=store)
        active[sess["id"]] = sess
        s_id = sess["id"]

    if preset_key and preset_key in GOLDEN_PRESETS:
        preset = GOLDEN_PRESETS[preset_key]
        sess["title"] = preset.get("title", "🧩 探索·思维引导突破")
        sess["is_initialized"] = True
        sess["title_stage"] = 1
        sess["question"] = preset["question"]
        sess["solver_blueprint"] = preset["solver_blueprint"]
        sess["dialogue_history"] = [
            {"role": "user", "content": preset["initial_student_input"]},
            {"role": "assistant", "content": preset["offline_simulation"][0]["tutor_response"]}
        ]
        sess["tutor_turns"] = 1
        sess["current_stage"] = 2
        sess["diagnostic_result"] = None
        sess["transfer_eval_result"] = None
        sess["current_variant_tier"] = 1
    else:
        if not question_text:
            raise HTTPException(status_code=400, detail="Question cannot be empty")
        sess["question"] = question_text
        sess["is_initialized"] = True
        sess["title_stage"] = 1
        sess["dialogue_history"] = [
            {"role": "assistant", "content": "我已经审视了这道题目。作为你的苏格拉底认知导师，我不会直接给出最终答案。请告诉我，面对这道题目，你的第一直觉是什么？你注意到的核心矛盾、关键已知线索或分析切入点是什么？"}
        ]
        sess["tutor_turns"] = 0
        sess["current_stage"] = 1
        sess["diagnostic_result"] = None
        sess["transfer_eval_result"] = None
        sess["current_variant_tier"] = 1
        sess["title"] = generate_session_title(
            question=question_text,
            dialogue_history=[],
            diagnostic_result=None,
            current_title=sess.get("title", "会话"),
            title_stage=1,
            api_config=api_config
        )
        sess["solver_blueprint"] = generate_solver_blueprint(question_text, api_config)

    save_user_session(user_id, sess)
    set_user_current_session(user_id, s_id)
    return {"status": "ok", "store": get_user_store(user_id)}


@app.post("/api/sessions/reset")
@app.post("/cogni-scaffold/api/sessions/reset")
async def reset_session(request: Request, data: dict):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")

    user_id = user["id"]
    s_id = data.get("session_id")
    store = get_user_store(user_id)
    sess = store.get("active_sessions", {}).get(s_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    sess["dialogue_history"] = [
        {"role": "assistant", "content": "我已经审视了这道题目。作为你的苏格拉底认知导师，我不会直接给出最终答案。请告诉我，面对这道题目，你的第一直觉是什么？你注意到的核心矛盾、关键已知线索或分析切入点是什么？"}
    ]
    sess["tutor_turns"] = 0
    sess["current_stage"] = 1
    sess["diagnostic_result"] = None
    sess["transfer_eval_result"] = None
    sess["current_variant_tier"] = 1
    save_user_session(user_id, sess)
    return {"status": "ok", "store": get_user_store(user_id)}


_session_tier_locks: Dict[str, asyncio.Lock] = {}

def get_session_lock(session_id: str) -> asyncio.Lock:
    if session_id not in _session_tier_locks:
        _session_tier_locks[session_id] = asyncio.Lock()
    return _session_tier_locks[session_id]


@app.post("/api/sessions/verify")
@app.post("/cogni-scaffold/api/sessions/verify")
async def verify_session(request: Request, data: dict):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")

    user_id = user["id"]
    s_id = data.get("session_id")
    store = get_user_store(user_id)
    sess = store.get("active_sessions", {}).get(s_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
        
    lock = get_session_lock(s_id)
    if lock.locked():
        return {"status": "ok", "store": store}

    async with lock:
        store = get_user_store(user_id)
        sess = store.get("active_sessions", {}).get(s_id)
        if sess.get("diagnostic_result"):
            return {"status": "ok", "store": store}
        trigger_diagnosis_for_session(sess)
        save_user_session(user_id, sess)
        return {"status": "ok", "store": get_user_store(user_id)}


@app.post("/api/sessions/next_tier")
@app.post("/cogni-scaffold/api/sessions/next_tier")
async def next_tier(request: Request, data: dict):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")

    user_id = user["id"]
    s_id = data.get("session_id")
    store = get_user_store(user_id)
    sess = store.get("active_sessions", {}).get(s_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
        
    lock = get_session_lock(s_id)
    if lock.locked():
        return {"status": "ok", "store": store}

    async with lock:
        store = get_user_store(user_id)
        sess = store.get("active_sessions", {}).get(s_id)
        diag = sess.get("diagnostic_result") or {}
        existing_tiers = [
            int(k.replace("tier", "").replace("_variant", ""))
            for k in diag.keys()
            if k.startswith("tier") and k.endswith("_variant") and k.replace("tier", "").replace("_variant", "").isdigit()
        ]
        max_t = max(existing_tiers, default=3)
        curr_tier = sess.get("current_variant_tier", 1)

        if curr_tier <= max_t:
            return {"status": "ok", "store": store}

        next_t = max_t + 1
        new_variant = generate_next_tier_variant(
            sess.get("question", ""),
            sess.get("dialogue_history", []),
            diag,
            next_t,
            api_config
        )
        diag[f"tier{next_t}_variant"] = new_variant
        sess["diagnostic_result"] = diag
        sess["current_variant_tier"] = next_t
        sess["current_stage"] = 4
        dispatch_variant_tier_data(sess, next_t)
        save_user_session(user_id, sess)
        return {"status": "ok", "store": get_user_store(user_id)}


@app.post("/api/sessions/upload_image")
@app.post("/cogni-scaffold/api/sessions/upload_image")
async def upload_image(
    request: Request,
    image: UploadFile = File(...),
    mode: str = Form("question"),
    question_context: str = Form("")
):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="问答功能需先登录账号")

    try:
        content = await image.read()
        recognized_text = analyze_image_input(content, mode, question_context, api_config)
        return {"status": "ok", "text": recognized_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sessions/{session_id}/chat/stream")
@app.get("/cogni-scaffold/api/sessions/{session_id}/chat/stream")
async def chat_stream(session_id: str, student_text: str, request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="问答功能需先登录账号")

    user_id = user["id"]
    store = get_user_store(user_id)
    sess = store.get("active_sessions", {}).get(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    student_text = student_text.strip()
    if not student_text:
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    async def event_generator():
        nonlocal user_id, sess
        try:
            # 1. 记录学生输入
            sess["dialogue_history"].append({"role": "user", "content": student_text})

            # 【断路器 1：前置安全与合规检测】
            is_blocked, refusal_text = check_input_guardrail(student_text)
            if is_blocked:
                chunk_size = 12
                for i in range(0, len(refusal_text), chunk_size):
                    chunk = refusal_text[i:i+chunk_size]
                    yield f"data: {json.dumps({'type': 'chunk', 'content': chunk, 'role': 'assistant'}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.01)

                sess["dialogue_history"].append({"role": "assistant", "content": refusal_text})
                save_user_session(user_id, sess)
                yield f"data: {json.dumps({'type': 'done', 'session': sess, 'store': get_user_store(user_id)}, ensure_ascii=False)}\n\n"
                return

            # 【意图与早退路由检测】
            intent_type, intent_guidance = classify_user_intent(student_text, sess.get("question", ""))
            
            if intent_type == "PROFANITY":
                chunk_size = 12
                for i in range(0, len(intent_guidance), chunk_size):
                    chunk = intent_guidance[i:i+chunk_size]
                    yield f"data: {json.dumps({'type': 'chunk', 'content': chunk, 'role': 'assistant'}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.01)

                sess["dialogue_history"].append({"role": "assistant", "content": intent_guidance})
                save_user_session(user_id, sess)
                yield f"data: {json.dumps({'type': 'done', 'session': sess, 'store': get_user_store(user_id)}, ensure_ascii=False)}\n\n"
                return

            elif intent_type in ["GIVE_UP", "OFF_TOPIC", "DEMAND_ANSWER", "LOW_INFO"]:
                chunk_size = 12
                for i in range(0, len(intent_guidance), chunk_size):
                    chunk = intent_guidance[i:i+chunk_size]
                    yield f"data: {json.dumps({'type': 'chunk', 'content': chunk, 'role': 'assistant'}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.01)

                sess["dialogue_history"].append({"role": "assistant", "content": intent_guidance})
                sess["tutor_turns"] += 1
                save_user_session(user_id, sess)
                yield f"data: {json.dumps({'type': 'done', 'session': sess, 'store': get_user_store(user_id)}, ensure_ascii=False)}\n\n"
                return

            # 阶段 4：变式迁移挑战应答
            if sess.get("current_stage") == 4:
                diag = sess.get("diagnostic_result") or {}
                defined_tiers = [
                    int(k.replace("tier", "").replace("_variant", ""))
                    for k in diag.keys()
                    if k.startswith("tier") and k.endswith("_variant") and k.replace("tier", "").replace("_variant", "").isdigit()
                ]
                max_defined = max(defined_tiers, default=3)
                curr_tier = sess.get("current_variant_tier", 1)

                if curr_tier > max_defined:
                    next_t = max_defined + 1
                    new_variant = generate_next_tier_variant(
                        sess.get("question", ""),
                        sess.get("dialogue_history", []),
                        diag,
                        next_t,
                        api_config
                    )
                    diag[f"tier{next_t}_variant"] = new_variant
                    sess["diagnostic_result"] = diag
                    sess["current_variant_tier"] = next_t
                    sess["current_stage"] = 4
                    prompt_msg = dispatch_variant_tier_data(sess, next_t)
                    save_user_session(user_id, sess)

                    chunk_size = 12
                    for i in range(0, len(prompt_msg), chunk_size):
                        chunk = prompt_msg[i:i+chunk_size]
                        yield f"data: {json.dumps({'type': 'chunk', 'content': chunk, 'role': 'assistant_variant'}, ensure_ascii=False)}\n\n"
                        await asyncio.sleep(0.01)

                    yield f"data: {json.dumps({'type': 'done', 'session': sess, 'store': get_user_store(user_id)}, ensure_ascii=False)}\n\n"
                    return

                tier_data = diag.get(f"tier{curr_tier}_variant", {})
                var_q = tier_data.get("question", "变式题")
                var_h = tier_data.get("hint", "")

                eval_text = evaluate_transfer_answer(var_q, var_h, student_text, api_config)
                
                chunk_size = 8
                for i in range(0, len(eval_text), chunk_size):
                    chunk = eval_text[i:i+chunk_size]
                    yield f"data: {json.dumps({'type': 'chunk', 'content': chunk, 'role': 'assistant_variant'}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.02)

                sess["dialogue_history"].append({"role": "assistant_variant", "content": eval_text})
                sess["transfer_eval_result"] = eval_text

                if is_transfer_eval_passed(eval_text):
                    if curr_tier < max_defined:
                        next_t = curr_tier + 1
                        sess["current_variant_tier"] = next_t
                        dispatch_variant_tier_data(sess, next_t)
                    else:
                        sess["current_variant_tier"] = max_defined + 1

                save_user_session(user_id, sess)
                yield f"data: {json.dumps({'type': 'done', 'session': sess, 'store': get_user_store(user_id)}, ensure_ascii=False)}\n\n"

            else:
                # 阶段 1~3：启发式引导
                full_response = ""
                temp_history = list(sess["dialogue_history"])
                
                for chunk in stream_tutor_response(temp_history, sess.get("solver_blueprint", ""), api_config):
                        full_response += chunk
                        clean_chunk = chunk.replace("[TRIGGER_DIAGNOSIS]", "")
                        if clean_chunk:
                            yield f"data: {json.dumps({'type': 'chunk', 'content': clean_chunk, 'role': 'assistant'}, ensure_ascii=False)}\n\n"
                        await asyncio.sleep(0.01)

                clean_full = full_response.replace("[TRIGGER_DIAGNOSIS]", "").strip()
                sess["dialogue_history"].append({"role": "assistant", "content": clean_full})
                sess["tutor_turns"] += 1

                if sess.get("title_stage", 0) == 0:
                    new_title = generate_session_title(
                        sess["question"],
                        sess["dialogue_history"],
                        None,
                        sess.get("title", ""),
                        title_stage=1,
                        api_config=api_config
                    )
                    sess["title"] = new_title
                    sess["title_stage"] = 1

                is_refusal = check_output_refusal(clean_full)

                can_trigger_diagnosis = (
                    not is_refusal
                    and (intent_type not in ["LOW_INFO", "DEMAND_ANSWER"] and sess.get("tutor_turns", 0) >= 2)
                    and "[TRIGGER_DIAGNOSIS]" in full_response
                )

                if can_trigger_diagnosis:
                    trigger_diagnosis_for_session(sess)

                save_user_session(user_id, sess)
                yield f"data: {json.dumps({'type': 'done', 'session': sess, 'store': get_user_store(user_id)}, ensure_ascii=False)}\n\n"

        except Exception as err:
            err_msg = f"⚠️ 连接处理异常：{str(err)}。请点击重试。"
            yield f"data: {json.dumps({'type': 'chunk', 'content': err_msg, 'role': 'assistant'}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'session': sess, 'store': get_user_store(user_id)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
