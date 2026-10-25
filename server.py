import os
import re
import json
import asyncio
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv(override=True)

from core.presets import GOLDEN_PRESETS
from core.storage import (
    load_all_data,
    save_all_data,
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
    analyze_image_input,
    simulate_offline_stream
)
from core.latex_presets import LATEX_PRESETS_TREE
from core.guardrails import check_input_guardrail, check_output_refusal
from core.intent import classify_user_intent

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
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/cogni-scaffold/static", StaticFiles(directory="static"), name="static_subpath")

api_config = {
    "api_key": os.getenv("OPENAI_API_KEY", ""),
    "base_url": os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"),
    "model": os.getenv("MODEL_NAME", "deepseek-chat"),
    "temperature": 0.3
}

def get_store() -> dict:
    store = load_all_data()
    active_dict = store.setdefault("active_sessions", {})
    curr_id = store.get("current_session_id")
    if not curr_id or curr_id not in active_dict:
        if active_dict:
            curr_id = list(active_dict.keys())[0]
            store["current_session_id"] = curr_id
        else:
            preset = GOLDEN_PRESETS["math_derivative"]
            sess = create_new_session_data("📐 数学·导数极值讨论", preset["question"])
            sess["solver_blueprint"] = preset["solver_blueprint"]
            sess["dialogue_history"] = [
                {"role": "user", "content": preset["initial_student_input"]},
                {"role": "assistant", "content": preset["offline_simulation"][0]["tutor_response"]}
            ]
            sess["tutor_turns"] = 1
            sess["current_stage"] = 2
            sess["title_stage"] = 1
            sess["is_initialized"] = True
            active_dict[sess["id"]] = sess
            store["current_session_id"] = sess["id"]
            save_all_data(store)
    return store

def dispatch_variant_tier_data(session: dict, tier_num: int):
    diag = session.get("diagnostic_result") or {}
    tier_key = f"tier{tier_num}_variant"
    tier_data = diag.get(tier_key, {})
    
    raw_title = tier_data.get("title", f"第{to_chinese_num(tier_num)}关变式挑战")
    clean_title = re.sub(r'^(?:Tier\s*\d+\s*[:：]|第\s*\d+\s*关\s*[:：]|第\s*[一二三四五六七八九十]+\s*关\s*[:：])\s*', '', raw_title)
    full_title = f"第{to_chinese_num(tier_num)}关：{clean_title}"

    question = tier_data.get("question", diag.get("variant_question", "请分析约束反转后的系统动量或导数单调性。"))
    hint = tier_data.get("hint", diag.get("variant_hint", "注意边界与受力方向的矢量分解。"))

    # 规范化转义换行符，保留 \neq, \nabla 等合法 LaTeX 命令
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

def trigger_diagnosis_for_session(session: dict, offline_mode: bool = False):
    q_t = session.get("question", "")
    if offline_mode:
        if "动量" in q_t or "滑块" in q_t or "凹槽" in q_t:
            preset = GOLDEN_PRESETS.get("physics_momentum")
        elif "NaOH" in q_t or "CH_3COOH" in q_t or "中性" in q_t or "水解" in q_t:
            preset = GOLDEN_PRESETS.get("chemistry_equilibrium")
        elif "热敏电阻" in q_t or "比较器" in q_t or "三极管" in q_t:
            preset = GOLDEN_PRESETS.get("tech_logic_control")
        else:
            preset = GOLDEN_PRESETS.get("math_derivative")
        session["diagnostic_result"] = preset["preset_diagnostic"]
    else:
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


@app.get("/", response_class=HTMLResponse)
@app.get("/cogni-scaffold", response_class=HTMLResponse)
@app.get("/cogni-scaffold/", response_class=HTMLResponse)
async def serve_index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/api/bootstrap")
@app.get("/cogni-scaffold/api/bootstrap")
async def get_bootstrap():
    store = get_store()
    return {
        "store": store,
        "golden_presets": {
            k: {
                "title": v.get("title", k),
                "question": v.get("question", ""),
                "description": v.get("solver_blueprint", "")[:120]
            } for k, v in GOLDEN_PRESETS.items()
        },
        "latex_presets_tree": LATEX_PRESETS_TREE,
        "offline_demo": False
    }


@app.post("/api/sessions/create")
@app.post("/cogni-scaffold/api/sessions/create")
async def create_session():
    store = get_store()
    new_s = create_new_session_data(is_initialized=False, store=store)
    store["active_sessions"][new_s["id"]] = new_s
    store["current_session_id"] = new_s["id"]
    save_all_data(store)
    return {"status": "ok", "store": store}


@app.post("/api/sessions/switch")
@app.post("/cogni-scaffold/api/sessions/switch")
async def switch_session(data: dict):
    s_id = data.get("session_id")
    store = get_store()
    if s_id in store.get("active_sessions", {}):
        store["current_session_id"] = s_id
        save_all_data(store)
        return {"status": "ok", "store": store}
    raise HTTPException(status_code=404, detail="Session not found")


@app.post("/api/sessions/close")
@app.post("/cogni-scaffold/api/sessions/close")
async def close_session(data: dict):
    s_id = data.get("session_id")
    store = get_store()
    active = store.get("active_sessions", {})
    archived = store.setdefault("archived_sessions", {})
    if s_id in active:
        closed = active.pop(s_id)
        archived[s_id] = closed
        if store.get("current_session_id") == s_id:
            store["current_session_id"] = list(active.keys())[0] if active else None
        save_all_data(store)
        return {"status": "ok", "store": store, "closed_title": closed.get("title")}
    raise HTTPException(status_code=404, detail="Session not found")


@app.post("/api/sessions/toggle_star")
@app.post("/cogni-scaffold/api/sessions/toggle_star")
async def toggle_star(data: dict):
    s_id = data.get("session_id")
    store = get_store()
    active = store.get("active_sessions", {})
    archived = store.get("archived_sessions", {})
    target = active.get(s_id) or archived.get(s_id)
    if target:
        target["is_starred"] = not target.get("is_starred", False)
        save_all_data(store)
        return {"status": "ok", "is_starred": target["is_starred"]}
    raise HTTPException(status_code=404, detail="Session not found")


@app.post("/api/sessions/restore")
@app.post("/cogni-scaffold/api/sessions/restore")
async def restore_session(data: dict):
    s_id = data.get("session_id")
    store = get_store()
    archived = store.get("archived_sessions", {})
    active = store.setdefault("active_sessions", {})
    if s_id in archived:
        sess = archived.pop(s_id)
        active[s_id] = sess
        store["current_session_id"] = s_id
        save_all_data(store)
        return {"status": "ok", "store": store}
    raise HTTPException(status_code=404, detail="Archived session not found")


@app.post("/api/sessions/delete_archived")
@app.post("/cogni-scaffold/api/sessions/delete_archived")
async def delete_archived(data: dict):
    s_id = data.get("session_id")
    store = get_store()
    archived = store.get("archived_sessions", {})
    if s_id in archived:
        archived.pop(s_id, None)
        save_all_data(store)
        return {"status": "ok", "store": store}
    raise HTTPException(status_code=404, detail="Archived session not found")


@app.post("/api/theme")
@app.post("/cogni-scaffold/api/theme")
async def set_theme(data: dict):
    theme = data.get("theme", "dark")
    store = get_store()
    store["theme_mode"] = theme
    save_all_data(store)
    return {"status": "ok", "theme": theme}


@app.post("/api/sessions/init_question")
@app.post("/cogni-scaffold/api/sessions/init_question")
async def init_question(data: dict):
    s_id = data.get("session_id")
    question_text = data.get("question", "").strip()
    preset_key = data.get("preset_key")
    
    store = get_store()
    active = store.get("active_sessions", {})
    sess = active.get(s_id)
    if not sess:
        sess = create_new_session_data(is_initialized=False, store=store)
        active[sess["id"]] = sess
        store["current_session_id"] = sess["id"]

    if preset_key and preset_key in GOLDEN_PRESETS:
        preset = GOLDEN_PRESETS[preset_key]
        title_map = {
            "math_derivative": "📐 数学·导数极值分类",
            "physics_momentum": "⚖️ 物理·系统动量守恒",
            "chemistry_equilibrium": "🧪 化学·中性点电荷守恒",
            "tech_logic_control": "💻 技术·电控逻辑门限"
        }
        sess["title"] = title_map.get(preset_key, preset.get("title", "思维探索"))
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
            {"role": "assistant", "content": "我已经审视了这道题目。作为你的苏格拉底思维导师，我不会直接给出最终答案。请告诉我，看到这道题你的第一直觉是什么？脑海中浮现的第一个公式、定理或分析切入点是什么？"}
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

    save_all_data(store)
    return {"status": "ok", "store": store}


@app.post("/api/sessions/reset")
@app.post("/cogni-scaffold/api/sessions/reset")
async def reset_session(data: dict):
    s_id = data.get("session_id")
    store = get_store()
    sess = store.get("active_sessions", {}).get(s_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    sess["dialogue_history"] = [
        {"role": "assistant", "content": "我已经审视了这道题目。作为你的苏格拉底思维导师，我不会直接给出最终答案。请告诉我，看到这道题你的第一直觉是什么？脑海中浮现的第一个公式、定理或分析切入点是什么？"}
    ]
    sess["tutor_turns"] = 0
    sess["current_stage"] = 1
    sess["diagnostic_result"] = None
    sess["transfer_eval_result"] = None
    sess["current_variant_tier"] = 1
    save_all_data(store)
    return {"status": "ok", "store": store}


_session_tier_locks: Dict[str, asyncio.Lock] = {}

def get_session_lock(session_id: str) -> asyncio.Lock:
    if session_id not in _session_tier_locks:
        _session_tier_locks[session_id] = asyncio.Lock()
    return _session_tier_locks[session_id]


@app.post("/api/sessions/verify")
@app.post("/cogni-scaffold/api/sessions/verify")
async def verify_session(data: dict):
    s_id = data.get("session_id")
    store = get_store()
    sess = store.get("active_sessions", {}).get(s_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
        
    lock = get_session_lock(s_id)
    if lock.locked():
        return {"status": "ok", "store": store}

    async with lock:
        store = get_store()
        sess = store.get("active_sessions", {}).get(s_id)
        if sess.get("diagnostic_result"):
            return {"status": "ok", "store": store}
        trigger_diagnosis_for_session(sess, offline_mode=False)
        save_all_data(store)
        return {"status": "ok", "store": store}


@app.post("/api/sessions/next_tier")
@app.post("/cogni-scaffold/api/sessions/next_tier")
async def next_tier(data: dict):
    s_id = data.get("session_id")
    store = get_store()
    sess = store.get("active_sessions", {}).get(s_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
        
    lock = get_session_lock(s_id)
    if lock.locked():
        # 并发防抖：如果已有出题任务正在处理，直接返回当前状态，绝不允许跳关
        return {"status": "ok", "store": store}

    async with lock:
        store = get_store()
        sess = store.get("active_sessions", {}).get(s_id)
        diag = sess.get("diagnostic_result") or {}
        existing_tiers = [
            int(k.replace("tier", "").replace("_variant", ""))
            for k in diag.keys()
            if k.startswith("tier") and k.endswith("_variant") and k.replace("tier", "").replace("_variant", "").isdigit()
        ]
        max_t = max(existing_tiers, default=3)
        curr_tier = sess.get("current_variant_tier", 1)

        # 严格幂等防重：只有全部关卡通关后 (curr_tier > max_t)，才允许生成新题
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
        save_all_data(store)
        return {"status": "ok", "store": store}


@app.post("/api/sessions/upload_image")
@app.post("/cogni-scaffold/api/sessions/upload_image")
async def upload_image(
    image: UploadFile = File(...),
    mode: str = Form("question"),
    question_context: str = Form("")
):
    try:
        content = await image.read()
        recognized_text = analyze_image_input(content, mode, question_context, api_config)
        return {"status": "ok", "text": recognized_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sessions/{session_id}/chat/stream")
@app.get("/cogni-scaffold/api/sessions/{session_id}/chat/stream")
async def chat_stream(session_id: str, student_text: str):
    store = get_store()
    sess = store.get("active_sessions", {}).get(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    student_text = student_text.strip()
    if not student_text:
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    async def event_generator():
        nonlocal store, sess
        try:
            # 1. 记录学生输入
            sess["dialogue_history"].append({"role": "user", "content": student_text})

            # 【断路器 1：前置安全与合规检测 (Fast Circuit Breaker)】
            is_blocked, refusal_text = check_input_guardrail(student_text)
            if is_blocked:
                # 触发断路硬熔断：直接返回标准拒答，绝不调用大模型，绝不推进状态机，绝不出题！
                chunk_size = 12
                for i in range(0, len(refusal_text), chunk_size):
                    chunk = refusal_text[i:i+chunk_size]
                    yield f"data: {json.dumps({'type': 'chunk', 'content': chunk, 'role': 'assistant'}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.01)

                sess["dialogue_history"].append({"role": "assistant", "content": refusal_text})
                # 状态原地锁定，不推进任何关卡或轮次
                save_all_data(store)
                yield f"data: {json.dumps({'type': 'done', 'session': sess, 'store': store}, ensure_ascii=False)}\n\n"
                return

            # 【意图与早退路由检测 (Intent & Early-Exit Routing)】
            intent_type, intent_guidance = classify_user_intent(student_text, sess.get("question", ""))
            
            # 1. 情绪发泄、粗俗语拦截：温和安抚并重设边界，严格不推新题
            if intent_type == "PROFANITY":
                chunk_size = 12
                for i in range(0, len(intent_guidance), chunk_size):
                    chunk = intent_guidance[i:i+chunk_size]
                    yield f"data: {json.dumps({'type': 'chunk', 'content': chunk, 'role': 'assistant'}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.01)

                sess["dialogue_history"].append({"role": "assistant", "content": intent_guidance})
                save_all_data(store)
                yield f"data: {json.dumps({'type': 'done', 'session': sess, 'store': store}, ensure_ascii=False)}\n\n"
                return

            # 2. Meta 纠错 / 上下文脱节 / 题目关联质疑：暂停答疑与判题流，由导师出面解释认知同构逻辑，严禁误判
            if intent_type == "META_QUESTION":
                chunk_size = 12
                for i in range(0, len(intent_guidance), chunk_size):
                    chunk = intent_guidance[i:i+chunk_size]
                    yield f"data: {json.dumps({'type': 'chunk', 'content': chunk, 'role': 'assistant'}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.01)

                sess["dialogue_history"].append({"role": "assistant", "content": intent_guidance})
                save_all_data(store)
                yield f"data: {json.dumps({'type': 'done', 'session': sess, 'store': store}, ensure_ascii=False)}\n\n"
                return

            # 3. 显式脱轨闲聊：优雅拉回，状态原地锁定，不推进关卡
            if intent_type == "OFF_TOPIC":
                chunk_size = 12
                for i in range(0, len(intent_guidance), chunk_size):
                    chunk = intent_guidance[i:i+chunk_size]
                    yield f"data: {json.dumps({'type': 'chunk', 'content': chunk, 'role': 'assistant'}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.01)

                sess["dialogue_history"].append({"role": "assistant", "content": intent_guidance})
                save_all_data(store)
                yield f"data: {json.dumps({'type': 'done', 'session': sess, 'store': store}, ensure_ascii=False)}\n\n"
                return

            # 判断是否处于变式闯关阶段 (Stage >= 4)
            if sess.get("current_stage", 1) >= 4:
                diag = sess.get("diagnostic_result") or {}
                defined_tiers = [
                    int(k.replace("tier", "").replace("_variant", ""))
                    for k in diag.keys()
                    if k.startswith("tier") and k.endswith("_variant") and k.replace("tier", "").replace("_variant", "").isdigit()
                ]
                max_defined = max(defined_tiers, default=3)
                curr_tier = sess.get("current_variant_tier", 1)

                if curr_tier > max_defined:
                    # 全线通关后，学生输入新内容触发更高阶全新关卡
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
                    save_all_data(store)

                    # 模拟打字机流式展示新出题目
                    chunk_size = 12
                    for i in range(0, len(prompt_msg), chunk_size):
                        chunk = prompt_msg[i:i+chunk_size]
                        yield f"data: {json.dumps({'type': 'chunk', 'content': chunk, 'role': 'assistant_variant'}, ensure_ascii=False)}\n\n"
                        await asyncio.sleep(0.01)

                    yield f"data: {json.dumps({'type': 'done', 'session': sess, 'store': store}, ensure_ascii=False)}\n\n"
                    return

                tier_data = diag.get(f"tier{curr_tier}_variant", {})
                var_q = tier_data.get("question", "变式题")
                var_h = tier_data.get("hint", "")

                # 评估回答或提供启发线索
                eval_text = evaluate_transfer_answer(var_q, var_h, student_text, api_config)
                
                # 模拟打字机流式输出给前端
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

                save_all_data(store)
                yield f"data: {json.dumps({'type': 'done', 'session': sess, 'store': store}, ensure_ascii=False)}\n\n"

            else:
                # 阶段 1~3：启发式引导
                full_response = ""
                temp_history = list(sess["dialogue_history"])
                
                # 使用真实模型流式生成
                for chunk in stream_tutor_response(temp_history, sess.get("solver_blueprint", ""), api_config):
                    full_response += chunk
                    clean_chunk = chunk.replace("[TRIGGER_DIAGNOSIS]", "")
                    if clean_chunk:
                        yield f"data: {json.dumps({'type': 'chunk', 'content': clean_chunk, 'role': 'assistant'}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.01)

                clean_full = full_response.replace("[TRIGGER_DIAGNOSIS]", "").strip()
                sess["dialogue_history"].append({"role": "assistant", "content": clean_full})
                sess["tutor_turns"] += 1

                # 首次两段式标题进化
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

                # 【断路器 2：后置大模型拒答熔断检查】
                is_refusal = check_output_refusal(clean_full)

                # 【状态机解耦：前提条件严格校验】
                # 只有在：1. 未被后置熔断 2. 非低信息量输入 3. 轮次>=2 4. 模型带有突破标识 时才允许触发诊断出题
                can_trigger_diagnosis = (
                    not is_refusal
                    and intent_type not in ["LOW_INFO", "DEMAND_ANSWER"]
                    and sess.get("tutor_turns", 0) >= 2
                    and "[TRIGGER_DIAGNOSIS]" in full_response
                )

                if can_trigger_diagnosis:
                    trigger_diagnosis_for_session(sess, offline_mode=False)

                save_all_data(store)
                yield f"data: {json.dumps({'type': 'done', 'session': sess, 'store': store}, ensure_ascii=False)}\n\n"

        except Exception as err:
            err_msg = f"⚠️ 连接处理异常：{str(err)}。请点击重试。"
            yield f"data: {json.dumps({'type': 'chunk', 'content': err_text if 'err_text' in locals() else err_msg, 'role': 'assistant'}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'session': sess, 'store': store}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
