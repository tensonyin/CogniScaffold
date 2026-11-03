import os
import re
import json
import asyncio
import threading
import ipaddress
import mimetypes
import weakref
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, RedirectResponse, Response
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
from core.guardrails import check_input_guardrail, check_output_refusal, get_matched_guardrail_pattern
from core.intent import classify_user_intent

# 导入 SQLite 持久化与认证安全模块
from core.db import (
    get_user_custom_api_key,
    set_user_custom_api_key,
    clear_user_custom_api_key,
    get_all_class_names,
    get_class_analytics,
    soft_delete_user,
    restore_user,
    purge_user,
    soft_delete_session,
    restore_session_from_trash,
    purge_session,
    get_trash_items,
    batch_soft_delete_users,
    batch_restore_users,
    batch_purge_users,
    batch_soft_delete_sessions,
    batch_restore_sessions,
    batch_purge_sessions,
    batch_reset_user_passwords,
    batch_set_user_token_limits,
    batch_set_user_status,
    batch_reset_user_today_usage,
    TZ_EAST8,
    now_east8,
    set_user_security_and_password,
    get_user_security_question,
    verify_security_answer,
    create_password_reset_token,
    verify_password_reset_token,
    now_east8_str,
    today_east8_str,
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
    record_question_submission,
    set_user_current_session,
    set_user_session_order,
    archive_user_session,
    restore_user_session,
    delete_archived_user_session,
    toggle_user_session_star,
    get_system_config,
    get_all_system_configs,
    set_system_config,
    record_token_usage,
    get_token_stats_overview,
    record_guardrail_log,
    get_guardrail_logs,
    check_user_ban_status,
    ban_user,
    unban_user,
    reset_user_password_by_admin,
    set_user_custom_quota,
    reset_user_today_questions,
    batch_create_users,
    get_user_effective_limits,
    get_user_today_questions_count,
    get_user_today_tokens,
    check_can_create_question,
    check_can_continue_chat,
    check_can_consume_tokens,
    get_admin_overview,
    get_admin_users_list,
    get_admin_sessions_list,
    get_admin_session_detail,
    submit_user_feedback,
    get_user_feedbacks,
    get_admin_feedbacks,
    reply_user_feedback
)
from core.auth import (
    verify_password,
    validate_password_strength,
    check_rate_limit,
    check_action_rate,
    record_failed_attempt,
    reset_failed_attempts,
    generate_salt
)

app = FastAPI(title="CogniScaffold API")

# CORS：仅允许本地开发端口与本站正式域名，禁止任意子域（避免子域被接管后携带 Cookie 读取接口）
CORS_ORIGIN_REGEX = os.getenv(
    "CORS_ORIGIN_REGEX",
    r"^(https?://(localhost|127\.0\.0\.1)(:\d+)?|https?://(www\.)?buildfuture\.tech)$"
)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_REQUEST_BODY = int(os.getenv("MAX_REQUEST_BODY", str(12 * 1024 * 1024)))  # 12 MB（含 multipart 边界开销）
MAX_ACTIVE_SESSIONS = int(os.getenv("MAX_ACTIVE_SESSIONS", "100"))
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"}


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_REQUEST_BODY:
                return JSONResponse(status_code=413, content={"detail": "请求体过大，最大允许 12MB"})
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "非法的 Content-Length"})

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
    # API 响应包含用户隐私与额度信息，禁止浏览器/中间代理缓存
    if request.url.path.startswith("/api/") or "/api/" in request.url.path:
        if "no-cache" not in response.headers.get("Cache-Control", ""):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    # 仅在 HTTPS 访问时下发 HSTS，避免本地 HTTP 调试被强制跳转
    is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    if is_https:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

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

def get_effective_api_config(user_id: str) -> Tuple[Dict[str, Any], bool]:
    """
    获取当前用户实际生效的 API 配置。
    优先使用用户导入的专属 DeepSeek API Key（固定官方 base_url 和 deepseek-chat），返回 (cfg, True)。
    若未导入则返回学校全局分配的 api_config，返回 (cfg, False)。
    """
    custom_key = get_user_custom_api_key(user_id)
    if custom_key and custom_key.strip().startswith("sk-"):
        cfg = dict(api_config)
        cfg["api_key"] = custom_key.strip()
        cfg["base_url"] = "https://api.deepseek.com"
        cfg["model"] = "deepseek-chat"
        return cfg, True
    return api_config, False



async def _warmup_deepseek_connection():
    """
    后台静默预热 DeepSeek API 连通性：
    解决校园内网/防火墙/DPI冷启动与首次 TLS 握手断开 (unexpected eof while reading) 问题。
    在服务启动时自动完成首连握手，并定期维持底层 HTTP 连接池与防火墙 NAT 会话。
    """
    api_key = api_config.get("api_key", "")
    if not api_key or api_key == "sk-dummy":
        return
    base_url = api_config.get("base_url", "https://api.deepseek.com")

    # 稍微等待 1.5 秒，确保主事件循环初始化完毕
    await asyncio.sleep(1.5)

    # 启动时执行快速预热握手（免费 models.list()，0 Token 消耗）
    for attempt in range(3):
        try:
            from core.engine import get_openai_client
            client = get_openai_client(api_key, base_url)
            await asyncio.to_thread(client.models.list)
            print("[LLM Warmup] ✔ DeepSeek API 连通性预热成功，内网连接池与防火墙状态已就绪！", flush=True)
            break
        except Exception as e:
            print(f"[LLM Warmup] 首连预热第 {attempt + 1}/3 次握手重试: {type(e).__name__}: {e}", flush=True)
            await asyncio.sleep(1.0)

    # 后台持续心跳：每 5 分钟向 DeepSeek 发送一次零 Token 消耗的轻量探测，防止校园网防火墙丢弃闲置 NAT 映射
    while True:
        try:
            await asyncio.sleep(300)
            from core.engine import get_openai_client
            client = get_openai_client(api_key, base_url)
            await asyncio.to_thread(client.models.list)
        except Exception:
            pass


@app.on_event("startup")
async def startup_event():
    init_db()
    asyncio.create_task(_warmup_deepseek_connection())


def _load_trusted_proxies() -> List[Any]:
    """解析可信反向代理网段（默认仅回环与私有网段）"""
    raw = os.getenv(
        "TRUSTED_PROXY_IPS",
        "127.0.0.1/32,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16",
    )
    networks: List[Any] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            networks.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            continue
    return networks


TRUSTED_PROXY_NETS = _load_trusted_proxies()
TRUST_CF_CONNECTING_IP = os.getenv("TRUST_CF_CONNECTING_IP", "0") == "1"


def _is_trusted_proxy(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in net for net in TRUSTED_PROXY_NETS)


def get_client_ip(request: Request) -> str:
    """
    提取客户端真实 IP。
    仅当直连对端是可信反向代理（Nginx/Docker 网关等）时才采信转发头，
    并从右向左跳过可信代理，防止客户端伪造 X-Forwarded-For 绕过登录限流。
    """
    peer = request.client.host if request.client else "127.0.0.1"
    if not _is_trusted_proxy(peer):
        return peer

    if TRUST_CF_CONNECTING_IP:
        cf_ip = (request.headers.get("CF-Connecting-IP") or "").strip()
        if cf_ip:
            try:
                return str(ipaddress.ip_address(cf_ip))
            except ValueError:
                pass

    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        chain = [item.strip() for item in forwarded.split(",") if item.strip()]
        chain.append(peer)
        for candidate in reversed(chain):
            if not _is_trusted_proxy(candidate):
                try:
                    return str(ipaddress.ip_address(candidate))
                except ValueError:
                    continue
        return chain[0]
    return peer


def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    """从 HttpOnly Cookie 或 Bearer Header 解析已鉴权用户（不再接受 URL 查询参数，避免 Token 泄漏到日志与 Referer）"""
    token = request.cookies.get("cogni_session") or request.cookies.get("cogni_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
    if not token:
        return None
    return get_user_from_token(token)


def require_admin(request: Request) -> Dict[str, Any]:
    """校验当前请求是否为具有管理员身份的用户，否则直接阻断抛出 403"""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录管理员账号")
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="无权访问管理员后台功能")
    return user


def dispatch_variant_tier_data(session: dict, tier_num: int):
    diag = session.get("diagnostic_result") or {}
    if not isinstance(diag, dict):
        diag = {}
    tier_key = f"tier{tier_num}_variant"
    tier_data = diag.get(tier_key, {})
    if not isinstance(tier_data, dict):
        tier_data = {}

    raw_title = str(tier_data.get("title") or f"第{to_chinese_num(tier_num)}关变式挑战")
    clean_title = re.sub(r'^(?:Tier\s*\d+\s*[:：]|第\s*\d+\s*关\s*[:：]|第\s*[一二三四五六七八九十]+\s*关\s*[:：])\s*', '', raw_title)
    full_title = f"第{to_chinese_num(tier_num)}关：{clean_title}"

    question = tier_data.get("question") or diag.get("variant_question") or "请分析约束反转后的系统动量或导数单调性。"
    hint = tier_data.get("hint") or diag.get("variant_hint") or "注意边界与受力方向的矢量分解。"

    def unescape_newlines(txt: str) -> str:
        if not isinstance(txt, str): return str(txt)
        latex_n_cmds = {'neq', 'nabla', 'notin', 'nu', 'ne', 'natural', 'nparallel', 'neg', 'normalsize', 'newcommand', 'nolimits'}
        return re.sub(r'\\n([a-zA-Z]*)', lambda m: m.group(0) if m.group(1) in latex_n_cmds else f"\n{m.group(1)}", txt).replace('\\r', '')

    question = unescape_newlines(question)
    hint = unescape_newlines(hint)

    history = session.setdefault("dialogue_history", [])
    history.append({
        "role": "divider",
        "content": f"阶段 4 · {full_title}"
    })

    prompt_msg = (
        f"**📝 {full_title}**\n\n"
        f"{question}\n\n"
        f"> 💡 **考查要点与暗坑提示**：{hint}\n\n"
        f"**请在下方写出你的推导思路或结论（若觉得太简单可直接表明）：**"
    )
    history.append({
        "role": "assistant_variant",
        "content": prompt_msg
    })
    session["current_stage"] = 4
    session["current_variant_tier"] = tier_num
    return prompt_msg


def trigger_diagnosis_for_session(session: dict, user_id: Optional[str] = None):
    s_id = session.get("id")
    result = generate_diagnostic_report(
        session["dialogue_history"],
        session["question"],
        api_config,
        user_id=user_id,
        session_id=s_id
    )
    # 防御大模型返回非对象 JSON，避免后续 .get() 崩溃并污染会话存档
    session["diagnostic_result"] = result if isinstance(result, dict) else None
    if not session["diagnostic_result"]:
        return None
    session["current_stage"] = 4
    session["current_variant_tier"] = 1
    
    if session.get("title_stage", 0) < 2:
        new_title = generate_session_title(
            session["question"],
            session["dialogue_history"],
            session["diagnostic_result"],
            session.get("title", "会话"),
            title_stage=2,
            api_config=api_config,
            user_id=user_id,
            session_id=s_id
        )
        session["title"] = new_title
        session["title_stage"] = 2
    
    dispatch_variant_tier_data(session, 1)
    return True


def build_user_response_info(user: dict) -> dict:
    """构建统一的用户概要与额度信息结构"""
    is_admin = (user.get("role") == "admin")
    can_create, cur_q, max_q = check_can_create_question(user["id"], is_admin=is_admin)
    _, max_turns, max_tokens = get_user_effective_limits(user["id"])
    can_tokens, used_tokens, limit_tokens = check_can_consume_tokens(user["id"], is_admin=is_admin)
    remaining_tokens = max(0, limit_tokens - used_tokens) if not is_admin else 99999999
    remaining_pct = round((remaining_tokens / limit_tokens) * 100) if (not is_admin and limit_tokens > 0) else 100
    remaining_pct = max(0, min(100, remaining_pct))

    has_custom = bool(user.get("custom_api_key_enc")) or bool(get_user_custom_api_key(user["id"]))
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "class_name": user.get("class_name", ""),
        "role": user["role"],
        "has_custom_key": has_custom,
        "quota": {
            "can_create": can_create and can_tokens,
            "can_chat": can_tokens,
            "today_questions": 0 if is_admin else cur_q,
            "daily_limit": 99999 if is_admin else max_q,
            "turn_limit": 99999 if is_admin else max_turns,
            "today_tokens": 0 if is_admin else used_tokens,
            "daily_tokens": 99999999 if is_admin else limit_tokens,
            "daily_token_limit": 99999999 if is_admin else limit_tokens,
            "remaining_tokens": remaining_tokens,
            "token_remaining_pct": remaining_pct,
            "is_admin": is_admin
        }
    }


def get_user_quota_info(user_id: str, is_admin: Optional[bool] = None) -> Dict[str, Any]:
    """实时计算获取用户的最新额度与已消耗 Token 数据，自动判定管理员与防范未定义异常"""
    user = get_user_by_id(user_id)
    if not user:
        user = {"id": user_id, "role": "admin" if is_admin else "student"}
    if is_admin is None:
        is_admin = (user.get("role") == "admin")
    return build_user_response_info(user)["quota"]


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
    user_info = build_user_response_info(user) if user else None

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
    if len(username) > 64 or len(password) > 256:
        raise HTTPException(status_code=400, detail="用户名或密码长度超出限制")

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

    # 2. 查询用户并校验封禁状态与密码（PBKDF2-HMAC 常量时间比对）
    user = get_user_by_username(username)
    if user:
        is_banned, ban_reason, banned_until = check_user_ban_status(user["id"])
        if is_banned:
            log_audit_event(user["id"], "login_banned_attempt", client_ip, f"banned_until: {banned_until}")
            until_desc = "永久封禁" if banned_until == "permanent" else f"封禁至 {banned_until}"
            return JSONResponse(
                status_code=403,
                content={"status": "error", "message": f"该账号已被限制登录（{until_desc}）。封禁原因：{ban_reason or '违反使用规范'}"}
            )

    if not user or user.get("status") != "active" or not verify_password(password, user["salt"], user["password_hash"]):
        is_now_locked, attempts, _ = record_failed_attempt(f"user:{username}")
        # IP 维度阈值放宽，避免少数错误输入锁死整个校园 NAT / 代理出口
        record_failed_attempt(f"ip:{client_ip}", max_attempts=30)
        log_audit_event(user["id"] if user else None, "login_failed", client_ip, f"username: {username}, attempts: {attempts}")
        await asyncio.sleep(0.6)  # 渐进式延迟阻断暴力试凑
        if is_now_locked:
            return JSONResponse(
                status_code=429,
                content={"status": "error", "message": "密码连续错误 5 次，账号已被临时锁定 15 分钟"}
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

    must_setup_security = bool(user.get("must_change_password") or not user.get("security_question"))
    user_info = build_user_response_info(user)
    user_info["must_setup_security"] = must_setup_security
    user_store = get_user_store(user["id"])

    response = JSONResponse(content={
        "status": "ok",
        "user": user_info,
        "token": token,
        "store": user_store,
        "must_setup_security": must_setup_security
    })
    is_https = (request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https")
    for cookie_key in ["cogni_session", "cogni_token"]:
        response.set_cookie(
            key=cookie_key,
            value=token,
            httponly=True,
            secure=is_https,
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
    for cookie_key in ["cogni_session", "cogni_token"]:
        response.delete_cookie(key=cookie_key, path="/")
    return response


@app.get("/api/auth/me")
@app.get("/cogni-scaffold/api/auth/me")
async def auth_me(request: Request):
    user = get_current_user(request)
    if not user:
        return {"user": None}
    return {"user": build_user_response_info(user)}


@app.post("/api/auth/change_password")
@app.post("/cogni-scaffold/api/auth/change_password")
async def auth_change_password(request: Request, data: dict):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")

    old_password = data.get("old_password", "").strip()
    new_password = data.get("new_password", "").strip()
    client_ip = get_client_ip(request)

    if len(old_password) > 256 or len(new_password) > 256:
        return JSONResponse(status_code=400, content={"status": "error", "message": "密码长度超出限制"})

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
    is_https = (request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https")
    for cookie_key in ["cogni_session", "cogni_token"]:
        response.set_cookie(
            key=cookie_key,
            value=new_token,
            httponly=True,
            secure=is_https,
            samesite="lax",
            max_age=7 * 86400,
            path="/"
        )
    return response


@app.post("/api/auth/setup_security_and_password")
@app.post("/cogni-scaffold/api/auth/setup_security_and_password")
async def setup_security_and_password(request: Request, data: dict):
    """首次登录强制设置密保问题并修改新密码"""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")

    new_password = data.get("new_password", "").strip()
    security_question = data.get("security_question", "").strip()
    security_answer = data.get("security_answer", "").strip()

    if not new_password or not security_question or not security_answer:
        raise HTTPException(status_code=400, detail="新密码、密保问题及密保答案均不能为空")
    if len(new_password) > 256 or len(security_question) > 200 or len(security_answer) > 200:
        raise HTTPException(status_code=400, detail="密保问题、答案或密码长度超出限制")
    if len(security_answer) < 2:
        raise HTTPException(status_code=400, detail="密保答案至少需要 2 个字符")

    if new_password in ["Student@2026!", "Admin@Cogni2026!", "123456", "password"]:
        raise HTTPException(status_code=400, detail="禁止继续使用系统默认初始密码，请设置强密码")

    valid, err_msg = validate_password_strength(new_password)
    if not valid:
        raise HTTPException(status_code=400, detail=err_msg)

    set_user_security_and_password(user["id"], new_password, security_question, security_answer)
    log_audit_event(user["id"], "setup_security_success", get_client_ip(request), "Success")
    return {"status": "ok", "message": "密保问题与新密码设置成功"}


@app.get("/api/auth/security_question")
@app.get("/cogni-scaffold/api/auth/security_question")
async def get_security_question(request: Request, username: str = ""):
    """获取用户预设的密保问题（按 IP 限流，降低账号枚举风险）"""
    client_ip = get_client_ip(request)
    allowed, retry_after = check_action_rate(f"secq_lookup:{client_ip}", max_events=30, window_seconds=600)
    if not allowed:
        raise HTTPException(status_code=429, detail=f"查询过于频繁，请 {retry_after} 秒后再试")

    uname = username.strip()
    if not uname or len(uname) > 64:
        raise HTTPException(status_code=400, detail="请输入有效的账号用户名")

    user = get_user_by_username(uname)
    question = get_user_security_question(uname) if user else None
    if not question:
        # 统一文案，避免通过 404/400 差异枚举系统内已存在的账号
        raise HTTPException(status_code=400, detail="账号不存在或尚未设置密保问题，请联系任课教师或管理员协助重置密码")

    return {"status": "ok", "question": question}


@app.post("/api/auth/verify_security_answer")
@app.post("/cogni-scaffold/api/auth/verify_security_answer")
async def verify_sec_answer(request: Request, data: dict):
    """忘记密码第一步：验证密保答案并签发重置令牌（连续失败将临时锁定）"""
    uname = data.get("username", "").strip()
    answer = data.get("security_answer", "").strip()
    client_ip = get_client_ip(request)

    if not uname or not answer:
        raise HTTPException(status_code=400, detail="用户名和密保答案均不能为空")
    if len(uname) > 64 or len(answer) > 200:
        raise HTTPException(status_code=400, detail="用户名或密保答案长度超出限制")

    user_lock_key = f"secq_user:{uname}"
    ip_lock_key = f"secq_ip:{client_ip}"
    is_locked, remaining = check_rate_limit(user_lock_key)
    if not is_locked:
        is_locked, remaining = check_rate_limit(ip_lock_key)
    if is_locked:
        log_audit_event(None, "verify_security_answer_locked", client_ip, f"username: {uname}")
        raise HTTPException(status_code=429, detail=f"密保验证失败次数过多，请等待 {remaining} 秒后再试")

    user = get_user_by_username(uname)
    if not user:
        # 对不存在账号也执行一次哈希，避免响应时间差暴露账号是否存在
        verify_password(answer.strip().lower(), generate_salt(), "0" * 64)
        record_failed_attempt(user_lock_key)
        record_failed_attempt(ip_lock_key, max_attempts=30)
        raise HTTPException(status_code=400, detail="密保答案不正确，请重新核对后输入")

    is_valid, user_id = verify_security_answer(uname, answer)
    if not is_valid:
        record_failed_attempt(user_lock_key)
        record_failed_attempt(ip_lock_key, max_attempts=30)
        log_audit_event(user_id, "verify_security_answer_failed", client_ip, f"username: {uname}")
        raise HTTPException(status_code=400, detail="密保答案不正确，请重新核对后输入")

    reset_failed_attempts(user_lock_key)
    reset_failed_attempts(ip_lock_key)
    reset_token = create_password_reset_token(user_id, ttl_seconds=600)
    log_audit_event(user_id, "verify_security_answer_success", client_ip, f"username: {uname}")
    return {"status": "ok", "reset_token": reset_token}


@app.post("/api/auth/reset_password")
@app.post("/cogni-scaffold/api/auth/reset_password")
async def reset_password_with_sec_token(request: Request, data: dict):
    """忘记密码第二步：凭有效重置令牌设置新密码"""
    reset_token = data.get("reset_token", "").strip()
    new_password = data.get("new_password", "").strip()
    client_ip = get_client_ip(request)

    if not reset_token or not new_password:
        raise HTTPException(status_code=400, detail="重置凭据或新密码不能为空")
    if len(reset_token) > 256 or len(new_password) > 256:
        raise HTTPException(status_code=400, detail="重置凭据或密码长度超出限制")

    user_id = verify_password_reset_token(reset_token)
    if not user_id:
        raise HTTPException(status_code=400, detail="密码重置链接已失效或超时（有效期 10 分钟），请重新验证密保")

    if new_password in ["Student@2026!", "Admin@Cogni2026!", "123456", "password"]:
        raise HTTPException(status_code=400, detail="禁止继续使用系统默认初始密码，请设置强密码")

    valid, err_msg = validate_password_strength(new_password)
    if not valid:
        raise HTTPException(status_code=400, detail=err_msg)

    update_user_password(user_id, new_password)
    log_audit_event(user_id, "reset_password_success", client_ip, "Success")
    return {"status": "ok", "message": "密码重置成功，请使用新密码重新登录"}


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
    is_admin = (user.get("role") == "admin")
    store = get_user_store(user_id)
    active = store.setdefault("active_sessions", {})

    # 仅允许存在一个未初始化的空白新建会话
    for s_id, s in active.items():
        if not s.get("is_initialized", False) and not s.get("question", "").strip():
            set_user_current_session(user_id, s_id)
            store["current_session_id"] = s_id
            return {"status": "ok", "store": store, "already_exists": True}

    # 防御资源耗尽：限制单个用户同时存在的活跃标签页数量
    if len(active) >= MAX_ACTIVE_SESSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"当前活跃标签页已达上限（{MAX_ACTIVE_SESSIONS} 个），请先归档或关闭部分会话"
        )

    new_s = create_new_session_data(is_initialized=False, store=store)
    save_user_session(user_id, new_s)
    set_user_current_session(user_id, new_s["id"])
    return {"status": "ok", "store": get_user_store(user_id), "user_quota": get_user_quota_info(user_id, is_admin)}


@app.post("/api/sessions/switch")
@app.post("/cogni-scaffold/api/sessions/switch")
async def switch_session(request: Request, data: dict):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")

    s_id = data.get("session_id")
    user_id = user["id"]
    effective_api_config, is_custom_key = get_effective_api_config(user_id)
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
    is_admin = (user.get("role") == "admin")
    new_order = data.get("order", [])
    if new_order and isinstance(new_order, list):
        set_user_session_order(user_id, new_order)
    return {"status": "ok", "store": get_user_store(user_id), "user_quota": get_user_quota_info(user_id, is_admin)}


@app.post("/api/sessions/close")
@app.post("/cogni-scaffold/api/sessions/close")
async def close_session(request: Request, data: dict):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")

    user_id = user["id"]
    is_admin = (user.get("role") == "admin")
    s_id = data.get("session_id")
    archive_user_session(user_id, s_id)
    return {"status": "ok", "store": get_user_store(user_id), "user_quota": get_user_quota_info(user_id, is_admin)}


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
    is_admin = (user.get("role") == "admin")
    s_id = data.get("session_id")
    restore_user_session(user_id, s_id)
    set_user_current_session(user_id, s_id)
    return {"status": "ok", "store": get_user_store(user_id), "user_quota": get_user_quota_info(user_id, is_admin)}


@app.post("/api/sessions/delete_archived")
@app.post("/cogni-scaffold/api/sessions/delete_archived")
async def delete_archived(request: Request, data: dict):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")

    user_id = user["id"]
    is_admin = (user.get("role") == "admin")
    s_id = data.get("session_id")
    delete_archived_user_session(user_id, s_id)
    return {"status": "ok", "store": get_user_store(user_id), "user_quota": get_user_quota_info(user_id, is_admin)}


@app.post("/api/theme")
@app.post("/cogni-scaffold/api/theme")
async def set_theme(request: Request, data: dict):
    theme = str(data.get("theme", "dark")).strip().lower()
    if theme not in {"dark", "light"}:
        raise HTTPException(status_code=400, detail="不支持的主题模式")
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

    # 提问额度与 Token 门禁检测（非管理员账号受约束）
    effective_api_config, is_custom_key = get_effective_api_config(user_id)
    effective_api_config, is_custom_key = get_effective_api_config(user_id)
    is_admin = (user.get("role") == "admin")
    if not is_admin and not is_custom_key:
        can_tokens, used_tokens, limit_tokens = check_can_consume_tokens(user_id, is_admin=is_admin)
        if not can_tokens:
            raise HTTPException(
                status_code=429,
                detail=f"今日 Token 额度已用尽（今日已消耗 {used_tokens}/{limit_tokens} Tokens）。如需继续探索，请联系任课教师或管理员提升专属限额。"
            )

    # 仅当新发起题目时计入今日开题额度；同一会话中途更换题目同样视为一次新开题，
    # 避免攻击者复用已初始化会话无限提交新题目绕过每日限额。
    # 预设案例不计入每日开题限额，但在后续对话计入 Token 与轮次。
    is_new_question = (not sess.get("is_initialized", False)) or (question_text != (sess.get("question") or ""))
    should_record_question = bool(is_new_question and not preset_key and not is_admin)
    if is_new_question and not is_admin and not preset_key:
        can_create, cur_count, max_limit = check_can_create_question(user_id, is_admin=is_admin)
        if not can_create:
            raise HTTPException(
                status_code=429,
                detail=f"今日提问额度已达上限（今日已提问 {cur_count}/{max_limit} 道）。若有学习需要，请联系教师或管理员增加额度。"
            )

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
            raise HTTPException(status_code=400, detail="题目内容不能为空")
        if len(question_text) > 8000:
            raise HTTPException(status_code=400, detail="题目内容过长，请控制在 8000 字以内")
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
        # 标题生成与解题底座均为同步网络调用，放入线程池并行执行，避免阻塞事件循环
        new_title, new_blueprint = await asyncio.gather(
            asyncio.to_thread(
                generate_session_title,
                question=question_text,
                dialogue_history=[],
                diagnostic_result=None,
                current_title=sess.get("title", "会话"),
                title_stage=1,
                api_config=api_config,
                user_id=user_id,
                session_id=s_id,
            ),
            asyncio.to_thread(
                generate_solver_blueprint,
                question_text,
                api_config,
                user_id=user_id,
                session_id=s_id,
            ),
        )
        sess["title"] = new_title
        sess["solver_blueprint"] = new_blueprint

    save_user_session(user_id, sess)
    if should_record_question:
        record_question_submission(user_id, s_id)
    set_user_current_session(user_id, s_id)
    return {"status": "ok", "store": get_user_store(user_id), "user_quota": get_user_quota_info(user_id, is_admin)}


@app.post("/api/sessions/reset")
@app.post("/cogni-scaffold/api/sessions/reset")
async def reset_session(request: Request, data: dict):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")

    user_id = user["id"]
    is_admin = (user.get("role") == "admin")
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
    return {"status": "ok", "store": get_user_store(user_id), "user_quota": get_user_quota_info(user_id, is_admin)}


_session_tier_locks: "weakref.WeakValueDictionary[str, asyncio.Lock]" = weakref.WeakValueDictionary()
_STREAM_SENTINEL = object()

def get_session_lock(session_id: str) -> asyncio.Lock:
    lock = _session_tier_locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _session_tier_locks[session_id] = lock
    return lock


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
    if not sess.get("is_initialized") or not str(sess.get("question") or "").strip():
        raise HTTPException(status_code=400, detail="该会话尚未开题，无法申请诊断")

    lock = get_session_lock(s_id)
    if lock.locked():
        return {"status": "ok", "store": store}

    async with lock:
        store = get_user_store(user_id)
        sess = store.get("active_sessions", {}).get(s_id)
        if sess.get("diagnostic_result"):
            return {"status": "ok", "store": store}

        is_admin = (user.get("role") == "admin")
        # 与前端门禁保持一致：至少完成 3 轮真实启发式对话后才允许生成诊断，
        # 防止直接对空白/新建会话调用接口消耗大模型额度。
        if not is_admin and int(sess.get("tutor_turns") or 0) < 3:
            raise HTTPException(status_code=400, detail="请先完成至少 3 轮思维引导对话，再申请突破诊断")
        if not is_admin:
            can_tokens, used_tokens, limit_tokens = check_can_consume_tokens(user_id, is_admin=is_admin)
            if not can_tokens:
                raise HTTPException(
                    status_code=429,
                    detail=f"今日 Token 额度已用尽（今日已消耗 {used_tokens}/{limit_tokens} Tokens）。如需继续探索，请联系任课教师或管理员提升专属限额。"
                )
        diagnosed = await asyncio.to_thread(trigger_diagnosis_for_session, sess, user_id=user_id)
        if not diagnosed:
            raise HTTPException(status_code=502, detail="诊断画像生成失败，请稍后重试")
        save_user_session(user_id, sess)
        return {"status": "ok", "store": get_user_store(user_id), "user_quota": get_user_quota_info(user_id, is_admin)}


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
        if not isinstance(diag, dict) or not diag:
            raise HTTPException(status_code=400, detail="请先申请突破诊断，再挑战更高阶变式")
        existing_tiers = [
            int(k.replace("tier", "").replace("_variant", ""))
            for k in diag.keys()
            if k.startswith("tier") and k.endswith("_variant") and k.replace("tier", "").replace("_variant", "").isdigit()
        ]
        max_t = max(existing_tiers, default=3)
        curr_tier = sess.get("current_variant_tier", 1)

        if curr_tier <= max_t:
            return {"status": "ok", "store": store}

        is_admin = (user.get("role") == "admin")
        if not is_admin:
            can_tokens, used_tokens, limit_tokens = check_can_consume_tokens(user_id, is_admin=is_admin)
            if not can_tokens:
                raise HTTPException(
                    status_code=429,
                    detail=f"今日 Token 额度已用尽（今日已消耗 {used_tokens}/{limit_tokens} Tokens）。如需继续探索，请联系任课教师或管理员提升专属限额。"
                )

        next_t = max_t + 1
        new_variant = await asyncio.to_thread(
            generate_next_tier_variant,
            sess.get("question", ""),
            sess.get("dialogue_history", []),
            diag,
            next_t,
            api_config,
            user_id=user_id,
            session_id=s_id
        )
        if not isinstance(new_variant, dict):
            raise HTTPException(status_code=502, detail="变式题生成失败，请稍后重试")
        diag[f"tier{next_t}_variant"] = new_variant
        sess["diagnostic_result"] = diag
        sess["current_variant_tier"] = next_t
        sess["current_stage"] = 4
        dispatch_variant_tier_data(sess, next_t)
        save_user_session(user_id, sess)
        return {"status": "ok", "store": get_user_store(user_id), "user_quota": get_user_quota_info(user_id, is_admin)}


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

    if image.content_type and image.content_type.lower() not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="不支持的图片格式，仅支持 JPG、PNG、WebP 图片")

    is_admin = (user.get("role") == "admin")
    if not is_admin and not is_custom_key:
        can_tokens_tokens = check_can_consume_tokens(user["id"], is_admin=is_admin)
        if not can_tokens:
            raise HTTPException(
                status_code=429,
                detail=f"今日 Token 额度已用尽（今日已消耗 {used_tokens}/{limit_tokens} Tokens）。如需继续探索，请联系任课教师或管理员提升专属限额。"
            )

    try:
        content = await image.read(MAX_UPLOAD_SIZE + 1)
        if len(content) > MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=400, detail="图片大小超出限制（单张最大允许 10MB）")

        # 过滤与截断题目上下文，防范 Prompt 注入
        safe_context = question_context[:500].strip()
        recognized_text = await asyncio.to_thread(
            analyze_image_input, content, mode, safe_context, api_config, user_id=user["id"]
        )
        return {"status": "ok", "text": recognized_text}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[Upload/OCR Error] {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail="图片处理与识别失败，请检查文件或稍后重试")


async def aiter_sync_generator(sync_gen, keepalive_interval: float = 3.0):
    """
    将阻塞式同步 Generator（如 OpenAI 流式迭代器）转换为轻量高效的异步流，
    避免逐 token 频繁调度 ThreadPoolExecutor 导致的多核争用与线程池耗尽。
    若上游生成出现网络停顿或模型思考阶段，自动发送 SSE 注释保活帧，防止网关/反向代理超时或缓冲。
    """
    queue = asyncio.Queue(maxsize=100)
    loop = asyncio.get_running_loop()
    done_event = threading.Event()

    def _worker():
        try:
            for item in sync_gen:
                if done_event.is_set():
                    break
                asyncio.run_coroutine_threadsafe(queue.put(("chunk", item)), loop).result()
        except Exception as e:
            asyncio.run_coroutine_threadsafe(queue.put(("error", e)), loop).result()
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(("done", None)), loop).result()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

    try:
        while True:
            try:
                msg_type, payload = await asyncio.wait_for(queue.get(), timeout=keepalive_interval)
                if msg_type == "done":
                    break
                elif msg_type == "error":
                    raise payload
                elif msg_type == "chunk":
                    yield payload
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
    finally:
        done_event.set()


@app.post("/api/sessions/{session_id}/chat/stream")
@app.post("/cogni-scaffold/api/sessions/{session_id}/chat/stream")
async def chat_stream(session_id: str, request: Request, data: dict):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="问答功能需先登录账号")

    student_text = str(data.get("student_text", "") or "").strip()
    if not student_text:
        raise HTTPException(status_code=400, detail="输入内容不能为空")
    if len(student_text) > 4000:
        raise HTTPException(status_code=400, detail="单次输入内容过长，请控制在 4000 字以内")

    user_id = user["id"]
    store = get_user_store(user_id)
    sess = store.get("active_sessions", {}).get(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    if not sess.get("is_initialized") or not str(sess.get("question") or "").strip():
        raise HTTPException(status_code=400, detail="该会话尚未开题，请先提交题目")

    # 对话轮次与 Token 门禁检测（非管理员账号受单题目轮次及当日Token限额约束）
    is_admin = (user.get("role") == "admin")
    if not is_admin:
        can_tokens, used_tokens, limit_tokens = check_can_consume_tokens(user_id, is_admin=is_admin)
        if not can_tokens:
            raise HTTPException(
                status_code=429,
                detail=f"今日 Token 额度已用尽（今日已消耗 {used_tokens}/{limit_tokens} Tokens）。如需继续探索，请联系任课教师或管理员提升专属限额。"
            )

    can_continue, cur_turns, max_turns = check_can_continue_chat(user_id, sess.get("tutor_turns", 0), is_admin=is_admin)
    if not can_continue:
        raise HTTPException(
            status_code=429,
            detail=f"当前题目的对话轮次已达上限（已完成 {cur_turns}/{max_turns} 轮）。请根据现有导学总结推导，或开启新题目继续探索。"
        )

    lock = get_session_lock(session_id)
    if lock.locked():
        raise HTTPException(status_code=429, detail="当前会话已有正在进行的流式推理，请等待上一轮完成")

    async def event_generator():
        nonlocal sess
        effective_api_config, is_custom_key = get_effective_api_config(user_id)
        # 使用 async with 保证生成器在任意位置被取消时锁都能释放，避免会话永久死锁
        async with lock:
            # 抢到锁后重新加载会话快照，避免并发请求用旧快照覆盖上一轮消息
            latest_store = get_user_store(user_id)
            latest_sess = (latest_store.get("active_sessions") or {}).get(session_id)
            if latest_sess:
                sess = latest_sess
            try:
                # 1. 记录学生输入
                sess["dialogue_history"].append({"role": "user", "content": student_text})

                # 【断路器 1：前置安全与合规检测】
                is_blocked, refusal_text = check_input_guardrail(student_text)
                if is_blocked:
                    matched_p = get_matched_guardrail_pattern(student_text)
                    record_guardrail_log(
                        user_id=user_id,
                        session_id=session_id,
                        input_text=student_text,
                        matched_pattern=matched_p or "keyword_match",
                        action_taken="blocked"
                    )
                    chunk_size = 12
                    for i in range(0, len(refusal_text), chunk_size):
                        chunk = refusal_text[i:i+chunk_size]
                        yield f"data: {json.dumps({'type': 'chunk', 'content': chunk, 'role': 'assistant'}, ensure_ascii=False)}\n\n"
                        await asyncio.sleep(0.01)

                    sess["dialogue_history"].append({"role": "assistant", "content": refusal_text})
                    save_user_session(user_id, sess)
                    yield f"data: {json.dumps({'type': 'done', 'session': sess, 'store': get_user_store(user_id), 'user_quota': get_user_quota_info(user_id, is_admin)}, ensure_ascii=False)}\n\n"
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
                    yield f"data: {json.dumps({'type': 'done', 'session': sess, 'store': get_user_store(user_id), 'user_quota': get_user_quota_info(user_id, is_admin)}, ensure_ascii=False)}\n\n"
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
                    yield f"data: {json.dumps({'type': 'done', 'session': sess, 'store': get_user_store(user_id), 'user_quota': get_user_quota_info(user_id, is_admin)}, ensure_ascii=False)}\n\n"
                    return

                # 阶段 4：变式迁移挑战应答
                if sess.get("current_stage") == 4:
                    diag = sess.get("diagnostic_result") or {}
                    if not isinstance(diag, dict):
                        diag = {}
                    defined_tiers = [
                        int(k.replace("tier", "").replace("_variant", ""))
                        for k in diag.keys()
                        if k.startswith("tier") and k.endswith("_variant") and k.replace("tier", "").replace("_variant", "").isdigit()
                    ]
                    max_defined = max(defined_tiers, default=3)
                    curr_tier = sess.get("current_variant_tier", 1)

                    if curr_tier > max_defined:
                        next_t = max_defined + 1
                        new_variant = await asyncio.to_thread(
                            generate_next_tier_variant,
                            sess.get("question", ""),
                            sess.get("dialogue_history", []),
                            diag,
                            next_t,
                            api_config,
                            user_id=user_id,
                            session_id=session_id
                        )
                        if isinstance(new_variant, dict):
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

                        yield f"data: {json.dumps({'type': 'done', 'session': sess, 'store': get_user_store(user_id), 'user_quota': get_user_quota_info(user_id, is_admin)}, ensure_ascii=False)}\n\n"
                        return

                    tier_data = diag.get(f"tier{curr_tier}_variant", {})
                    if not isinstance(tier_data, dict):
                        tier_data = {}
                    var_q = tier_data.get("question", "变式题")
                    var_h = tier_data.get("hint", "")

                    eval_text = await asyncio.to_thread(
                        evaluate_transfer_answer, var_q, var_h, student_text, api_config,
                        user_id=user_id, session_id=session_id
                    )
                    eval_text = str(eval_text or "")

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
                    yield f"data: {json.dumps({'type': 'done', 'session': sess, 'store': get_user_store(user_id), 'user_quota': get_user_quota_info(user_id, is_admin)}, ensure_ascii=False)}\n\n"

                else:
                    # 阶段 1~3：启发式引导
                    full_response = ""
                    temp_history = list(sess["dialogue_history"])
                    usage_dict = {}

                    # 使用轻量异步流迭代器驱动，零线程调度争用并自带保活穿透代理
                    active_api_config = effective_api_config
                    used_fallback = False

                    try:
                        tutor_gen = stream_tutor_response(
                            temp_history, sess.get("solver_blueprint", ""), active_api_config, usage_dict=usage_dict
                        )
                        async for chunk in aiter_sync_generator(tutor_gen, keepalive_interval=3.0):
                            if await request.is_disconnected():
                                print(f"[Chat Stream] Client disconnected prematurely for session {session_id}")
                                break
                            if chunk.startswith(":"):
                                yield chunk
                                continue
                            full_response += chunk
                            clean_chunk = chunk.replace("[TRIGGER_DIAGNOSIS]", "")
                            if clean_chunk:
                                yield f"data: {json.dumps({'type': 'chunk', 'content': clean_chunk, 'role': 'assistant'}, ensure_ascii=False)}\n\n"
                    except Exception as stream_err:
                        if is_custom_key and not used_fallback and not full_response:
                            print(f"[Custom API Fallback] Key failed ({stream_err}), falling back to school api_config")
                            used_fallback = True
                            fallback_notice = "⚠️ 您的专属 API Key 调用受限或余额不足，系统已自动无缝切换至学校公共配额继续服务。"
                            yield f"data: {json.dumps({'type': 'api_fallback', 'message': fallback_notice}, ensure_ascii=False)}\n\n"
                            
                            usage_dict = {}
                            active_api_config = api_config
                            tutor_gen = stream_tutor_response(
                                temp_history, sess.get("solver_blueprint", ""), api_config, usage_dict=usage_dict
                            )
                            async for chunk in aiter_sync_generator(tutor_gen, keepalive_interval=3.0):
                                if await request.is_disconnected():
                                    break
                                if chunk.startswith(":"):
                                    yield chunk
                                    continue
                                full_response += chunk
                                clean_chunk = chunk.replace("[TRIGGER_DIAGNOSIS]", "")
                                if clean_chunk:
                                    yield f"data: {json.dumps({'type': 'chunk', 'content': clean_chunk, 'role': 'assistant'}, ensure_ascii=False)}\n\n"
                        else:
                            raise stream_err
                    finally:
                        try:
                            tutor_gen.close()
                        except Exception:
                            pass

                    clean_full = full_response.replace("[TRIGGER_DIAGNOSIS]", "").strip()
                    sess["dialogue_history"].append({"role": "assistant", "content": clean_full})
                    sess["tutor_turns"] += 1

                    if usage_dict:
                        record_token_usage(
                            user_id=user_id,
                            session_id=session_id,
                            prompt_tokens=usage_dict.get("prompt_tokens", 0),
                            completion_tokens=usage_dict.get("completion_tokens", 0),
                            total_tokens=usage_dict.get("total_tokens", 0),
                            model_name=api_config.get("model", "deepseek-chat"),
                            call_type="chat_tutor"
                        )

                    # 标题提炼异步非阻塞执行，不拖累当前流式响应结束
                    if sess.get("title_stage", 0) == 0:
                        sess["title_stage"] = 1
                        async def _bg_title(q, hist, u_id, s_id):
                            try:
                                t = await asyncio.to_thread(
                                    generate_session_title,
                                    q, hist, None, "会话", 1, api_config, user_id=u_id, session_id=s_id
                                )
                                s_store = get_user_store(u_id)
                                cur_s = (s_store.get("active_sessions") or {}).get(s_id)
                                if cur_s:
                                    cur_s["title"] = t
                                    cur_s["title_stage"] = 1
                                    save_user_session(u_id, cur_s)
                            except Exception as e:
                                print(f"[BG Title Error] {e}")

                        asyncio.create_task(_bg_title(sess["question"], list(sess["dialogue_history"]), user_id, session_id))

                    is_refusal = check_output_refusal(clean_full)

                    can_trigger_diagnosis = (
                        not is_refusal
                        and (intent_type not in ["LOW_INFO", "DEMAND_ANSWER"] and sess.get("tutor_turns", 0) >= 2)
                        and "[TRIGGER_DIAGNOSIS]" in full_response
                    )

                    if can_trigger_diagnosis:
                        # 明确通知客户端：主回复已完毕，正在生成深度认知透视与变式题
                        yield f"data: {json.dumps({'type': 'stage_transition', 'stage': 'diagnosing', 'message': '✨ 检测到认知突破！正在为你生成思维盲区透视与定制三阶变式挑战...'}, ensure_ascii=False)}\n\n"
                        await asyncio.to_thread(trigger_diagnosis_for_session, sess, user_id=user_id)

                    save_user_session(user_id, sess)
                    yield f"data: {json.dumps({'type': 'done', 'session': sess, 'store': get_user_store(user_id), 'user_quota': get_user_quota_info(user_id, is_admin)}, ensure_ascii=False)}\n\n"

            except Exception as err:
                print(f"[Chat Stream Exception] {type(err).__name__}: {err}")
                err_msg = "⚠️ 导师连接处理异常，请点击重试。"
                yield f"data: {json.dumps({'type': 'chunk', 'content': err_msg, 'role': 'assistant'}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'session': sess, 'store': get_user_store(user_id), 'user_quota': get_user_quota_info(user_id, is_admin)}, ensure_ascii=False)}\n\n"

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive"
    }
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)


# ============================================================
# 管理员控制台 API (仅限 admin 角色访问，违规直接 403 阻断)
# ============================================================

@app.get("/api/admin/overview")
@app.get("/cogni-scaffold/api/admin/overview")
async def admin_get_overview(request: Request):
    require_admin(request)
    overview = get_admin_overview()
    return {"status": "ok", "overview": overview}


@app.get("/api/admin/users")
@app.get("/cogni-scaffold/api/admin/users")
async def admin_get_users(
    request: Request,
    search: str = "",
    role: str = "",
    status: str = "",
    class_name: str = "",
    page_size: int = 500
):
    require_admin(request)
    page_size = max(1, min(int(page_size), 500))
    users = get_admin_users_list(search=search, role=role, status=status, limit=page_size, class_filter=class_name)
    return {"status": "ok", "users": users, "total_count": len(users)}


@app.post("/api/admin/users/batch")
@app.post("/cogni-scaffold/api/admin/users/batch")
async def admin_batch_users(request: Request, data: dict):
    require_admin(request)
    mode = data.get("mode", "pattern")
    users_to_create = []

    if mode == "pattern":
        prefix = str(data.get("prefix", "student")).strip()
        try:
            start = int(data.get("start", 1))
            end = int(data.get("end", 10))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="起始与结束序号必须为整数")
        default_pwd = str(data.get("default_password", "CogniScaffold123!")).strip()
        role = str(data.get("role", "student")).strip()
        class_name = str(data.get("class_name", "")).strip()[:40]

        if role not in ("student", "admin"):
            raise HTTPException(status_code=400, detail="非法的用户角色")
        if not re.fullmatch(r"[A-Za-z0-9_.@-]{2,32}", prefix):
            raise HTTPException(status_code=400, detail="账号前缀仅限 2-32 位字母、数字、下划线、点、@ 字符")
        if start < 1 or end > 999999:
            raise HTTPException(status_code=400, detail="序号范围须在 1-999999 之间")
        if end < start:
            raise HTTPException(status_code=400, detail="结束序号不能小于起始序号")
        if (end - start + 1) > 500:
            raise HTTPException(status_code=400, detail="单次批量创建账号总数不能超过 500 个")

        valid_pwd, pwd_err = validate_password_strength(default_pwd)
        if not valid_pwd:
            raise HTTPException(status_code=400, detail=f"默认密码不符合强度要求：{pwd_err}")

        pad_len = max(2, len(str(end)))
        for i in range(start, end + 1):
            num_str = str(i).zfill(pad_len)
            uname = f"{prefix}{num_str}"
            dname = f"学生{num_str}" if role == "student" else f"用户{num_str}"
            users_to_create.append({
                "username": uname,
                "password": default_pwd,
                "display_name": dname,
                "class_name": class_name,
                "role": role
            })
    elif mode == "table":
        table_text = data.get("table_text", "").strip()
        if not table_text:
            raise HTTPException(status_code=400, detail="粘贴文本内容不能为空")
        
        lines = [line.strip() for line in table_text.splitlines() if line.strip()]
        for line in lines:
            parts = [p.strip() for p in re.split(r'[	,，|]+', line)]
            if len(parts) < 2:
                continue
            # 严格按照规范：账号, 密码, 姓名, 班级（禁止粘贴创建管理员，角色统一锁死为 student）
            uname = parts[0]
            pwd = parts[1]
            dname = parts[2] if len(parts) > 2 and parts[2] else uname
            cname = parts[3] if len(parts) > 3 else ""
            if not re.fullmatch(r"[A-Za-z0-9_.@-]{2,32}", uname):
                raise HTTPException(status_code=400, detail=f"账号格式不符合规范：{uname[:32]}")
            if len(pwd) > 256 or len(dname) > 40:
                raise HTTPException(status_code=400, detail=f"账号 {uname[:32]} 的密码或显示名称过长")
            valid_pwd, pwd_err = validate_password_strength(pwd)
            if not valid_pwd:
                raise HTTPException(status_code=400, detail=f"账号 {uname[:32]} 密码不符合强度要求：{pwd_err}")
            users_to_create.append({
                "username": uname,
                "password": pwd,
                "display_name": dname,
                "class_name": cname,
                "role": "student"
            })
    else:
        raise HTTPException(status_code=400, detail="未知的批量创建模式")

    if not users_to_create:
        raise HTTPException(status_code=400, detail="未解析到有效用户数据，请检查输入格式")

    # 关键修复：使用 asyncio.to_thread 移入线程池执行 PBKDF2 哈希计算，彻底消除批量导入时的前端阻塞卡死
    results = await asyncio.to_thread(batch_create_users, users_to_create)
    return {"status": "ok", "results": results}


@app.post("/api/admin/users/ban")
@app.post("/cogni-scaffold/api/admin/users/ban")
async def admin_ban_user(request: Request, data: dict):
    admin = require_admin(request)
    user_id = data.get("user_id")
    duration = data.get("duration", "permanent")
    custom_until = data.get("custom_until", "")
    reason = data.get("reason", "管理员临时封禁")

    if not user_id:
        raise HTTPException(status_code=400, detail="缺少 user_id 参数")
    if str(user_id) == str(admin["id"]):
        raise HTTPException(status_code=400, detail="管理员不可封禁自己的账号")
    if duration not in ("1d", "3d", "7d", "custom", "permanent"):
        raise HTTPException(status_code=400, detail="不支持的封禁时长")
    reason = str(reason or "").strip()[:200] or "管理员临时封禁"

    now = now_east8()
    if duration == "1d":
        banned_until = (now + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    elif duration == "3d":
        banned_until = (now + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    elif duration == "7d":
        banned_until = (now + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    elif duration == "custom":
        custom_until = str(custom_until or "").strip()
        if not custom_until:
            raise HTTPException(status_code=400, detail="自定义封禁时间不能为空")
        parsed = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(custom_until, fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            raise HTTPException(status_code=400, detail="自定义封禁时间格式不正确，请使用 YYYY-MM-DD HH:MM:SS")
        banned_until = parsed.strftime("%Y-%m-%d %H:%M:%S")
    else:
        banned_until = "permanent"

    ban_user(str(user_id), banned_until, reason, admin_id=str(admin["id"]))
    return {"status": "ok", "message": f"用户已被限制登录（{banned_until}）"}


@app.post("/api/admin/users/unban")
@app.post("/cogni-scaffold/api/admin/users/unban")
async def admin_unban_user(request: Request, data: dict):
    require_admin(request)
    user_id = data.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="缺少 user_id 参数")
    unban_user(str(user_id))
    return {"status": "ok", "message": "用户已成功解除封禁"}


@app.post("/api/admin/users/reset_password")
@app.post("/cogni-scaffold/api/admin/users/reset_password")
async def admin_reset_password(request: Request, data: dict):
    admin = require_admin(request)
    user_id = data.get("user_id")
    new_password = data.get("new_password", "").strip()

    if not user_id or not new_password:
        raise HTTPException(status_code=400, detail="缺少 user_id 或新密码")
    if len(new_password) > 256:
        raise HTTPException(status_code=400, detail="新密码长度超出限制")

    valid, err_msg = validate_password_strength(new_password)
    if not valid:
        raise HTTPException(status_code=400, detail=f"新密码不符合安全要求：{err_msg}")

    success = reset_user_password_by_admin(str(user_id), new_password, admin_id=str(admin["id"]))
    if not success:
        raise HTTPException(status_code=404, detail="目标用户不存在")
    return {"status": "ok", "message": "用户密码重置成功，原登录会话已全部注销"}


@app.post("/api/admin/users/quota")
@app.post("/cogni-scaffold/api/admin/users/quota")
async def admin_set_quota(request: Request, data: dict):
    require_admin(request)
    user_id = data.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="缺少 user_id 参数")

    custom_daily = data.get("custom_daily_limit")
    custom_turn = data.get("custom_turn_limit")
    custom_token = data.get("custom_daily_token_limit")
    reset_today = bool(data.get("reset_today", False))

    def _parse_quota(value, field: str):
        if value is None or value == "":
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{field} 必须为整数")
        if parsed < 1 or parsed > 10_000_000:
            raise HTTPException(status_code=400, detail=f"{field} 必须在 1-10000000 之间")
        return parsed

    custom_daily = _parse_quota(custom_daily, "每日开题上限")
    custom_turn = _parse_quota(custom_turn, "单题轮次上限")
    custom_token = _parse_quota(custom_token, "每日 Token 上限")

    updated = set_user_custom_quota(str(user_id), custom_daily, custom_turn, custom_token)
    if not updated:
        raise HTTPException(status_code=404, detail="目标用户不存在")
    if reset_today:
        reset_user_today_questions(str(user_id))
    return {"status": "ok", "message": "用户专属额度配置已更新"}


@app.get("/api/admin/sessions")
@app.get("/cogni-scaffold/api/admin/sessions")
async def admin_get_sessions(
    request: Request,
    user_id: Optional[str] = None,
    search: Optional[str] = None,
    page_size: int = 100
):
    require_admin(request)
    page_size = max(1, min(int(page_size), 500))
    sessions = get_admin_sessions_list(user_id=user_id, search=search or "", limit=page_size)
    return {"status": "ok", "sessions": sessions, "total_count": len(sessions)}


@app.get("/api/admin/sessions/{session_id}")
@app.get("/cogni-scaffold/api/admin/sessions/{session_id}")
async def admin_get_session_detail_endpoint(session_id: str, request: Request):
    require_admin(request)
    detail = get_admin_session_detail(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail="会话记录不存在")
    return {"status": "ok", "session": detail}


@app.get("/api/admin/configs")
@app.get("/cogni-scaffold/api/admin/configs")
async def admin_get_configs(request: Request):
    require_admin(request)
    configs = get_all_system_configs()
    return {"status": "ok", "configs": configs}


@app.post("/api/admin/configs")
@app.post("/cogni-scaffold/api/admin/configs")
async def admin_set_configs(request: Request, data: dict):
    require_admin(request)
    configs = data.get("configs", {})
    if not isinstance(configs, dict):
        raise HTTPException(status_code=400, detail="configs 必须为对象")

    int_limits = {
        "daily_question_limit": (1, 100000),
        "session_turn_limit": (1, 100000),
        "daily_token_limit": (1, 100000000),
    }
    float_prices = {"deepseek_input_price_per_m", "deepseek_output_price_per_m"}
    allowed_keys = set(int_limits) | float_prices

    sanitized: Dict[str, str] = {}
    for k, v in configs.items():
        key = str(k)
        if key not in allowed_keys:
            raise HTTPException(status_code=400, detail=f"不支持的系统配置项：{key[:40]}")
        if key in int_limits:
            try:
                parsed = int(str(v).strip())
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"配置项 {key} 必须为整数")
            low, high = int_limits[key]
            if parsed < low or parsed > high:
                raise HTTPException(status_code=400, detail=f"配置项 {key} 必须在 {low}-{high} 之间")
            sanitized[key] = str(parsed)
        else:
            try:
                parsed_f = float(str(v).strip())
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"配置项 {key} 必须为数字")
            if parsed_f < 0 or parsed_f > 1_000_000:
                raise HTTPException(status_code=400, detail=f"配置项 {key} 超出允许范围")
            sanitized[key] = str(parsed_f)

    for k, v in sanitized.items():
        set_system_config(k, v)
    return {"status": "ok", "message": "系统全局配置已更新", "configs": get_all_system_configs()}


@app.get("/api/admin/guardrail_logs")
@app.get("/cogni-scaffold/api/admin/guardrail_logs")
async def admin_get_guardrail_logs(request: Request, limit: int = 100):
    require_admin(request)
    limit = max(1, min(int(limit), 1000))
    logs = get_guardrail_logs(limit=limit)
    return {"status": "ok", "logs": logs}


@app.get("/api/admin/probe")
@app.get("/cogni-scaffold/api/admin/probe")
async def admin_probe_api(request: Request):
    require_admin(request)
    import time
    from openai import OpenAI
    start_time = time.time()
    model = api_config.get("model", "deepseek-chat")
    base_url = api_config.get("base_url", "https://api.deepseek.com")
    api_key = api_config.get("api_key", "")

    if not api_key:
        return {
            "status": "error",
            "message": "未配置 OPENAI_API_KEY",
            "model": model,
            "base_url": base_url,
            "latency_ms": None
        }

    try:
        def _probe():
            from core.engine import get_openai_client, call_llm_with_retry
            client = get_openai_client(api_key, base_url)
            return call_llm_with_retry(
                client,
                {
                    "model": model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1
                },
                max_retries=3,
                initial_delay=0.3
            )

        res = await asyncio.to_thread(_probe)
        latency_ms = int((time.time() - start_time) * 1000)
        return {
            "status": "ok",
            "message": "API 连通正常",
            "model": model,
            "base_url": base_url,
            "latency_ms": latency_ms,
            "response_text": res.choices[0].message.content if res.choices else ""
        }
    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        return {
            "status": "error",
            "message": f"探测失败：{type(e).__name__}: {str(e)}",
            "model": model,
            "base_url": base_url,
            "latency_ms": latency_ms
        }


# ============================================================
# 用户反馈与管理回复接口 (Feedback & Admin Replies API)
# ============================================================

@app.post("/api/feedbacks")
@app.post("/cogni-scaffold/api/feedbacks")
async def create_feedback_endpoint(request: Request, data: dict):
    user = get_current_user(request)
    client_ip = get_client_ip(request)
    # 反馈接口允许匿名提交，因此必须限流，防止被用于灌库或骚扰
    allowed, retry_after = check_action_rate(f"feedback:{client_ip}", max_events=10, window_seconds=600)
    if not allowed:
        raise HTTPException(status_code=429, detail=f"提交过于频繁，请 {retry_after} 秒后再试")

    title = str(data.get("title") or "").strip()
    content = str(data.get("content") or "").strip()
    contact = str(data.get("contact") or "").strip()
    raw_category = str(data.get("category") or "other").strip()
    allowed_categories = {"pedagogical", "bug", "ui", "feature", "other"}
    # 白名单收敛分类字段，杜绝把任意 HTML/脚本写入数据库并回流到管理端
    category = raw_category if raw_category in allowed_categories else "other"

    if not title:
        raise HTTPException(status_code=400, detail="反馈标题不能为空")
    if not content:
        raise HTTPException(status_code=400, detail="反馈详细内容不能为空")
    if len(title) > 200:
        raise HTTPException(status_code=400, detail="反馈标题过长（最多 200 字）")
    if len(content) > 5000:
        raise HTTPException(status_code=400, detail="反馈内容过长（最多 5000 字）")
    if len(contact) > 200:
        raise HTTPException(status_code=400, detail="联系方式过长（最多 200 字）")

    fb = submit_user_feedback(
        user_id=str(user["id"]) if user else None,
        username=user["username"] if user else "访客",
        category=category,
        title=title,
        content=content,
        contact=contact
    )
    return {"status": "ok", "message": "感谢您的反馈，管理员审阅后将尽快在此答复！", "feedback": fb}


@app.get("/api/feedbacks/my")
@app.get("/cogni-scaffold/api/feedbacks/my")
async def get_my_feedbacks_endpoint(request: Request):
    user = get_current_user(request)
    if not user:
        return {"status": "ok", "feedbacks": []}
    fbs = get_user_feedbacks(str(user["id"]))
    return {"status": "ok", "feedbacks": fbs}


@app.get("/api/admin/feedbacks")
@app.get("/cogni-scaffold/api/admin/feedbacks")
async def admin_get_feedbacks_endpoint(
    request: Request,
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100
):
    require_admin(request)
    limit = max(1, min(int(limit), 500))
    fbs = get_admin_feedbacks(status=status, search=search or "", limit=limit)
    return {"status": "ok", "feedbacks": fbs}


@app.post("/api/admin/feedbacks/{feedback_id}/reply")
@app.post("/cogni-scaffold/api/admin/feedbacks/{feedback_id}/reply")
async def admin_reply_feedback_endpoint(feedback_id: int, request: Request, data: dict):
    admin = require_admin(request)
    reply = (data.get("reply") or "").strip()
    status = data.get("status", "replied")

    if not reply:
        raise HTTPException(status_code=400, detail="回复内容不能为空")
    if len(reply) > 5000:
        raise HTTPException(status_code=400, detail="回复内容过长（最多 5000 字）")
    if status not in ("replied", "pending", "closed"):
        status = "replied"

    success = reply_user_feedback(
        feedback_id=feedback_id,
        admin_reply=reply,
        admin_name=admin.get("username", "管理员"),
        status=status
    )
    if not success:
        raise HTTPException(status_code=404, detail="反馈记录不存在")
    return {"status": "ok", "message": "回复成功！"}




# ============================================================
# 班级管理、回收站与高级批量控制台 API
# ============================================================

@app.get("/api/admin/classes")
@app.get("/cogni-scaffold/api/admin/classes")
async def admin_get_classes(request: Request):
    require_admin(request)
    classes = get_all_class_names()
    return {"status": "ok", "classes": classes}


@app.post("/api/admin/users/batch_actions")
@app.post("/cogni-scaffold/api/admin/users/batch_actions")
async def admin_users_batch_actions(request: Request, data: dict):
    admin = require_admin(request)
    action = data.get("action")
    user_ids = data.get("user_ids", [])
    params = data.get("params", {})

    if not isinstance(user_ids, list) or not user_ids:
        raise HTTPException(status_code=400, detail="请至少勾选一个账号")

    if action == "delete_trash":
        res = batch_soft_delete_users(user_ids, admin["id"])
        return {"status": "ok", "message": f"成功将 {res['success']} 个账号移入回收站", "result": res}
    elif action == "restore":
        res = batch_restore_users(user_ids)
        return {"status": "ok", "message": f"成功从回收站恢复 {res['success']} 个账号", "result": res}
    elif action == "purge":
        res = batch_purge_users(user_ids, admin["id"])
        return {"status": "ok", "message": f"成功彻底粉碎 {res['success']} 个账号及关联数据", "result": res}
    elif action == "reset_pwd":
        new_pwd = str(params.get("new_password") or "CogniScaffold123!").strip()
        valid, err = validate_password_strength(new_pwd)
        if not valid:
            raise HTTPException(status_code=400, detail=f"新密码不符合强度要求：{err}")
        res = batch_reset_user_passwords(user_ids, new_pwd)
        return {"status": "ok", "message": f"已将选中的 {res['success']} 个账号密码重置为统一密码，并将在下次登入时强制修改", "result": res}
    elif action == "set_limit":
        try:
            new_limit = int(params.get("new_limit", 50000))
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Token 上限必须为整数")
        if new_limit < 1000 or new_limit > 5000000:
            raise HTTPException(status_code=400, detail="Token 上限应在 1,000 ~ 5,000,000 之间")
        res = batch_set_user_token_limits(user_ids, new_limit)
        return {"status": "ok", "message": f"已成功将 {res['success']} 个账号每日 Token 限额设为 {new_limit:,}", "result": res}
    elif action == "ban":
        res = batch_set_user_status(user_ids, "banned")
        return {"status": "ok", "message": f"已封禁 {res['success']} 个账号", "result": res}
    elif action == "unban":
        res = batch_set_user_status(user_ids, "active")
        return {"status": "ok", "message": f"已解封 {res['success']} 个账号", "result": res}
    elif action == "reset_quota":
        res = batch_reset_user_today_usage(user_ids)
        return {"status": "ok", "message": f"已重置 {res['success']} 个账号今日消耗基准", "result": res}
    else:
        raise HTTPException(status_code=400, detail=f"不支持的批量操作：{action}")


@app.delete("/api/admin/users/{user_id}")
@app.delete("/cogni-scaffold/api/admin/users/{user_id}")
async def admin_delete_user_endpoint(user_id: str, request: Request):
    admin = require_admin(request)
    ok, msg = soft_delete_user(user_id, admin["id"])
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "ok", "message": msg}


@app.delete("/api/admin/sessions/{session_id}")
@app.delete("/cogni-scaffold/api/admin/sessions/{session_id}")
async def admin_delete_session_endpoint(session_id: str, request: Request):
    require_admin(request)
    ok = soft_delete_session(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在或已删除")
    return {"status": "ok", "message": "会话已成功移入回收站"}


@app.get("/api/admin/trash/items")
@app.get("/cogni-scaffold/api/admin/trash/items")
async def admin_get_trash_items(request: Request):
    require_admin(request)
    items = get_trash_items()
    return {"status": "ok", "trash": items}


@app.post("/api/admin/trash/sessions/action")
@app.post("/cogni-scaffold/api/admin/trash/sessions/action")
async def admin_trash_sessions_action(request: Request, data: dict):
    require_admin(request)
    action = data.get("action")
    session_ids = data.get("session_ids", [])
    if not isinstance(session_ids, list) or not session_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个对话")

    if action == "restore":
        res = batch_restore_sessions(session_ids)
        return {"status": "ok", "message": f"成功恢复 {res['success']} 个对话", "result": res}
    elif action == "purge":
        res = batch_purge_sessions(session_ids)
        return {"status": "ok", "message": f"成功彻底粉碎 {res['success']} 个对话", "result": res}
    else:
        raise HTTPException(status_code=400, detail=f"不支持的操作：{action}")


@app.get("/api/admin/analytics/class_report")
@app.get("/cogni-scaffold/api/admin/analytics/class_report")
async def admin_class_report_endpoint(
    request: Request,
    class_name: Optional[str] = None,
    format: Optional[str] = None
):
    require_admin(request)
    cname = (class_name or "").strip() or None
    analytics = get_class_analytics(cname)
    
    if format == "csv":
        import io
        import csv
        output = io.StringIO()
        output.write("\ufeff")  # UTF-8 BOM
        writer = csv.writer(output)
        writer.writerow(["学号/账号", "学生姓名", "班级", "探究会话数", "达成突破数(阶段4+)", "主要思维盲区类型"])
        for s in analytics.get("student_reports", []):
            blindspots_str = "、".join(set(s.get("blindspots", []))) if s.get("blindspots") else "暂无记录"
            writer.writerow([
                s.get("username", ""),
                s.get("display_name", ""),
                s.get("class_name", "") or "未分班",
                s.get("sessions_count", 0),
                s.get("breakthroughs", 0),
                blindspots_str
            ])
        csv_bytes = output.getvalue().encode("utf-8")
        filename = f"class_report_{(cname or 'all')}_{today_east8_str()}.csv"
        return Response(
            content=csv_bytes,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    return {"status": "ok", "report": analytics}


# ============================================================
# 用户自定义专属 API Key 管理 API
# ============================================================

@app.post("/api/user/custom_api_key")
@app.post("/cogni-scaffold/api/user/custom_api_key")
async def set_custom_api_key_endpoint(request: Request, data: dict):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登入账号")

    raw_key = str(data.get("api_key") or "").strip()
    if not raw_key:
        raise HTTPException(status_code=400, detail="API Key 不能为空")

    if not raw_key.startswith("sk-") or len(raw_key) < 15 or len(raw_key) > 128:
        raise HTTPException(status_code=400, detail="API Key 格式不合规：必须为 sk- 开头的有效密钥字符串")

    # 连通性探测
    def _probe():
        from core.engine import get_openai_client
        client = get_openai_client(raw_key, "https://api.deepseek.com")
        return client.models.list()

    try:
        await asyncio.to_thread(_probe)
    except Exception as e:
        err_msg = str(e)
        err_lower = err_msg.lower()
        if "401" in err_msg or "authentication" in err_lower or "invalid" in err_lower:
            raise HTTPException(
                status_code=400,
                detail="API Key 校验失败（HTTP 401 认证失败）：密钥无效或未激活，请确认是从 DeepSeek 官方开放平台完整复制的 sk- 密钥。"
            )
        elif "402" in err_msg or "insufficient_quota" in err_lower or "balance" in err_lower or "quota" in err_lower:
            raise HTTPException(
                status_code=400,
                detail="API Key 校验失败（HTTP 402 账户余额不足）：请先前往 DeepSeek 官方开放平台充值（推荐充值 10 元）后再绑定使用。"
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"连接 DeepSeek 官方 API 失败：{type(e).__name__} - {err_msg}。请检查网络或稍后重试。"
            )

    set_user_custom_api_key(str(user["id"]), raw_key)
    masked = raw_key[:5] + "****" + raw_key[-4:]
    return {"status": "ok", "message": "DeepSeek API Key 验证成功并已成功绑定！后续提问将优先使用您的专属 Key。", "masked_key": masked}


@app.get("/api/user/custom_api_key")
@app.get("/cogni-scaffold/api/user/custom_api_key")
async def get_custom_api_key_endpoint(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登入账号")

    k = get_user_custom_api_key(str(user["id"]))
    if k and k.strip().startswith("sk-"):
        masked = k[:5] + "****" + k[-4:]
        return {
            "status": "ok",
            "has_custom_key": True,
            "masked_key": masked,
            "mode": "custom"
        }
    return {
        "status": "ok",
        "has_custom_key": False,
        "masked_key": "",
        "mode": "school"
    }


@app.delete("/api/user/custom_api_key")
@app.delete("/cogni-scaffold/api/user/custom_api_key")
async def delete_custom_api_key_endpoint(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登入账号")

    clear_user_custom_api_key(str(user["id"]))
    return {"status": "ok", "message": "已解除专属 API Key 绑定，已切换回学校公共每日配额。"}
