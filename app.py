"""
CogniScaffold (智构思维导师)
Streamlit 极简双栏人机交互界面
核心升级：
1. 顶部沉浸式多标签工作台（AI 自动提炼短标题 + 收藏星标 + 悬停关闭归档 + ➕新建会话）
2. 独立「📚 历史归档库」浮层，支持随时查看复盘过往推导、盲区画像与一键恢复
3. 本地 JSON 数据持久化（data/history_store.json），刷新不丢失
4. 弹性微图景启发制（150-250字），彻底解绑干瘪的 100 字限制
5. 两段式 AI 标题进化（首轮提炼学科+题型，结算追加错因定性）
6. 三阶渐进变式矩阵与自信豁免通关
"""

import os
import re
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

load_dotenv(override=True)

from core.presets import GOLDEN_PRESETS
from core.storage import (
    load_all_data,
    save_all_data,
    create_new_session_data,
    generate_session_title
)
from components.chrome_tabs import render_chrome_tabs
from core.engine import (
    generate_solver_blueprint,
    stream_tutor_response,
    generate_diagnostic_report,
    evaluate_transfer_answer,
    generate_next_tier_variant,
    analyze_image_input,
    simulate_offline_stream
)
from core.latex_presets import LATEX_PRESETS_TREE


def format_chat_markdown(text: str) -> str:
    """清理并转换 Markdown 标题，防止 #、### 源码在对话气泡中外露或排版破损"""
    if not text:
        return ""
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            clean_title = stripped.lstrip("#").strip()
            lines.append(f"**{clean_title}**")
        else:
            lines.append(line)
    return "\n".join(lines)


# 页面基础配置
st.set_page_config(
    page_title="CogniScaffold | 智构思维导师",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 注入高质感现代工作台与多标签栏 CSS
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
    
    /* 彻底隐藏左侧边栏与展开按钮，防止 API 与配置外露 */
    [data-testid="collapsedControl"] {
        display: none !important;
    }
    section[data-testid="stSidebar"] {
        display: none !important;
    }
    
    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    
    .block-container {
        padding-top: 1.5rem !important;
        padding-bottom: 2rem !important;
    }
    
    header[data-testid="stHeader"] {
        background-color: transparent !important;
    }
    
    /* 顶部工作台多标签栏容器 */
    .tabbar-wrapper {
        background: rgba(15, 23, 42, 0.7);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 10px;
        padding: 6px 12px;
        margin-bottom: 1rem;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    
    /* 右侧列固定常驻 */
    div[data-testid="column"]:nth-of-type(2) {
        position: sticky !important;
        top: 2rem !important;
        align-self: flex-start !important;
    }
    
    /* 步骤指示器 (Stepper) */
    .stepper-box {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 12px 14px;
        background: rgba(22, 27, 34, 0.6);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 10px;
        margin-bottom: 12px;
    }
    .step-node {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 4px;
        z-index: 2;
    }
    .step-dot {
        width: 26px;
        height: 26px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 0.75rem;
        font-weight: 700;
        transition: all 0.2s ease;
    }
    .step-dot.done {
        background: rgba(16, 185, 129, 0.2);
        color: #34d399;
        border: 1.5px solid #10b981;
    }
    .step-dot.current {
        background: #2563eb;
        color: #ffffff;
        border: 1.5px solid #60a5fa;
        box-shadow: 0 0 10px rgba(59, 130, 246, 0.5);
    }
    .step-dot.pending {
        background: rgba(255, 255, 255, 0.05);
        color: #64748b;
        border: 1.5px solid rgba(255, 255, 255, 0.15);
    }
    .step-text {
        font-size: 0.74rem;
        color: #94a3b8;
    }
    .step-text.active-text {
        color: #60a5fa;
        font-weight: 600;
    }
    .step-connector {
        flex: 1;
        height: 2px;
        background: rgba(255, 255, 255, 0.1);
        margin: 0 6px;
        margin-bottom: 18px;
    }
    .step-connector.done {
        background: #10b981;
    }

    /* 对话气泡样式：学生靠右中性灰底无边框，导师靠左带亮蓝强调线，两侧 82% 对称 */
    div[data-testid="stChatMessage"] {
        padding: 4px 6px !important;
        margin-bottom: 6px !important;
        background: transparent !important;
    }
    div[data-testid="stChatMessage"]:has(.student-msg-marker) {
        flex-direction: row-reverse !important;
    }
    div[data-testid="stChatMessage"]:has(.student-msg-marker) div[data-testid="stChatMessageContent"] {
        background: rgba(255, 255, 255, 0.07) !important;
        border: none !important;
        border-radius: 12px 2px 12px 12px !important;
        max-width: 82% !important;
        padding: 10px 15px !important;
        margin-left: auto !important;
        margin-right: 6px !important;
        color: #e2e8f0 !important;
    }
    div[data-testid="stChatMessage"]:has(.tutor-msg-marker) div[data-testid="stChatMessageContent"],
    div[data-testid="stChatMessage"]:has(.variant-msg-marker) div[data-testid="stChatMessageContent"] {
        background: rgba(22, 27, 34, 0.9) !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-left: 3px solid #3b82f6 !important;
        border-radius: 2px 12px 12px 12px !important;
        max-width: 82% !important;
        padding: 11px 16px !important;
        margin-right: auto !important;
        margin-left: 6px !important;
        color: #f8fafc !important;
    }
    
    .variant-divider-card {
        background: rgba(16, 185, 129, 0.1);
        border: 1px dashed rgba(16, 185, 129, 0.4);
        border-radius: 8px;
        padding: 8px 14px;
        margin: 0.8rem 0;
        text-align: center;
    }
    
    .dashboard-card {
        background: rgba(22, 27, 34, 0.7);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 8px;
        padding: 12px 14px;
        margin-bottom: 0.7rem;
        color: #f1f5f9 !important;
    }
    .dashboard-card h5 {
        color: #f8fafc !important;
        font-size: 0.92rem;
        font-weight: 600;
    }

    .latex-preview-card {
        background: transparent;
        border: none;
        padding: 4px 0 2px 0;
        margin-top: 6px;
        margin-bottom: 2px;
        font-size: 0.85rem;
    }

    /* 文本输入域增强：15px 字号 + 高对比度占位符 + 舒适行高 */
    div[data-testid="stTextArea"] textarea {
        font-size: 15px !important;
        line-height: 1.6 !important;
        color: #f8fafc !important;
        background: rgba(15, 23, 42, 0.75) !important;
        border: 1px solid rgba(255, 255, 255, 0.12) !important;
        border-radius: 8px !important;
        padding: 10px 14px !important;
    }
    div[data-testid="stTextArea"] textarea::placeholder {
        color: #94a3b8 !important;
        font-size: 14.5px !important;
    }
    div[data-testid="stTextArea"] textarea:focus {
        border-color: #3b82f6 !important;
        box-shadow: 0 0 0 1px #3b82f6 !important;
    }

    /* 图标 Popover 纯图标微调：隐藏下拉箭头，紧凑方块按钮并排紧贴右边缘 */
    div[data-testid="stPopover"] {
        width: 100% !important;
        display: flex !important;
        justify-content: center !important;
    }
    div[data-testid="stPopover"] button {
        padding: 0 4px !important;
        width: 100% !important;
        min-width: 32px !important;
        min-height: 28px !important;
        height: 28px !important;
        font-size: 1rem !important;
        font-weight: 600 !important;
        background: rgba(255, 255, 255, 0.06) !important;
        border: 1px solid rgba(255, 255, 255, 0.15) !important;
        border-radius: 6px !important;
        color: #f1f5f9 !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
    }
    div[data-testid="stPopover"] button > div + div,
    div[data-testid="stPopover"] button span[title="Expand"],
    div[data-testid="stPopover"] button svg {
        display: none !important;
    }
    div[data-testid="stPopover"] button:hover {
        background: rgba(255, 255, 255, 0.12) !important;
        border-color: #60a5fa !important;
        color: #ffffff !important;
    }

    /* 思维轨迹组件样式 */
    .trajectory-container {
        background: rgba(22, 27, 34, 0.5);
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 8px;
        padding: 10px 12px;
        margin-bottom: 0.7rem;
    }
    .trajectory-item {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 0.8rem;
        padding: 4px 0;
        border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    }
    .trajectory-item:last-child {
        border-bottom: none;
        padding-bottom: 0;
    }
    .trajectory-tag {
        padding: 1px 6px;
        border-radius: 4px;
        font-size: 0.7rem;
        font-weight: 600;
        white-space: nowrap;
    }
    .tag-stuck { background: rgba(239, 68, 68, 0.16); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.3); }
    .tag-advance { background: rgba(59, 130, 246, 0.16); color: #93c5fd; border: 1px solid rgba(59, 130, 246, 0.3); }
    .tag-break { background: rgba(16, 185, 129, 0.16); color: #6ee7b7; border: 1px solid rgba(16, 185, 129, 0.3); }

    /* 禁用状态按钮：虚线边框 + 明显未解锁感 */
    button:disabled {
        border: 1px dashed rgba(255, 255, 255, 0.22) !important;
        background: rgba(255, 255, 255, 0.02) !important;
        color: rgba(255, 255, 255, 0.38) !important;
        cursor: not-allowed !important;
    }

    /* 核心卡片容器 (border=True 容器统一质感) */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background: rgba(22, 27, 34, 0.72) !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 12px !important;
        padding: 16px 20px !important;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3) !important;
    }

    /* Primary 按钮精致微动效 */
    button[kind="primary"] {
        background: linear-gradient(135deg, #2563eb, #1d4ed8) !important;
        border: 1px solid rgba(255, 255, 255, 0.15) !important;
        font-weight: 500 !important;
        letter-spacing: 0.3px !important;
        box-shadow: 0 4px 12px rgba(37, 99, 235, 0.25) !important;
        transition: all 0.15s ease !important;
    }
    button[kind="primary"]:hover {
        background: linear-gradient(135deg, #3b82f6, #2563eb) !important;
        box-shadow: 0 6px 16px rgba(59, 130, 246, 0.4) !important;
        transform: translateY(-1px) !important;
    }

    /* Toolbar icon columns: force compact width */
    div[data-testid="stHorizontalBlock"]:has(div[data-testid="stPopover"]) > div[data-testid="column"]:not(:first-child) {
        flex: 0 0 36px !important;
        min-width: 36px !important;
        max-width: 36px !important;
        padding: 0 2px !important;
    }

    /* Popover panel style for comprehensive keypad */
    div[data-testid="stPopoverBody"] {
        min-width: 480px !important;
        max-width: 540px !important;
        background: #0d1117 !important;
        border: 1px solid rgba(255, 255, 255, 0.12) !important;
        border-radius: 12px !important;
        padding: 14px 16px !important;
        box-shadow: 0 16px 36px rgba(0, 0, 0, 0.55) !important;
    }

    /* Popover keypad button style */
    div[data-testid="stPopoverBody"] button:not([kind="primary"]) {
        min-height: 36px !important;
        padding: 2px 4px !important;
        font-size: 0.88rem !important;
        font-family: "JetBrains Mono", monospace, sans-serif !important;
        background: rgba(255, 255, 255, 0.04) !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 6px !important;
        transition: all 0.15s ease !important;
    }
    div[data-testid="stPopoverBody"] button:not([kind="primary"]):hover {
        background: rgba(59, 130, 246, 0.18) !important;
        border-color: rgba(59, 130, 246, 0.45) !important;
        color: #93c5fd !important;
        transform: translateY(-1px) !important;
    }
</style>
""", unsafe_allow_html=True)


# ==========================================
# 顶层持久化数据初始化 (Store Initialization)
# ==========================================
if "app_store" not in st.session_state:
    loaded = load_all_data()
    # 如果初次启动没有任何活动标签，默认注入一个数学经典案例
    if not loaded.get("active_sessions"):
        sess = create_new_session_data("📐 数学·导数极值讨论", GOLDEN_PRESETS["math_derivative"]["question"])
        sess["solver_blueprint"] = GOLDEN_PRESETS["math_derivative"]["solver_blueprint"]
        sess["dialogue_history"] = [
            {"role": "user", "content": GOLDEN_PRESETS["math_derivative"]["initial_student_input"]},
            {"role": "assistant", "content": GOLDEN_PRESETS["math_derivative"]["offline_simulation"][0]["tutor_response"]}
        ]
        sess["tutor_turns"] = 1
        sess["current_stage"] = 2
        sess["title_stage"] = 1
        loaded["active_sessions"] = {sess["id"]: sess}
        loaded["current_session_id"] = sess["id"]
        save_all_data(loaded)
    st.session_state.app_store = loaded

# 确保有激活的 session
store = st.session_state.app_store
active_dict = store.setdefault("active_sessions", {})
curr_id = store.get("current_session_id")
if not curr_id or curr_id not in active_dict:
    if active_dict:
        curr_id = list(active_dict.keys())[0]
        store["current_session_id"] = curr_id
    else:
        new_s = create_new_session_data()
        active_dict[new_s["id"]] = new_s
        store["current_session_id"] = new_s["id"]
        curr_id = new_s["id"]
        save_all_data(store)

cur_session = active_dict[curr_id]

# 暂存输入框清空状态
if "pending_thought_input" in st.session_state:
    st.session_state["student_thought_input"] = st.session_state.pop("pending_thought_input")
if "student_thought_input" not in st.session_state:
    st.session_state["student_thought_input"] = ""

# 查看历史归档弹窗开关
if "show_history_modal" not in st.session_state:
    st.session_state.show_history_modal = False


# ==========================================
# 页面顶部：像素级复刻 Chrome 原生多标签栏 (Tab Bar)
# ==========================================
chrome_tabs_data = []
for s_id, s_obj in active_dict.items():
    chrome_tabs_data.append({
        "id": s_id,
        "title": s_obj.get("title", "新解题会话"),
        "is_starred": s_obj.get("is_starred", False)
    })

tab_event = render_chrome_tabs(
    tabs=chrome_tabs_data,
    active_id=curr_id,
    archived_count=len(store.get("archived_sessions", {})),
    key="top_chrome_tabs_widget"
)

if tab_event:
    event_id = tab_event.get("eventId")
    last_event_id = st.session_state.get("last_handled_tab_event_id")
    if event_id and event_id != last_event_id:
        st.session_state["last_handled_tab_event_id"] = event_id
        action = tab_event.get("action")
        payload = tab_event.get("payload")
        if action == "select_tab":
            if store.get("current_session_id") != payload:
                store["current_session_id"] = payload
                save_all_data(store)
                st.rerun()
        elif action == "close_tab":
            arch = store.setdefault("archived_sessions", {})
            if payload in active_dict:
                closed_s = active_dict.pop(payload)
                arch[payload] = closed_s
                if store.get("current_session_id") == payload:
                    store["current_session_id"] = list(active_dict.keys())[0] if active_dict else None
                save_all_data(store)
                st.toast(f"已将会话【{closed_s.get('title')}】归档至历史记录库", icon="🗂️")
                st.rerun()
        elif action == "toggle_star":
            if payload in active_dict:
                active_dict[payload]["is_starred"] = not active_dict[payload].get("is_starred", False)
                save_all_data(store)
                st.rerun()
        elif action == "add_tab":
            new_s = create_new_session_data(is_initialized=False, store=store)
            active_dict[new_s["id"]] = new_s
            store["current_session_id"] = new_s["id"]
            save_all_data(store)
            st.rerun()
        elif action == "open_history":
            st.session_state.show_history_modal = not st.session_state.show_history_modal
            st.rerun()

st.markdown("<div style='margin-bottom: 0.5rem;'></div>", unsafe_allow_html=True)


# ==========================================
# 历史归档库展开抽屉 (History Drawer)
# ==========================================
if st.session_state.show_history_modal:
    with st.expander("📚 历史归档与收藏库 (点击收起)", expanded=True):
        h_tab1, h_tab2 = st.tabs(["🌟 我的收藏 (Starred)", "🗂️ 归档历史 (Archived)"])
        
        # 收藏列表
        with h_tab1:
            starred_sessions = [s for s in list(active_dict.values()) + list(store.get("archived_sessions", {}).values()) if s.get("is_starred")]
            if starred_sessions:
                for st_sess in starred_sessions:
                    c1, c2, c3 = st.columns([6, 2, 2])
                    with c1:
                        st.markdown(f"**{st_sess.get('title')}** `({st_sess.get('created_at', '')})`")
                        st.caption(f"题目：{st_sess.get('question')[:45]}...")
                    with c2:
                        stage_txt = f"阶段 {st_sess.get('current_stage')} 推进"
                        st.caption(stage_txt)
                    with c3:
                        if st.button("恢复到工作台", key=f"restore_star_{st_sess['id']}"):
                            # 激活
                            active_dict[st_sess["id"]] = st_sess
                            store["current_session_id"] = st_sess["id"]
                            save_all_data(store)
                            st.session_state.show_history_modal = False
                            st.rerun()
            else:
                st.info("暂无收藏会话，点击标签栏上的 ★ 即可收藏重要推导。")

        # 归档历史列表
        with h_tab2:
            arch_dict = store.get("archived_sessions", {})
            if arch_dict:
                for a_id, a_sess in list(arch_dict.items()):
                    c1, c2, c3, c4 = st.columns([5, 2, 2, 1])
                    with c1:
                        st.markdown(f"**{a_sess.get('title')}** `({a_sess.get('created_at', '')})`")
                        st.caption(f"{a_sess.get('question')[:40]}...")
                    with c2:
                        diag_txt = a_sess.get("diagnostic_result", {}).get("blindspot_type", "探索中") if a_sess.get("diagnostic_result") else "未结算"
                        st.caption(f"错因定性: #{diag_txt[:8]}")
                    with c3:
                        if st.button("一键恢复", key=f"restore_arch_{a_id}"):
                            active_dict[a_id] = arch_dict.pop(a_id)
                            store["current_session_id"] = a_id
                            save_all_data(store)
                            st.session_state.show_history_modal = False
                            st.rerun()
                    with c4:
                        if st.button("🗑️", key=f"del_arch_{a_id}", help="永久删除此归档"):
                            arch_dict.pop(a_id, None)
                            save_all_data(store)
                            st.rerun()
            else:
                st.info("暂无归档会话。点击标签栏上的 ✕ 即可将完成的题目归档至此。")
    st.markdown("---")


# ==========================================
# 侧边栏：API配置与演示控制
# ==========================================
with st.sidebar:
    st.markdown("### 🧭 CogniScaffold 控制台")
    
    offline_demo = st.toggle("🛡️ 演练安全仓模式 (Offline Demo)", value=False, help="开启后使用内建真实案例仿真推演，断网可用；关闭后连接真实的 DeepSeek 大模型推理。")
    if offline_demo:
        st.markdown("""
        <div style="display: flex; align-items: center; gap: 8px; font-size: 0.82rem; color: #cbd5e1; margin: 4px 0 12px 0; padding: 6px 10px; background: rgba(245, 158, 11, 0.08); border: 1px solid rgba(245, 158, 11, 0.2); border-radius: 6px;">
            <span style="display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: #f59e0b; box-shadow: 0 0 6px rgba(245, 158, 11, 0.7);"></span>
            <span>已启用离线仿真演练</span>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div style="display: flex; align-items: center; gap: 8px; font-size: 0.82rem; color: #cbd5e1; margin: 4px 0 12px 0; padding: 6px 10px; background: rgba(16, 185, 129, 0.08); border: 1px solid rgba(16, 185, 129, 0.2); border-radius: 6px;">
            <span style="display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: #10b981; box-shadow: 0 0 6px rgba(16, 185, 129, 0.7);"></span>
            <span>已连接 DeepSeek 推理引擎</span>
        </div>
        """, unsafe_allow_html=True)

    api_config = {
        "api_key": os.getenv("OPENAI_API_KEY", "sk-00dd7d26d38f4eb285d020a79ec72364"),
        "base_url": os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"),
        "model": os.getenv("MODEL_NAME", "deepseek-chat"),
        "temperature": 0.3
    }

    def initialize_session_with_question(session, question_text, api_cfg, offline_mode=False):
        session["question"] = question_text
        session["is_initialized"] = True
        session["title_stage"] = 1
        session["dialogue_history"] = [
            {"role": "assistant", "content": "我已经审视了这道题目。作为你的苏格拉底思维导师，我不会直接给出最终答案。请告诉我，看到这道题你的第一直觉是什么？脑海中浮现的第一个公式、定理或分析切入点是什么？"}
        ]
        session["tutor_turns"] = 0
        session["current_stage"] = 1
        session["diagnostic_result"] = None
        session["transfer_eval_result"] = None
        session["current_variant_tier"] = 1
        
        if offline_mode:
            if "导数" in question_text or "ln" in question_text:
                session["title"] = "📐 数学·导数极值分类"
                session["solver_blueprint"] = GOLDEN_PRESETS["math_derivative"]["solver_blueprint"]
            elif "动量" in question_text or "滑块" in question_text:
                session["title"] = "⚖️ 物理·系统动量守恒"
                session["solver_blueprint"] = GOLDEN_PRESETS["physics_momentum"]["solver_blueprint"]
            else:
                session["title"] = "💡 探索·数理思维突破"
                session["solver_blueprint"] = f"核心分析：针对【{question_text[:30]}】进行概念剖析与反例引导。"
        else:
            with st.spinner("正在基于认知心理学模型拆解解题蓝图与潜在暗坑..."):
                session["title"] = generate_session_title(
                    question=question_text,
                    dialogue_history=[],
                    diagnostic_result=None,
                    current_title=session.get("title", "会话"),
                    title_stage=1,
                    api_config=api_cfg
                )
                session["solver_blueprint"] = generate_solver_blueprint(question_text, api_cfg)

    with st.expander("➕ 录入新题 / 新建会话", expanded=False):
        tab_text_q, tab_img_q = st.tabs(["✍️ 文字输入", "📸 拍照/传图"])
        
        with tab_text_q:
            new_q_input = st.text_area("输入新题目内容 (支持 LaTeX)：", placeholder="在此输入新题目文字，支持直接使用 LaTeX 科学公式...", height=80, key="new_text_q_in")
            if st.button("🚀 载入文字新题并开启陪练", use_container_width=True):
                if new_q_input.strip():
                    initialize_session_with_question(cur_session, new_q_input.strip(), api_config, offline_demo)
                    save_all_data(store)
                    st.session_state["pending_thought_input"] = ""
                    st.rerun()

        with tab_img_q:
            up_q_file = st.file_uploader("上传题目图片", type=["png", "jpg", "jpeg"], key="up_q_img")
            cam_q_file = st.camera_input("拍照", key="cam_q_img")
            active_q_img = up_q_file or cam_q_file
            if active_q_img is not None:
                st.image(active_q_img, caption="待识别题目照片", use_column_width=True)
                if st.button("🔍 智能识别题目并开启陪练", use_container_width=True):
                    img_bytes = active_q_img.getvalue()
                    recognized_q = analyze_image_input(img_bytes, "question", "", api_config)
                    initialize_session_with_question(cur_session, recognized_q, api_config, offline_demo)
                    save_all_data(store)
                    st.session_state["pending_thought_input"] = ""
                    st.rerun()

    st.markdown("---")
    st.markdown("#### 🚀 一键注入黄金案例")
    
    col_demo1, col_demo2 = st.columns(2)
    with col_demo1:
        if st.button("📐 导数定义域", use_container_width=True):
            preset = GOLDEN_PRESETS["math_derivative"]
            cur_session["title"] = "📐 数学·导数极值分类"
            cur_session["is_initialized"] = True
            cur_session["title_stage"] = 1
            cur_session["question"] = preset["question"]
            cur_session["solver_blueprint"] = preset["solver_blueprint"]
            cur_session["dialogue_history"] = [
                {"role": "user", "content": preset["initial_student_input"]},
                {"role": "assistant", "content": preset["offline_simulation"][0]["tutor_response"]}
            ]
            cur_session["tutor_turns"] = 1
            cur_session["current_stage"] = 2
            cur_session["diagnostic_result"] = None
            cur_session["transfer_eval_result"] = None
            cur_session["current_variant_tier"] = 1
            save_all_data(store)
            st.session_state["pending_thought_input"] = ""
            st.rerun()

    with col_demo2:
        if st.button("⚖️ 动量守恒", use_container_width=True):
            preset = GOLDEN_PRESETS["physics_momentum"]
            cur_session["title"] = "⚖️ 物理·系统动量守恒"
            cur_session["is_initialized"] = True
            cur_session["title_stage"] = 1
            cur_session["question"] = preset["question"]
            cur_session["solver_blueprint"] = preset["solver_blueprint"]
            cur_session["dialogue_history"] = [
                {"role": "user", "content": preset["initial_student_input"]},
                {"role": "assistant", "content": preset["offline_simulation"][0]["tutor_response"]}
            ]
            cur_session["tutor_turns"] = 1
            cur_session["current_stage"] = 2
            cur_session["diagnostic_result"] = None
            cur_session["transfer_eval_result"] = None
            cur_session["current_variant_tier"] = 1
            save_all_data(store)
            st.session_state["pending_thought_input"] = ""
            st.rerun()

    st.markdown("---")
    if st.button("🔄 重置当前问答", use_container_width=True):
        cur_session["dialogue_history"] = []
        cur_session["tutor_turns"] = 0
        cur_session["current_stage"] = 1
        cur_session["diagnostic_result"] = None
        cur_session["transfer_eval_result"] = None
        cur_session["current_variant_tier"] = 1
        save_all_data(store)
        st.session_state["pending_thought_input"] = ""
        st.rerun()


# ==========================================
# 触发阶段 4：发布指定 Tier 的变式题与更高阶挑战
# ==========================================
def dispatch_variant_tier(tier_num: int):
    diag = cur_session.get("diagnostic_result") or {}
    tier_key = f"tier{tier_num}_variant"
    tier_data = diag.get(tier_key, {})
    
    title = tier_data.get("title", f"第 {tier_num} 阶变式挑战")
    question = tier_data.get("question", diag.get("variant_question", "请分析约束反转后的系统动量或导数单调性。"))
    hint = tier_data.get("hint", diag.get("variant_hint", "注意边界与受力方向的矢量分解。"))
    
    # 统一前置单条阶段横幅
    cur_session["dialogue_history"].append({
        "role": "divider",
        "content": f"阶段 4 · {title}"
    })
    
    prompt_msg = (
        f"**📝 {title}**\n\n"
        f"{question}\n\n"
        f"> 💡 **考查要点与暗坑提示**：{hint}\n\n"
        f"**请在下方写出你的推导思路或结论（若觉得太简单可直接表明）：**"
    )
    cur_session["dialogue_history"].append({
        "role": "assistant_variant",
        "content": prompt_msg
    })
    cur_session["current_stage"] = 4
    cur_session["current_variant_tier"] = tier_num
    save_all_data(store)


def trigger_next_higher_tier():
    """动态生成并发布更高难度的进阶变式题（支持三阶之后不断再来一题，难度层层递进）"""
    diag = cur_session.get("diagnostic_result") or {}
    existing_tiers = [
        int(k.replace("tier", "").replace("_variant", ""))
        for k in diag.keys()
        if k.startswith("tier") and k.endswith("_variant") and k.replace("tier", "").replace("_variant", "").isdigit()
    ]
    max_t = max(existing_tiers, default=3)
    next_t = max_t + 1
    
    with st.spinner(f"正在基于认知模型生成第 {next_t} 阶更高难度巅峰挑战..."):
        new_variant = generate_next_tier_variant(
            cur_session.get("question", ""),
            cur_session.get("dialogue_history", []),
            diag,
            next_t,
            api_config
        )
        diag[f"tier{next_t}_variant"] = new_variant
        cur_session["diagnostic_result"] = diag
        cur_session["current_variant_tier"] = next_t
        cur_session["current_stage"] = 4
        dispatch_variant_tier(next_t)
        save_all_data(store)
        st.session_state["pending_thought_input"] = ""
        st.rerun()


def trigger_diagnosis_and_first_variant():
    if offline_demo:
        q_t = cur_session.get("question", "")
        if "动量" in q_t or "滑块" in q_t or "凹槽" in q_t:
            preset = GOLDEN_PRESETS.get("physics_momentum")
        elif "NaOH" in q_t or "CH_3COOH" in q_t or "中性" in q_t or "水解" in q_t:
            preset = GOLDEN_PRESETS.get("chemistry_equilibrium")
        elif "热敏电阻" in q_t or "比较器" in q_t or "三极管" in q_t:
            preset = GOLDEN_PRESETS.get("tech_logic_control")
        else:
            preset = GOLDEN_PRESETS.get("math_derivative")
        cur_session["diagnostic_result"] = preset["preset_diagnostic"]
    else:
        with st.spinner("正在基于认知心理学模型生成思维画像与三阶变式矩阵..."):
            cur_session["diagnostic_result"] = generate_diagnostic_report(
                cur_session["dialogue_history"],
                cur_session["question"],
                api_config
            )
    
    cur_session["current_stage"] = 4
    cur_session["current_variant_tier"] = 1
    
    # 🌟 两段式标题进化（阶段2：突破后追加错因定性）
    if cur_session.get("title_stage", 0) < 2:
        new_title = generate_session_title(
            cur_session["question"],
            cur_session["dialogue_history"],
            cur_session["diagnostic_result"],
            cur_session.get("title", "会话"),
            title_stage=2,
            api_config=api_config
        )
        cur_session["title"] = new_title
        cur_session["title_stage"] = 2
    
    # 直接原子发布第 1 阶变式挑战（合并单条横幅），彻底杜绝脱节
    dispatch_variant_tier(1)
    save_all_data(store)


def insert_latex_code(code_snippet: str):
    curr = st.session_state.get("student_thought_input", "")
    dollar_count = curr.count("$")
    if dollar_count % 2 == 0 and not code_snippet.startswith("$"):
        code_to_insert = f"${code_snippet}$"
    else:
        code_to_insert = code_snippet
    if curr and not curr.endswith(" ") and not curr.endswith("\n"):
        st.session_state["student_thought_input"] = curr + f" {code_to_insert} "
    else:
        st.session_state["student_thought_input"] = curr + f"{code_to_insert} "


# ==========================================
# 新会话独立开题工作区 (Dedicated Onboarding View)
# 若当前会话尚未录入题目，展示极简开题界面，仅提供输入新题目或拍照上传选项
# ==========================================
is_new_session = (not cur_session.get("is_initialized", False)) or (not cur_session.get("question", "").strip())

if is_new_session:
    st.markdown("""
    <div style="max-width: 860px; margin: 1.2rem auto 1.6rem auto; text-align: center;">
        <div style="display: inline-flex; align-items: center; justify-content: center; width: 54px; height: 54px; border-radius: 16px; background: rgba(59, 130, 246, 0.12); border: 1px solid rgba(59, 130, 246, 0.3); font-size: 28px; margin-bottom: 0.75rem; box-shadow: 0 4px 18px rgba(59, 130, 246, 0.18);">
            🧭
        </div>
        <h1 style="font-size: 2.25rem; font-weight: 800; color: #f8fafc; margin-bottom: 0.6rem; letter-spacing: -0.5px; line-height: 1.2;">
            CogniScaffold · 开启全新解题探索
        </h1>
        <div style="font-size: 1.05rem; font-weight: 500; color: #e2e8f0; margin-bottom: 0.3rem; line-height: 1.4;">
            打破“假装看懂”，拒绝直接灌输标准答案
        </div>
        <div style="font-size: 0.94rem; color: #94a3b8; margin-bottom: 1.2rem; line-height: 1.4;">
            依托苏格拉底思维脚手架，陪伴你一步步洞察解题暗坑并自主破局
        </div>
        <div style="display: flex; justify-content: center; gap: 10px; flex-wrap: wrap;">
            <span style="display: inline-flex; align-items: center; gap: 6px; padding: 5px 14px; border-radius: 20px; font-size: 0.84rem; font-weight: 500; background: rgba(59, 130, 246, 0.1); border: 1px solid rgba(59, 130, 246, 0.25); color: #93c5fd;">
                🎯 逐步提问 · 阶梯引导
            </span>
            <span style="display: inline-flex; align-items: center; gap: 6px; padding: 5px 14px; border-radius: 20px; font-size: 0.84rem; font-weight: 500; background: rgba(99, 102, 241, 0.12); border: 1px solid rgba(99, 102, 241, 0.25); color: #c7d2fe;">
                ⚡ 反例诱导 · 暴露盲区
            </span>
            <span style="display: inline-flex; align-items: center; gap: 6px; padding: 5px 14px; border-radius: 20px; font-size: 0.84rem; font-weight: 500; background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.25); color: #a7f3d0;">
                💡 自主发现 · 深度迁移
            </span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col_wrap1, col_center, col_wrap2 = st.columns([1, 6, 1])
    with col_center:
        with st.container(border=True):
            tab_new_text, tab_new_img, tab_new_preset = st.tabs([
                "✍️ 文字录入新题",
                "📸 拍照 / 图片上传",
                "💡 经典思维陷阱题 (一键体验)"
            ])
            
            with tab_new_text:
                def insert_onboard_latex(sym):
                    curr = st.session_state.get("onboarding_problem_text", "")
                    dollar_count = curr.count("$")
                    if dollar_count % 2 == 0 and not sym.startswith("$"):
                        code_to_insert = f"${sym}$"
                    else:
                        code_to_insert = sym
                    if curr and not curr.endswith(" ") and not curr.endswith("\n"):
                        st.session_state["onboarding_problem_text"] = curr + f" {code_to_insert} "
                    else:
                        st.session_state["onboarding_problem_text"] = curr + f"{code_to_insert} "

                st.markdown("✍️ **请输入题目内容**（完整支持 LaTeX 公式排版，如 $f(x) = \\ln x - ax$）：")

                onboard_q_text = st.text_area(
                    "题目内容输入",
                    placeholder="在此输入或粘贴题目完整内容，支持直接使用 LaTeX 科学公式排版（可展开下方符号键盘辅助输入）...",
                    height=130,
                    key="onboarding_problem_text",
                    label_visibility="collapsed"
                )
                
                # 实时 LaTeX 公式排版预览（单块闭合卡片，彻底避免多余空边框）
                if onboard_q_text.strip():
                    st.markdown("""
                    <div class="latex-preview-card" style="margin: 8px 0 6px 0;">
                        <span style="color: #60a5fa; font-weight: 600; font-size: 0.8rem;">👁️ 题目公式实时排版预览：</span>
                    </div>
                    """, unsafe_allow_html=True)
                    st.markdown(onboard_q_text.strip())
                else:
                    st.caption("💡 提示：输入包含 LaTeX 语法（如 $f(x) = \\ln x - ax$ 或 $\\frac{a}{b}$）时，在此实时呈现高精度公式排版预览。")
                
                with st.expander("🔣 全学科 LaTeX 符号键盘（高中数理化技双层预设）", expanded=False):
                    st.markdown("""
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <span style="font-size: 0.86rem; font-weight: 700; color: #f1f5f9;">📐 全学科 LaTeX 符号预设库</span>
                        <span style="font-size: 0.72rem; color: #60a5fa; background: rgba(59, 130, 246, 0.12); border: 1px solid rgba(59, 130, 246, 0.25); padding: 2px 7px; border-radius: 4px;">双层分类检索</span>
                    </div>
                    """, unsafe_allow_html=True)

                    # 第一层菜单：学科领域
                    onb_tier1_opts = list(LATEX_PRESETS_TREE.keys())
                    onb_active_t1 = st.session_state.get("onb_latex_t1_pref", onb_tier1_opts[0])
                    if onb_active_t1 not in onb_tier1_opts:
                        onb_active_t1 = onb_tier1_opts[0]
                    
                    onb_sel_t1 = st.segmented_control(
                        "开题学科领域",
                        options=onb_tier1_opts,
                        default=onb_active_t1,
                        key="onb_latex_sel_tier1",
                        label_visibility="collapsed"
                    ) or onb_active_t1
                    st.session_state["onb_latex_t1_pref"] = onb_sel_t1

                    # 第二层菜单：学科专题细分
                    onb_sub_dict = LATEX_PRESETS_TREE.get(onb_sel_t1, {})
                    onb_tier2_opts = list(onb_sub_dict.keys())
                    if onb_tier2_opts:
                        onb_active_t2 = st.session_state.get(f"onb_latex_t2_pref_{onb_sel_t1}", onb_tier2_opts[0])
                        if onb_active_t2 not in onb_tier2_opts:
                            onb_active_t2 = onb_tier2_opts[0]
                        onb_sel_t2 = st.pills(
                            "开题专题分类",
                            options=onb_tier2_opts,
                            default=onb_active_t2,
                            key=f"onb_latex_sel_tier2_{onb_sel_t1}",
                            label_visibility="collapsed"
                        ) or onb_active_t2
                        st.session_state[f"onb_latex_t2_pref_{onb_sel_t1}"] = onb_sel_t2
                    else:
                        onb_sel_t2 = None

                    # 符号按钮矩阵 (4列紧凑排布)
                    onb_symbols = onb_sub_dict.get(onb_sel_t2, [])
                    if onb_symbols:
                        st.markdown("<div style='margin-top: 6px;'></div>", unsafe_allow_html=True)
                        n_c = 4
                        cols_onb = st.columns(n_c, gap="small")
                        for o_idx, sym_it in enumerate(onb_symbols):
                            c_k = cols_onb[o_idx % n_c]
                            o_lbl = sym_it["label"]
                            o_code = sym_it["code"]
                            o_desc = sym_it["desc"]
                            btn_onb_id = f"btn_onb_lat_{abs(hash(onb_sel_t1 + (onb_sel_t2 or '') + o_lbl)) % 1000000}_{o_idx}"
                            with c_k:
                                st.button(
                                    o_lbl,
                                    key=btn_onb_id,
                                    help=f"【{o_desc}】\n点击插入：{o_code}",
                                    use_container_width=True,
                                    on_click=insert_onboard_latex,
                                    args=(o_code,)
                                )
                    st.markdown("<div style='font-size: 0.72rem; color: #64748b; margin-top: 8px; text-align: right;'>💡 点击任意公式符号自动填入题目输入框</div>", unsafe_allow_html=True)

                st.markdown("<div style='margin-top: 14px;'></div>", unsafe_allow_html=True)
                b_left, b_right = st.columns([3, 1.8])
                with b_right:
                    submit_text_btn = st.button("🚀 开启思维引导", use_container_width=True, type="primary")
                
                if submit_text_btn:
                    if onboard_q_text.strip():
                        initialize_session_with_question(cur_session, onboard_q_text.strip(), api_config, offline_demo)
                        save_all_data(store)
                        st.rerun()
                    else:
                        st.warning("请先输入题目文字或公式再开始陪练哦！")
                        
            with tab_new_img:
                st.markdown("<p style='font-size: 0.92rem; color: #cbd5e1; margin-top: 6px; margin-bottom: 8px;'>上传试卷、练习册照片或直接拍照，系统将智能识别文字与数学公式：</p>", unsafe_allow_html=True)
                onb_up_file = st.file_uploader("上传题目图片", type=["png", "jpg", "jpeg"], key="onb_up_q_file")
                onb_cam_file = st.camera_input("拍照识别", key="onb_cam_q_file")
                active_onb_img = onb_up_file or onb_cam_file
                if active_onb_img is not None:
                    st.image(active_onb_img, caption="待识别题目照片", use_column_width=True)
                    b_img_l, b_img_r = st.columns([3, 1.8])
                    with b_img_r:
                        submit_img_btn = st.button("🔍 智能识别并开启", use_container_width=True, type="primary")
                    if submit_img_btn:
                        with st.spinner("AI 视觉模型正在解析题目文字与数学公式..."):
                            img_bytes = active_onb_img.getvalue()
                            recognized_text = analyze_image_input(img_bytes, "question", "", api_config)
                        initialize_session_with_question(cur_session, recognized_text, api_config, offline_demo)
                        save_all_data(store)
                        st.rerun()

            with tab_new_preset:
                st.markdown("<p style='font-size: 0.92rem; color: #cbd5e1; margin-top: 6px; margin-bottom: 14px;'>挑选经过认知心理学验证的高中数理化技经典思维暗坑，即刻感受深度启发推导：</p>", unsafe_allow_html=True)
                
                # 4 大学科案例：2 x 2 经典矩阵
                row1_c1, row1_c2 = st.columns(2)
                row2_c1, row2_c2 = st.columns(2)
                
                preset_items = [
                    (row1_c1, "math_derivative", "📐 数学·导数极值分类", "📐 高中数学 · 导数分类讨论", "暗坑：对数定义域 $x>0$ 隐式约束，及参数 $a \\le 0$ 时导数恒正无极值的分类缺失。", "载入导数案例 ➔"),
                    (row1_c2, "physics_momentum", "⚖️ 物理·系统动量守恒", "⚖️ 高中物理 · 系统动量守恒", "暗坑：动量守恒是矢量定律，滑块下滑竖直方向合外力不为零，仅水平分动量守恒。", "载入动量案例 ➔"),
                    (row2_c1, "chemistry_equilibrium", "🧪 化学·中性点电荷守恒", "🧪 高中化学 · 水解与电荷守恒", "暗坑：混淆中性点（$\\mathrm{pH}=7$）与化学反应终点，忽略电荷守恒 $c(\\mathrm{Na^+})=c(\\mathrm{CH_3COO^-})$。", "载入化学案例 ➔"),
                    (row2_c2, "tech_logic_control", "💻 技术·电控逻辑门限", "💻 高中技术 · 比较器门限电平", "暗坑：直觉简化导致忽略分压桥臂电位升降，及电压比较器阈值突变逻辑断层。", "载入技术案例 ➔")
                ]
                
                for p_col, p_key, p_session_title, p_card_title, p_card_desc, p_btn_label in preset_items:
                    with p_col:
                        with st.container(border=True):
                            st.markdown(f"**{p_card_title}**")
                            st.markdown(p_card_desc)
                            st.markdown("<div style='margin-top: 8px;'></div>", unsafe_allow_html=True)
                            if st.button(p_btn_label, key=f"onb_load_{p_key}_btn", use_container_width=True):
                                preset = GOLDEN_PRESETS[p_key]
                                cur_session["title"] = p_session_title
                                cur_session["is_initialized"] = True
                                cur_session["title_stage"] = 1
                                cur_session["question"] = preset["question"]
                                cur_session["solver_blueprint"] = preset["solver_blueprint"]
                                cur_session["dialogue_history"] = [
                                    {"role": "user", "content": preset["initial_student_input"]},
                                    {"role": "assistant", "content": preset["offline_simulation"][0]["tutor_response"]}
                                ]
                                cur_session["tutor_turns"] = 1
                                cur_session["current_stage"] = 2
                                cur_session["diagnostic_result"] = None
                                cur_session["transfer_eval_result"] = None
                                cur_session["current_variant_tier"] = 1
                                save_all_data(store)
                                st.rerun()

    st.stop()


# ==========================================
# 自愈与状态对齐钩子 (Self-Healing State Alignment)
# 若当前会话已有思维画像(diagnostic_result)，但尚未在对话历史中发布变式题，或阶段未对齐：
# 自动提升至阶段 4 并发布当前 Tier 变式题，彻底杜绝“右侧显示已有题目但对话区未给出”的脱节现象！
# ==========================================
if cur_session.get("diagnostic_result"):
    has_variant = any(m.get("role") == "assistant_variant" for m in cur_session.get("dialogue_history", []))
    if not has_variant or cur_session.get("current_stage", 1) < 4:
        cur_session["current_stage"] = 4
        if not cur_session.get("current_variant_tier"):
            cur_session["current_variant_tier"] = 1
        dispatch_variant_tier(cur_session["current_variant_tier"])
        save_all_data(store)
        st.rerun()

# ==========================================
# 主界面双栏布局 (60% 交互区 : 40% 看板区)
# ==========================================
col_left, col_right = st.columns([1.5, 1.0], gap="large")

# ------------------------------------------
# 左侧：交互陪练与启发流
# ------------------------------------------
with col_left:
    st.markdown("### 💬 启发式交互陪练")
    
    # 题目卡片：标题与内容一体化，默认可折叠，折叠后只显示一行摘要
    q_raw = cur_session.get("question", "").replace("\n", " ").strip()
    q_summary = (q_raw[:40] + "...") if len(q_raw) > 40 else q_raw
    with st.expander(f"📌 当前题目：{q_summary}", expanded=False):
        st.markdown(cur_session["question"])
    
    # 聊天容器 (紧凑高度，内部独立滚动)
    chat_box = st.container(height=410)
    
    with chat_box:
        # 去除连续重复的 divider
        display_history = []
        for m in cur_session["dialogue_history"]:
            if m.get("role") == "divider" and display_history and display_history[-1].get("role") == "divider":
                continue
            display_history.append(m)

        total_msgs = len(display_history)
        # 找到最新一条关键消息（或其前置 divider）的索引，作为顶部滚动锚点
        anchor_idx = max(0, total_msgs - 1)
        if anchor_idx > 0 and display_history[anchor_idx - 1].get("role") == "divider":
            anchor_idx = anchor_idx - 1

        for idx, msg in enumerate(display_history):
            if idx == anchor_idx:
                st.markdown('<div id="latest-msg-top-anchor" style="height: 1px; margin: 0; padding: 0; scroll-margin-top: 14px;"></div>', unsafe_allow_html=True)

            if msg["role"] == "user":
                with st.chat_message("user", avatar="🧑‍🎓"):
                    st.markdown('<span class="student-msg-marker"></span>\n\n' + format_chat_markdown(msg["content"]), unsafe_allow_html=True)
            elif msg["role"] == "divider":
                st.markdown(f"""
                <div class="variant-divider-card">
                    <span style="color: #34d399; font-weight: 700; font-size: 0.92rem;">{msg["content"]}</span>
                    <div style="font-size: 0.78rem; color: #94a3b8; margin-top: 3px;">⚠️ 杜绝死记硬背 · 循序渐进闯关 · 深度认知迁移</div>
                </div>
                """, unsafe_allow_html=True)
            elif msg["role"] == "assistant_variant":
                with st.chat_message("assistant", avatar="🎯"):
                    st.markdown('<span class="variant-msg-marker"></span>\n\n' + format_chat_markdown(msg["content"]), unsafe_allow_html=True)
            else:
                with st.chat_message("assistant", avatar="🧭"):
                    clean_content = msg["content"].replace("[TRIGGER_DIAGNOSIS]", "").strip()
                    st.markdown('<span class="tutor-msg-marker"></span>\n\n' + format_chat_markdown(clean_content), unsafe_allow_html=True)
        
        # JS 自动定位：使用 getBoundingClientRect 精确计算相对位移，将最新横幅/消息顶部锁定在容器可视区顶端
        st.markdown("""
        <img src="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg'></svg>" style="display:none;" onload="(function(){
            function doScroll() {
                var a = document.getElementById('latest-msg-top-anchor');
                if (!a) return;
                var p = a.parentElement;
                while (p && p !== document.body) {
                    var cs = window.getComputedStyle(p);
                    if (cs.overflowY === 'auto' || cs.overflowY === 'scroll') {
                        var aRect = a.getBoundingClientRect();
                        var pRect = p.getBoundingClientRect();
                        var target = p.scrollTop + (aRect.top - pRect.top) - 10;
                        p.scrollTop = Math.max(0, target);
                        break;
                    }
                    p = p.parentElement;
                }
            }
            [60, 200, 450, 800].forEach(function(d){ setTimeout(doScroll, d); });
        })()"/>
        """, unsafe_allow_html=True)
        components.html("""
        <script>
            function scrollChatToTopAnchor() {
                try {
                    var doc = (window.parent && window.parent.document) ? window.parent.document : document;
                    var anchor = doc.getElementById('latest-msg-top-anchor');
                    if (!anchor) return;
                    var p = anchor.parentElement;
                    while (p && p !== doc.body) {
                        var cs = (doc.defaultView || window).getComputedStyle(p);
                        if (cs.overflowY === 'auto' || cs.overflowY === 'scroll') {
                            var aRect = anchor.getBoundingClientRect();
                            var pRect = p.getBoundingClientRect();
                            var target = p.scrollTop + (aRect.top - pRect.top) - 10;
                            p.scrollTop = Math.max(0, target);
                            break;
                        }
                        p = p.parentElement;
                    }
                } catch(e) {}
            }
            [60, 200, 450, 800].forEach(function(d) {
                setTimeout(scrollChatToTopAnchor, d);
            });
        </script>
        """, height=0)

    # 紧凑输入区：右上角纯图标 popover 快捷工具（并排紧贴右边缘）
    col_in_label, col_in_latex, col_in_photo = st.columns([10, 1, 1], gap="small")
    with col_in_label:
        st.markdown("<div style='font-size: 0.88rem; font-weight: 600; color: #94a3b8; padding-top: 4px;'>✍️ 你的推导与疑问：</div>", unsafe_allow_html=True)
    
    with col_in_latex:
        with st.popover("𝛴", help="全学科 LaTeX 符号键盘（高中数学/物理/化学/技术双层预设）", use_container_width=True):
            st.markdown("""
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <span style="font-size: 0.88rem; font-weight: 700; color: #f1f5f9;">📐 全学科 LaTeX 符号预设库</span>
                <span style="font-size: 0.72rem; color: #60a5fa; background: rgba(59, 130, 246, 0.12); border: 1px solid rgba(59, 130, 246, 0.25); padding: 2px 7px; border-radius: 4px;">双层分类检索</span>
            </div>
            """, unsafe_allow_html=True)
            
            # 第一层菜单：学科领域选择 (数学、物理、化学、技术、希腊/通用)
            tier1_options = list(LATEX_PRESETS_TREE.keys())
            active_t1 = st.session_state.get("latex_tier1_pref", tier1_options[0])
            if active_t1 not in tier1_options:
                active_t1 = tier1_options[0]
            
            sel_tier1 = st.segmented_control(
                "学科领域",
                options=tier1_options,
                default=active_t1,
                key="latex_sel_tier1",
                label_visibility="collapsed"
            ) or active_t1
            st.session_state["latex_tier1_pref"] = sel_tier1
            
            # 第二层菜单：学科专题细分
            sub_dict = LATEX_PRESETS_TREE.get(sel_tier1, {})
            tier2_options = list(sub_dict.keys())
            if tier2_options:
                active_t2 = st.session_state.get(f"latex_tier2_pref_{sel_tier1}", tier2_options[0])
                if active_t2 not in tier2_options:
                    active_t2 = tier2_options[0]
                
                sel_tier2 = st.pills(
                    "专题分类",
                    options=tier2_options,
                    default=active_t2,
                    key=f"latex_sel_tier2_{sel_tier1}",
                    label_visibility="collapsed"
                ) or active_t2
                st.session_state[f"latex_tier2_pref_{sel_tier1}"] = sel_tier2
            else:
                sel_tier2 = None
            
            # 符号矩阵渲染 (4列紧凑排布)
            symbols_list = sub_dict.get(sel_tier2, [])
            if symbols_list:
                st.markdown("<div style='margin-top: 6px;'></div>", unsafe_allow_html=True)
                num_cols = 4
                cols = st.columns(num_cols, gap="small")
                for s_idx, sym_item in enumerate(symbols_list):
                    col = cols[s_idx % num_cols]
                    s_lbl = sym_item["label"]
                    s_code = sym_item["code"]
                    s_desc = sym_item["desc"]
                    btn_uid = f"btn_lat_{abs(hash(sel_tier1 + (sel_tier2 or '') + s_lbl)) % 1000000}_{s_idx}"
                    with col:
                        st.button(
                            s_lbl,
                            key=btn_uid,
                            help=f"【{s_desc}】\n点击插入：{s_code}",
                            use_container_width=True,
                            on_click=insert_latex_code,
                            args=(s_code,)
                        )
            
            st.markdown("<div style='font-size: 0.72rem; color: #64748b; margin-top: 8px; text-align: right;'>💡 点击任意公式符号自动填入推导输入框</div>", unsafe_allow_html=True)

    with col_in_photo:
        with st.popover("📷", help="拍照或上传手写草稿解答图片识别", use_container_width=True):
            draft_file = st.file_uploader("传草稿图", type=["png", "jpg", "jpeg"], key="up_draft_step")
            draft_cam = st.camera_input("拍照", key="cam_draft_step")
            active_draft = draft_file or draft_cam
            if active_draft is not None:
                if st.button("📝 提取草稿推导填入输入框", use_container_width=True):
                    with st.spinner("正在识别手写草稿中的公式与推导步骤..."):
                        draft_bytes = active_draft.getvalue()
                        extracted_thought = analyze_image_input(draft_bytes, "draft", cur_session["question"], api_config)
                        st.session_state["pending_thought_input"] = extracted_thought
                        st.rerun()

    # 实时输入框（提升至 125px，容纳 4+ 行推导，字号 15px）
    if st.session_state.get("pending_thought_input"):
        st.session_state["student_thought_input"] = st.session_state.pop("pending_thought_input")

    diag = cur_session.get("diagnostic_result") or {}
    defined_tiers = [
        int(k.replace("tier", "").replace("_variant", ""))
        for k in diag.keys()
        if k.startswith("tier") and k.endswith("_variant") and k.replace("tier", "").replace("_variant", "").isdigit()
    ]
    max_defined_tier = max(defined_tiers, default=3)
    curr_tier = cur_session.get("current_variant_tier", 1)
    all_tiers_done = (cur_session.get("current_stage", 1) >= 4 and curr_tier > max_defined_tier)

    if cur_session.get("current_stage", 1) < 4:
        input_placeholder = "输入你的推导思路、卡点或推导疑问（支持 LaTeX 公式）..."
    elif all_tiers_done:
        input_placeholder = "已完成全部变式挑战！可点击下方【🔥 再来一题】挑战更高难度，或在此输入推导/探讨..."
    else:
        input_placeholder = f"输入对第 {curr_tier} 阶变式题的推导..."

    user_input = st.text_area(
        "你的思考与推导：",
        placeholder=input_placeholder,
        height=125,
        key="student_thought_input",
        label_visibility="collapsed"
    )
    
    # 实时公式预览
    if user_input.strip():
        preview_text = user_input.strip()
        has_dollar = "$" in preview_text
        has_latex_tokens = any(token in preview_text for token in ["\\", "^", "_", "{", "}"])
        st.markdown("""
        <div class="latex-preview-card">
            <span style="color: #60a5fa; font-weight: 600; font-size: 0.8rem;">👁️ 实时公式排版预览：</span>
        </div>
        """, unsafe_allow_html=True)
        if has_dollar:
            st.markdown(preview_text)
        elif has_latex_tokens:
            st.latex(preview_text)
        else:
            st.markdown(f"*{preview_text}*")

    # 底部内嵌操作栏（左侧校验/提示辅助，右下角内嵌主提交按钮）
    btn_aux_ver, btn_aux_hint, btn_sp, btn_send = st.columns([2.0, 1.2, 1.2, 1.8], gap="small")
    
    with btn_aux_ver:
        can_verify = (cur_session["tutor_turns"] >= 3 and cur_session["current_stage"] < 3)
        if can_verify:
            verify_clicked = st.button("🎯 请求突破校验", use_container_width=True, type="primary", help="向导师申请终审推导，结算思维画像")
        elif all_tiers_done:
            next_t = max_defined_tier + 1
            if st.button(f"🔥 再来一题 (第{next_t}阶)", use_container_width=True, type="primary", help="生成难度进一步递增的高阶巅峰变式挑战"):
                trigger_next_higher_tier()
            verify_clicked = False
        else:
            verify_clicked = False
            if cur_session["current_stage"] >= 3:
                st.button("✅ 认知画像已解锁", use_container_width=True, disabled=True)
            else:
                remaining = 3 - cur_session["tutor_turns"]
                st.button(f"🔒 突破校验 (需思考{remaining}轮)", use_container_width=True, disabled=True, help="为了打碎假装看懂，至少需完成3轮深度交互才能申请突破校验")
    
    with btn_aux_hint:
        hint_clicked = st.button("💡 换个角度", use_container_width=True, help="当前思路卡壳时，请求导师切换启发切入点")

    with btn_send:
        submit_clicked = st.button("🚀 提交思路", use_container_width=True, type="primary")

    # 提交逻辑
    if submit_clicked and user_input.strip():
        student_text = user_input.strip()
        st.session_state["pending_thought_input"] = ""
        
        # 阶段 4：变式闯关模式
        if cur_session["current_stage"] >= 4:
            diag = cur_session.get("diagnostic_result") or {}
            defined_tiers = [
                int(k.replace("tier", "").replace("_variant", ""))
                for k in diag.keys()
                if k.startswith("tier") and k.endswith("_variant") and k.replace("tier", "").replace("_variant", "").isdigit()
            ]
            max_defined = max(defined_tiers, default=3)
            curr_tier = cur_session.get("current_variant_tier", 1)

            if curr_tier > max_defined:
                # 已通关状态下用户继续输入或要求继续出题
                trigger_next_higher_tier()

            tier_data = diag.get(f"tier{curr_tier}_variant", {})
            var_q = tier_data.get("question", "变式题")
            var_h = tier_data.get("hint", "")

            with chat_box:
                with st.chat_message("user", avatar="🧑‍🎓"):
                    st.markdown('<span class="student-msg-marker"></span>\n\n' + format_chat_markdown(student_text), unsafe_allow_html=True)
                with st.chat_message("assistant", avatar="🎯"):
                    eval_text = evaluate_transfer_answer(var_q, var_h, student_text, api_config)
                    st.markdown('<span class="variant-msg-marker"></span>\n\n' + format_chat_markdown(eval_text), unsafe_allow_html=True)

            cur_session["dialogue_history"].append({"role": "user", "content": student_text})
            cur_session["dialogue_history"].append({"role": "assistant_variant", "content": eval_text})
            cur_session["transfer_eval_result"] = eval_text

            if "成功" in eval_text or "通关" in eval_text or "达成" in eval_text:
                if curr_tier < max_defined:
                    next_t = curr_tier + 1
                    cur_session["current_variant_tier"] = next_t
                    dispatch_variant_tier(next_t)
                else:
                    cur_session["current_variant_tier"] = max_defined + 1
                    cur_session["dialogue_history"].append({
                        "role": "divider",
                        "content": f"🏆 恭喜！前 {max_defined} 阶对抗变式全线通关！认知迁移达成度 100% ⭐⭐⭐"
                    })
                    cur_session["dialogue_history"].append({
                        "role": "assistant_variant",
                        "content": f"🎉 **学术大圆满！** 你已连续突破参数拓展、逆向陷阱与跨界全新情境等全部 {max_defined} 重大关。你展现了极佳的物理/数学建模素养与批判性反思直觉，已经彻底驾驭了该认知模块！\n\n👉 如想继续挑战更极限的物理/数学综合难题，可点击下方或右侧看板的 **【🔥 再来一题】** 按钮，系统将进一步加大难度！"
                    })
            save_all_data(store)
            st.rerun()

        else:
            with chat_box:
                with st.chat_message("user", avatar="🧑‍🎓"):
                    st.markdown('<span class="student-msg-marker"></span>\n\n' + format_chat_markdown(student_text), unsafe_allow_html=True)
                
                with st.chat_message("assistant", avatar="🧭"):
                    response_container = st.empty()
                    full_response = ""
                    
                    if offline_demo:
                        preset = GOLDEN_PRESETS.get("math_derivative")
                        sim_text = "请你仔细观察：在函数表达式中对数自变量的取值范围是什么？如果参数 a 是负数，请把自变量为负代入原函数试算，式子有意义吗？"
                        for chunk in simulate_offline_stream(sim_text):
                            full_response += chunk
                            clean_chunk = full_response.replace("[TRIGGER_DIAGNOSIS]", "").strip()
                            response_container.markdown('<span class="tutor-msg-marker"></span>\n\n' + format_chat_markdown(clean_chunk) + " ▌", unsafe_allow_html=True)
                        response_container.markdown('<span class="tutor-msg-marker"></span>\n\n' + format_chat_markdown(clean_chunk), unsafe_allow_html=True)
                    else:
                        temp_history = list(cur_session["dialogue_history"])
                        temp_history.append({"role": "user", "content": student_text})
                        for chunk in stream_tutor_response(temp_history, cur_session["solver_blueprint"], api_config):
                            full_response += chunk
                            clean_chunk = full_response.replace("[TRIGGER_DIAGNOSIS]", "").strip()
                            response_container.markdown('<span class="tutor-msg-marker"></span>\n\n' + format_chat_markdown(clean_chunk) + " ▌", unsafe_allow_html=True)
                        response_container.markdown('<span class="tutor-msg-marker"></span>\n\n' + format_chat_markdown(clean_chunk), unsafe_allow_html=True)
            
            cur_session["dialogue_history"].append({"role": "user", "content": student_text})
            cur_session["dialogue_history"].append({"role": "assistant", "content": full_response})
            cur_session["tutor_turns"] += 1
            
            # 🌟 两段式标题进化（阶段1：首轮交互后提炼学科+题型）
            if cur_session.get("title_stage", 0) == 0:
                new_title = generate_session_title(
                    cur_session["question"],
                    cur_session["dialogue_history"],
                    None,
                    cur_session.get("title", ""),
                    title_stage=1,
                    api_config=api_config
                )
                cur_session["title"] = new_title
                cur_session["title_stage"] = 1
            
            if "[TRIGGER_DIAGNOSIS]" in full_response:
                trigger_diagnosis_and_first_variant()
            
            save_all_data(store)
            st.rerun()

    if verify_clicked:
        trigger_diagnosis_and_first_variant()
        st.rerun()

    if hint_clicked:
        st.session_state["pending_thought_input"] = "这步有点抽象，能从最简单的特例或几何图景给我一个隐喻线索吗？"
        st.rerun()


# ------------------------------------------
# 右侧：学情认知动态看板
# ------------------------------------------
with col_right:
    st.markdown("### 📊 学情认知看板")
    
    # 1. 阶段进度步骤节点 (Stepper)
    curr_stage = cur_session.get("current_stage", 1)
    steps = [
        (1, "审题门禁"),
        (2, "梯度启发"),
        (3, "盲区透视"),
        (4, "变式迁移")
    ]
    stepper_html = '<div class="stepper-box">'
    for idx, (s_num, s_name) in enumerate(steps):
        if s_num < curr_stage:
            dot_cls = "done"
            dot_content = "✓"
            text_cls = ""
        elif s_num == curr_stage:
            dot_cls = "current"
            dot_content = str(s_num)
            text_cls = "active-text"
        else:
            dot_cls = "pending"
            dot_content = str(s_num)
            text_cls = ""
            
        stepper_html += f'''
        <div class="step-node">
            <div class="step-dot {dot_cls}">{dot_content}</div>
            <div class="step-text {text_cls}">{s_name}</div>
        </div>
        '''
        if idx < len(steps) - 1:
            conn_cls = "done" if s_num < curr_stage else ""
            stepper_html += f'<div class="step-connector {conn_cls}"></div>'
    stepper_html += '</div>'
    st.markdown(stepper_html, unsafe_allow_html=True)

    # ------------------------------------------
    # 第一层（始终可见）：阶段条 + 当前学习目标 + 一句行动提示
    # ------------------------------------------
    curr_tier_num = cur_session.get("current_variant_tier", 1)
    diag_check = cur_session.get("diagnostic_result") or {}
    defined_t_list = [
        int(k.replace("tier", "").replace("_variant", ""))
        for k in diag_check.keys()
        if k.startswith("tier") and k.endswith("_variant") and k.replace("tier", "").replace("_variant", "").isdigit()
    ]
    max_d_tier = max(defined_t_list, default=3)
    curr_all_done = (curr_stage >= 4 and curr_tier_num > max_d_tier)

    stage_goals = {
        1: ("审清关键约束与物理边界", "请在左侧回答你对本题条件与已知规律的第一直觉。"),
        2: ("暴露推导瓶颈与潜在断点", "针对导师提出的反例或极端情景，继续推演卡点所在。"),
        3: ("查收思维盲区透视分析", "点击下方选项卡查看错因归因，准备开启变式通关。"),
        4: ("完成高阶对抗变式闯关", "请在左侧输入框完成变式题推导，严防机械套用。")
    }
    cur_goal_title, cur_action_hint = stage_goals.get(curr_stage, ("跟随导师引导逐步推导", "在左侧输入你的推导过程。"))
    if curr_all_done:
        cur_goal_title = f"已通关全部 {max_d_tier} 阶变式挑战"
        cur_action_hint = "点击下方【🔥 再来一题】可开启更高阶巅峰对决！"

    st.markdown(f"""
    <div class="dashboard-card" style="border-left: 3px solid #3b82f6; padding: 12px 14px; margin-bottom: 0.8rem;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
            <span style="font-size: 0.9rem; font-weight: 600; color: #f1f5f9;">🎯 当前目标：{cur_goal_title}</span>
            <span style="font-size: 0.76rem; color: #94a3b8; background: rgba(255, 255, 255, 0.06); padding: 2px 8px; border-radius: 4px;">
                交互：第 <strong style="color: #60a5fa;">{cur_session['tutor_turns']}</strong> 轮
            </span>
        </div>
        <div style="font-size: 0.83rem; color: #94a3b8; line-height: 1.4;">👉 <strong>行动提示</strong>：{cur_action_hint}</div>
    </div>
    """, unsafe_allow_html=True)

    # ------------------------------------------
    # 第二层（默认展开一个）：用 Tab 切换「⚠️ 盲区透视」或「📈 思维轨迹」
    # ------------------------------------------
    diag = cur_session.get("diagnostic_result")
    t_turns = cur_session.get("tutor_turns", 1)
    
    tab_report, tab_trajectory = st.tabs(["⚠️ 盲区透视", "📈 思维轨迹"])
    
    with tab_report:
        if diag:
            b_type = diag.get("blindspot_type", "边界遗漏型")
            b_detail = diag.get("blindspot_detail", "")
            if "根源在于" in b_detail:
                p_perf, p_reason = b_detail.split("根源在于", 1)
                p_reason = "根源在于" + p_reason.strip()
                p_perf = p_perf.strip().rstrip("，。；")
            elif "原因" in b_detail:
                parts = b_detail.split("原因", 1)
                p_perf = parts[0].strip().rstrip("，。；")
                p_reason = "原因" + parts[1].strip()
            elif "；" in b_detail:
                parts = b_detail.split("；", 1)
                p_perf = parts[0].strip().rstrip("，。；")
                p_reason = parts[1].strip()
            elif "，" in b_detail:
                clauses = [c.strip() for c in b_detail.split("，") if c.strip()]
                if len(clauses) >= 3:
                    p_perf = "，".join(clauses[:2])
                    p_reason = "，".join(clauses[2:])
                else:
                    p_perf = clauses[0]
                    p_reason = clauses[1] if len(clauses) > 1 else b_detail
            else:
                p_perf = "直觉倾向于机械套用已知公式或结论"
                p_reason = b_detail or "忽略隐式边界与非平衡合力"
            p_break = diag.get("key_breakthrough", "通过反例诱发矛盾，实现自主逻辑重构")

            st.markdown(f"""
            <div style="background: rgba(245, 158, 11, 0.06); border-left: 3px solid #f59e0b; border-radius: 6px; padding: 12px 14px; margin-bottom: 0.6rem;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <span style="font-size: 0.9rem; font-weight: 700; color: #fbbf24;">错因定性：#{b_type}</span>
                    <span style="background: rgba(245, 158, 11, 0.18); color: #fcd34d; font-size: 0.74rem; padding: 2px 8px; border-radius: 4px; font-weight: 600;">
                        置信度 {diag.get('confidence', '95%')}
                    </span>
                </div>
                <div style="font-size: 13.5px; margin-bottom: 6px; color: #e2e8f0; line-height: 1.55;">
                    <span style="color: #cbd5e1; font-weight: 600;">• 表现：</span>{p_perf}
                </div>
                <div style="font-size: 13.5px; margin-bottom: 6px; color: #94a3b8; line-height: 1.55;">
                    <span style="color: #64748b; font-weight: 600;">• 原因：</span>{p_reason}
                </div>
                <div style="font-size: 13.5px; color: #34d399; line-height: 1.55;">
                    <span style="font-weight: 600;">• 突破点：</span>{p_break}
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # 对抗变式通关进度（支持任意 N 阶动态拓展与无缝循环）
            tier_idx = cur_session.get("current_variant_tier", 1)
            defined_tiers = [
                int(k.replace("tier", "").replace("_variant", ""))
                for k in diag.keys()
                if k.startswith("tier") and k.endswith("_variant") and k.replace("tier", "").replace("_variant", "").isdigit()
            ]
            defined_tiers = sorted(list(set(defined_tiers)))
            if not defined_tiers:
                defined_tiers = [1, 2, 3]
            max_defined = max(defined_tiers)
            all_tiers_done = (tier_idx > max_defined)
            
            tier_default_titles = {
                1: "Tier 1: 维度与参数拓展",
                2: "Tier 2: 逆向反转辨析",
                3: "Tier 3: 跨界综合应用",
                4: "Tier 4: 多体耦合与极值论证",
                5: "Tier 5: 变曲率复合场高阶迁移",
                6: "Tier 6: 抽象拓扑与极限约束",
            }

            def render_tier_row(tier_num, title, curr_t):
                if curr_t > tier_num:
                    stars = "⭐" * min(tier_num, 5)
                    return f'<div style="padding: 6px 10px; margin-bottom: 4px; background: rgba(16, 185, 129, 0.08); border-radius: 4px; display: flex; justify-content: space-between; align-items: center;"><span style="color: #34d399; font-size: 0.85rem;">{stars} <strong>{title}</strong></span><span style="color: #10b981; font-size: 0.82rem; font-weight: 600;">✅ 已通关</span></div>'
                elif curr_t == tier_num:
                    stars = "⭐" * min(tier_num, 5)
                    return f'<div style="padding: 6px 10px; margin-bottom: 4px; background: rgba(59, 130, 246, 0.12); border: 1px solid rgba(59, 130, 246, 0.35); border-radius: 4px; display: flex; justify-content: space-between; align-items: center;"><span style="color: #93c5fd; font-size: 0.85rem;">{stars} <strong>{title}</strong></span><span style="color: #60a5fa; font-size: 0.82rem; font-weight: 600;">🔥 挑战中</span></div>'
                else:
                    gray_stars = "★" * min(tier_num, 5)
                    return f'<div style="padding: 6px 10px; margin-bottom: 4px; opacity: 0.35; border-radius: 4px; display: flex; justify-content: space-between; align-items: center;"><span style="color: #64748b; font-size: 0.85rem;">{gray_stars} {title}</span><span style="color: #64748b; font-size: 0.82rem;">🔒 待解锁</span></div>'

            tier_rows_html = "".join([
                render_tier_row(
                    t_n,
                    (diag.get(f"tier{t_n}_variant", {}) or {}).get("title") or tier_default_titles.get(t_n, f"Tier {t_n}: 高阶综合拓展"),
                    tier_idx
                )
                for t_n in defined_tiers
            ])

            if all_tiers_done:
                status_hint_html = f'<div style="font-size: 0.8rem; color: #10b981; font-weight: 600; margin-top: 8px;">🏆 当前所有 {max_defined} 阶变式挑战均已通关！</div>'
            else:
                status_hint_html = f'<div style="font-size: 0.78rem; color: #64748b; margin-top: 8px;">👉 正在进行第 {tier_idx} 阶挑战，请在左侧主输入框中作答。</div>'

            st.markdown(f"""
            <div style="background: rgba(22, 27, 34, 0.5); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 6px; padding: 10px 12px; margin-top: 6px;">
                <div style="font-size: 0.82rem; color: #94a3b8; font-weight: 600; margin-bottom: 6px;">🎯 高阶对抗变式通关进度：</div>
                {tier_rows_html}
                {status_hint_html}
            </div>
            """, unsafe_allow_html=True)

            if all_tiers_done:
                next_t = max_defined + 1
                if st.button(f"🔥 再来一题 (开启第 {next_t} 阶巅峰挑战)", use_container_width=True, type="primary", key="btn_next_tier_right"):
                    trigger_next_higher_tier()
        else:
            remaining = max(1, 3 - t_turns)
            unlock_pct = min(100, int((t_turns / 3.0) * 100))
            st.markdown(f"""
            <div style="background: rgba(255, 255, 255, 0.02); border: 1px dashed rgba(255, 255, 255, 0.15); border-radius: 8px; padding: 14px; margin-bottom: 0.6rem;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                    <span style="font-size: 0.86rem; color: #94a3b8; font-weight: 600;">🔒 盲区画像透视（待解锁）</span>
                    <span style="font-size: 0.74rem; color: #cbd5e1; background: rgba(255, 255, 255, 0.05); padding: 2px 8px; border-radius: 4px; border: 1px dashed rgba(255, 255, 255, 0.2);">
                        需再深度思考 {remaining} 轮
                    </span>
                </div>
                <div style="font-size: 0.82rem; color: #64748b; line-height: 1.45; margin-bottom: 10px;">
                    正在探测你的第一直觉卡点与隐含逻辑断点，完成 3 轮推导后在此解锁认知归因报告与变式挑战。
                </div>
                <div style="background: rgba(255, 255, 255, 0.06); height: 4px; border-radius: 2px; overflow: hidden;">
                    <div style="background: #3b82f6; width: {unlock_pct}%; height: 100%; transition: width 0.3s ease;"></div>
                </div>
            </div>
            """, unsafe_allow_html=True)

    with tab_trajectory:
        traj_nodes = []
        if t_turns >= 1:
            traj_nodes.append(("第 1 轮", "卡住", "基于直觉提出初步推导，受制于机械套用", "tag-stuck"))
        if t_turns >= 2:
            traj_nodes.append(("第 2 轮", "推进", "在微图景反例启发下重新审视受力与边界", "tag-advance"))
        if t_turns >= 3:
            n_lbl = "顿悟" if diag else "推进"
            n_cls = "tag-break" if diag else "tag-advance"
            traj_nodes.append(("第 3 轮", n_lbl, "突破逻辑陷阱，准备终审校验" if not diag else "识破核心暗坑，完成推导闭环", n_cls))
        if t_turns >= 4:
            traj_nodes.append((f"第 {t_turns} 轮", "顿悟", "同构迁移推导，检验迁移能力", "tag-break"))

        traj_items_html = "".join([
            f'<div class="trajectory-item">'
            f'<span style="color: #64748b; font-size: 0.75rem; white-space: nowrap;">{r_lbl}</span>'
            f'<span class="trajectory-tag {t_cls}">{t_type}</span>'
            f'<span style="color: #cbd5e1; font-size: 0.78rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{t_desc}</span>'
            f'</div>'
            for r_lbl, t_type, t_desc, t_cls in traj_nodes
        ])

        traj_box_html = (
            f'<div class="trajectory-container">'
            f'{traj_items_html}'
            f'</div>'
        )
        st.markdown(traj_box_html, unsafe_allow_html=True)

    # ------------------------------------------
    # 第三层（默认折叠）：靶点标签 + 导师教学策略
    # ------------------------------------------
    with st.expander("🏷️ 查看核心靶点与教学策略", expanded=False):
        q_text = cur_session.get("question", "")
        if "动量" in q_text:
            tag_items = [
                ("矢量方向性守恒", "tag-advance"),
                ("支持力与重力非平衡", "tag-stuck" if not diag else "tag-break"),
                ("竖直方向加速度 a_y", "tag-advance")
            ]
        elif "导数" in q_text:
            tag_items = [
                ("对数定义域 x>0", "tag-stuck" if not diag else "tag-break"),
                ("参数 a 变号极值讨论", "tag-advance"),
                ("导数零点隐式存在", "tag-advance")
            ]
        else:
            tag_items = [
                ("隐含物理/数学边界", "tag-stuck" if not diag else "tag-break"),
                ("极端特例反例校验", "tag-advance"),
                ("逻辑推导闭环", "tag-break" if diag else "tag-advance")
            ]
        tags_html = "".join([f'<span class="trajectory-tag {cls}" style="margin-right:6px; margin-bottom:4px; display:inline-block;">#{lbl}</span>' for lbl, cls in tag_items])
        st.markdown(f"""
        <div style="margin-bottom: 10px;">
            <div style="font-size: 0.78rem; color: #94a3b8; font-weight: 600; margin-bottom: 4px;">🎯 核心认知靶点：</div>
            <div>{tags_html}</div>
        </div>
        <div style="font-size: 0.8rem; color: #94a3b8; line-height: 1.6; border-top: 1px solid rgba(255, 255, 255, 0.06); padding-top: 8px;">
            • <strong>苏格拉底产婆术</strong>：绝不直接给答案，通过提问将思维焦点导向关键矛盾。<br/>
            • <strong>微图景引导</strong>：构造极端情境或特例反例，迫使逻辑漏洞自然暴露。<br/>
            • <strong>防偷跑机制</strong>：须经过真实思考推导（至少 3 轮交互）方可触发终审校验。
        </div>
        """, unsafe_allow_html=True)
