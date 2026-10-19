"""
CogniScaffold 会话存储与多标签页数据持久化引擎
优化：
1. 区分“待开题空会话”与“正式推导会话”
2. 差异化初始标题（💡 探索 #1, #2...），避免标签栏全是雷同文字
3. 开题即提炼学科短标题，突破后追加错因定性
"""

import os
import json
import uuid
from typing import Dict, Any, List
from openai import OpenAI


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
STORAGE_FILE = os.path.join(DATA_DIR, "history_store.json")


def ensure_storage_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(STORAGE_FILE):
        default_data = {
            "active_sessions": {},
            "archived_sessions": {},
            "current_session_id": None,
            "session_counter": 0
        }
        with open(STORAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(default_data, f, ensure_ascii=False, indent=2)


def load_all_data() -> Dict[str, Any]:
    ensure_storage_dir()
    try:
        with open(STORAGE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"active_sessions": {}, "archived_sessions": {}, "current_session_id": None, "session_counter": 0}


def save_all_data(data: Dict[str, Any]):
    ensure_storage_dir()
    try:
        with open(STORAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving data: {e}")


def create_new_session_data(title: str = None, question: str = "", is_initialized: bool = False, store: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    创建一个全新的会话对象：
    - 若未指定 title，则根据递增计数器分配明确的标题（如 💡 探索 #1）
    - is_initialized=False 表示这是一个新对话，主界面将展示优雅的“录入新题目”开题页
    """
    counter = 1
    if store is not None:
        c = store.get("session_counter", 0) + 1
        store["session_counter"] = c
        counter = c

    default_title = title if title else f"💡 探索 #{counter}"

    return {
        "id": str(uuid.uuid4())[:8],
        "title": default_title,
        "is_starred": False,
        "is_initialized": is_initialized,  # 是否已录入题目开启陪练
        "question": question,
        "current_stage": 1,
        "tutor_turns": 0,
        "dialogue_history": [],
        "solver_blueprint": "",
        "diagnostic_result": None,
        "transfer_eval_result": None,
        "current_variant_tier": 1,
        "created_at": time_now_str(),
        "title_stage": 1 if is_initialized else 0
    }


def time_now_str() -> str:
    from datetime import datetime
    return datetime.now().strftime("%m-%d %H:%M")


def generate_session_title(
    question: str,
    dialogue_history: List[Dict[str, str]],
    diagnostic_result: Any,
    current_title: str,
    title_stage: int,
    api_config: Dict[str, Any]
) -> str:
    """
    两段式 AI 标题生成：
    - 阶段 1 (开题/首轮): 提炼「学科 + 核心题型」（7-10字，如 📐 数学·导数极值分类）
    - 阶段 2 (突破结算后): 在原标题后追加「错因总结」（如 📐 数学·导数分类 [边界遗漏突破]）
    """
    if title_stage == 2 and diagnostic_result:
        blindspot = diagnostic_result.get("blindspot_type", "突破")
        short_tag = blindspot.split("&")[0].split("与")[0].strip()[:6]
        base_title = current_title.split("[")[0].strip()
        return f"{base_title} [{short_tag}突破]"

    # 阶段 1：首轮提炼学科+题目类型
    prompt = f"请根据以下数理题目，提炼一个7到10个字且带对应数理Emoji的极简标题（格式类似：'📐 数学·导数极值分类' 或 '⚖️ 物理·斜面动量守恒'）。仅输出该标题本身，严禁任何废话。\n题目：{question}"
    
    try:
        client = OpenAI(api_key=api_config["api_key"] or "sk-dummy", base_url=api_config["base_url"])
        res = client.chat.completions.create(
            model=api_config["model"],
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=30
        )
        title = res.choices[0].message.content.strip().replace('"', '').replace("'", "")
        return title[:16]
    except Exception:
        if "导数" in question or "ln" in question:
            return "📐 数学·导数极值讨论"
        elif "动量" in question or "滑块" in question:
            return "⚖️ 物理·系统动量守恒"
        return "💡 探索·数理思维突破"
