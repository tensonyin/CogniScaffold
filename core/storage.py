"""
CogniScaffold 会话存储与多标签页数据持久化引擎
优化：
1. 区分“待开题空会话”与“正式推导会话”
2. 差异化初始标题（🧩 探索 #1, #2...），避免标签栏全是雷同文字
3. 开题即提炼学科短标题，突破后追加错因定性
"""

import os
import re
import json
import uuid
from typing import Dict, Any, List, Optional


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
    - 若未指定 title，则根据递增计数器分配明确的标题（如 🧩 探索 #1）
    - is_initialized=False 表示这是一个新对话，主界面将展示优雅的“录入新题目”开题页
    """
    default_title = title if title else "🧩 探索·新建会话"

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
    from core.db import now_east8_str
    return now_east8_str("%Y-%m-%d %H:%M:%S")


def generate_session_title(
    question: str,
    dialogue_history: List[Dict[str, str]],
    diagnostic_result: Any,
    current_title: str,
    title_stage: int,
    api_config: Dict[str, Any],
    user_id: Optional[str] = None,
    session_id: Optional[str] = None
) -> str:
    """
    两段式 AI 标题生成：
    - 阶段 1 (开题/首轮): 极速提炼统一规范【Emoji 学科·核心微考点】（严禁生成除高考10科及探索外的其他标题）
    - 阶段 2 (突破结算后): 在原标题后追加「错因总结」（如 📐 数学·导数极值分类 [边界遗漏突破]）
    """
    if title_stage == 2 and diagnostic_result:
        blindspot = diagnostic_result.get("blindspot_type", "突破")
        short_tag = blindspot.split("&")[0].split("与")[0].strip()[:6]
        base_title = current_title.split("[")[0].strip()
        return f"{base_title} [{short_tag}突破]"

    # 规范前缀映射字典 (覆盖 10 科 + 1 探索，严格对应唯一定制 Emoji)
    CANONICAL_PREFIXES = {
        "数学": "📐 数学·",
        "物理": "⚖️ 物理·",
        "化学": "🧪 化学·",
        "生物": "🧬 生物·",
        "技术": "💻 技术·",
        "语文": "📖 语文·",
        "英语": "🔤 英语·",
        "历史": "📜 历史·",
        "政治": "🏛️ 政治·",
        "地理": "🌍 地理·",
        "探索": "🧩 探索·",
    }

    # 阶段 1：首轮提炼学科与题目类型
    if question and api_config and api_config.get("api_key"):
        try:
            from core.engine import get_openai_client
            client = get_openai_client(api_config["api_key"], api_config.get("base_url", ""))
            prompt = (
                "你是一个高中与大学题目学科分类专家。请仔细阅读以下题目，将其严格归入以下【11个标准门类】之一，并生成规范标题：\n"
                "【标准门类与固定Emoji映射表】：\n"
                "- 📐 数学·【核心微考点】 (例如：📐 数学·导数极值讨论)\n"
                "- ⚖️ 物理·【核心微考点】 (例如：⚖️ 物理·电磁感应双杆)\n"
                "- 🧪 化学·【核心微考点】 (例如：🧪 化学·中性点电荷守恒)\n"
                "- 🧬 生物·【核心微考点】 (例如：🧬 生物·遗传系谱图计算)\n"
                "- 💻 技术·【核心微考点】 (例如：💻 技术·动态规划与控制)\n"
                "- 📖 语文·【核心微考点】 (例如：📖 语文·论述批判与隐性前提)\n"
                "- 🔤 英语·【核心微考点】 (例如：🔤 英语·倒装虚拟与长难句)\n"
                "- 📜 历史·【核心微考点】 (例如：📜 历史·洋务成因与制度局限)\n"
                "- 🏛️ 政治·【核心微考点】 (例如：🏛️ 政治·市场调节与宏观调控)\n"
                "- 🌍 地理·【核心微考点】 (例如：🌍 地理·热力环流与洋流)\n"
                "- 🧩 探索·【核心微考点】 (例如：🧩 探索·费米估算与博弈论)\n\n"
                "严格规则：\n"
                "1. 绝对不要生成除上述 10 门学科及「探索」之外的任何其他学科门类！若无法明确属于十科，必须归为「🧩 探索·xxx」！\n"
                "2. Emoji 必须严格使用上方表格中对应门类的唯一指定 Emoji，严禁使用任何其他 Emoji！\n"
                "3. 输出格式严格为：【Emoji】 【学科/探索名】·【考点概括（严格4至8个汉字）】\n"
                "4. 仅输出一行，绝对不要带有任何引号、括号或多余说明！\n\n"
                f"题目：\n{question[:350]}"
            )
            resp = client.chat.completions.create(
                model=api_config.get("model", "deepseek-chat"),
                messages=[
                    {"role": "system", "content": "你只输出指定格式的一行学科标签，绝不包含任何多余文字。"},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=25,
                temperature=0.2,
                timeout=6.0
            )
            if user_id and hasattr(resp, "usage") and resp.usage:
                try:
                    from core.db import record_token_usage
                    record_token_usage(
                        user_id=user_id,
                        session_id=session_id,
                        task_type="session_title",
                        prompt_tokens=resp.usage.prompt_tokens,
                        completion_tokens=resp.usage.completion_tokens,
                        total_tokens=resp.usage.total_tokens
                    )
                except Exception as e_tok:
                    print(f"[Token Log Error in session_title] {e_tok}")
            ai_title = resp.choices[0].message.content.strip().replace('"', '').replace("'", '').replace("【", "").replace("】", "")
            ai_title = ai_title.split("\n")[0].strip()

            # 校验并标准化前缀，严防模型偶发生成非标准 Emoji
            matched_prefix = None
            for subj, pfx in CANONICAL_PREFIXES.items():
                if subj in ai_title or pfx in ai_title:
                    matched_prefix = pfx
                    break

            if matched_prefix:
                # 提取考点名
                core_topic = ai_title.split("·")[-1].strip().split()[-1].strip()
                core_topic = re.sub(r'^[^一-龥a-zA-Z0-9]+', '', core_topic)[:10]
                if core_topic:
                    return f"{matched_prefix}{core_topic}"
            elif len(ai_title) >= 4 and "·" in ai_title:
                return f"🧩 探索·{ai_title.split('·')[-1].strip()[:8]}"
        except Exception as e:
            print(f"AI Title generation fallback: {e}")

    # 本地全学科规则匹配回退机制 (严格覆盖 10 科 + 探索)
    if question:
        q_clean = question.replace("\n", " ").strip()
        # 英语 (英文字符较多或语法核心词)
        if any(k in q_clean for k in ["虚拟语气", "倒装", "从句", "阅读理解", "完形填空", "英语", "宾语从句", "定语从句", "inversion", "syntax"]) or len(re.findall(r'[a-zA-Z]{3,}', q_clean)) >= 6:
            return "🔤 英语·语法逻辑与主旨推断"
        # 数学
        elif any(k in q_clean for k in ["导数", "极值", "单调", "切线", "驻点", "ln", "e^x", "f'(x)", "f(x)"]):
            return "📐 数学·导数与极值讨论"
        elif any(k in q_clean for k in ["椭圆", "双曲线", "抛物线", "离心率", "渐近线", "弦长", "焦点", "圆锥曲线"]):
            return "📐 数学·解析几何与圆锥曲线"
        elif any(k in q_clean for k in ["面面垂直", "线面角", "二面角", "法向量", "正方体", "棱锥", "球体"]):
            return "📐 数学·空间立体几何"
        elif any(k in q_clean for k in ["数列", "等差", "等比", "前n项和", "递推公式", "通项公式"]):
            return "📐 数学·数列与递推求和"
        elif any(k in q_clean for k in ["向量", "点积", "数量积", "正弦定理", "余弦定理", "三角函数"]):
            return "📐 数学·三角函数与向量"
        # 物理
        elif any(k in q_clean for k in ["动量", "碰撞", "弹性", "滑块", "小车", "动能", "反冲", "系统守恒"]):
            return "⚖️ 物理·系统动量与守恒"
        elif any(k in q_clean for k in ["磁场", "电场", "洛伦兹", "带电粒子", "偏转", "回旋", "感应电动势", "安培力"]):
            return "⚖️ 物理·电磁复合场感应"
        elif any(k in q_clean for k in ["行星", "卫星", "轨道", "万有引力", "开普勒", "第一宇宙速度"]):
            return "⚖️ 物理·天体引力与轨道"
        elif any(k in q_clean for k in ["摩擦力", "斜面", "牛顿第二定律", "传送带", "圆周运动", "向心力"]):
            return "⚖️ 物理·动力学受力平衡"
        # 化学
        elif any(k in q_clean for k in ["水解", "电离", "pH", "平衡常数", "Ka", "Kb", "Kw", "NaOH", "CH3COOH", "沉淀溶解"]):
            return "🧪 化学·溶液平衡与离子"
        elif any(k in q_clean for k in ["原电池", "电解池", "正极", "负极", "阴极", "阳极", "锂电池", "电极反应"]):
            return "🧪 化学·电化学与电池原理"
        elif any(k in q_clean for k in ["同分异构", "官能团", "取代反应", "加成反应", "酯化", "烃", "苯环"]):
            return "🧪 化学·有机合成与推断"
        # 生物
        elif any(k in q_clean for k in ["基因", "遗传", "伴性遗传", "孟德尔", "显性", "隐性", "DNA", "RNA", "染色体"]):
            return "🧬 生物·遗传系谱与伴性遗传"
        elif any(k in q_clean for k in ["光合", "呼吸", "叶绿体", "线粒体", "ATP", "神经", "激素", "反射弧", "内环境"]):
            return "🧬 生物·细胞代谢与平衡调节"
# 地理
        elif any(k in q_clean for k in ["等高线", "晨昏线", "地转偏向力", "锋面", "气旋", "洋流", "板块", "岩石圈", "经纬度", "热力", "山谷风", "海陆风", "大气环流", "季风", "降水", "气候", "水循环", "地质构造", "褶皱", "断层", "地理"]):
            return "🌍 地理·自然环境与热力环流"
        elif any(k in q_clean for k in ["城市区位", "人口迁移", "工业集聚", "农业地域", "交通运输", "可持续发展", "城镇化", "产业转移"]):
            return "🌍 地理·人文区位与协同发展"
        # 历史
        elif any(k in q_clean for k in ["洋务", "李鸿章", "甲午", "官督商办", "科举", "郡县", "封建", "辛亥", "抗日", "改革开放", "冷战", "工业革命", "凡尔赛", "历史", "史料", "王朝", "帝国", "皇帝"]):
            return "📜 历史·洋务成因与制度局限" if "洋务" in q_clean else "📜 历史·历史演进与文明脉络"
        # 政治
        elif any(k in q_clean for k in ["商品", "货币", "市场经济", "宏观调控", "人大", "政协", "矛盾", "唯物主义", "政治", "实践", "认识论", "市场失灵", "公共物品", "自然垄断", "辩证"]):
            return "🏛️ 政治·制度调控与哲学辨证"
        # 技术
        elif any(k in q_clean for k in ["二叉树", "动态规划", "dp", "二分", "贪心", "复杂度", "递归", "状态转移", "三极管", "比较器", "555", "电路", "技术", "门限", "算法", "寄存器"]):
            return "💻 技术·算法逻辑与系统控制"
        # 语文
        elif any(k in q_clean for k in ["现代文", "论述", "论证", "谬误", "隐性前提", "人情味", "稻草人", "滑坡", "主旨", "修辞", "文言文", "阅读", "语文", "诗歌", "词赋", "鲁迅", "通假字", "意象", "抒情", "散文", "小说", "先验"]):
            return "📖 语文·论述批判与隐性前提" if any(w in q_clean for w in ["前提", "谬误", "论述", "论证", "批判", "先验"]) else "📖 语文·文本阅读与思辨"
        # 探索类 (费米估算/博弈论/逻辑谜题)
        elif any(k in q_clean for k in ["费米", "估算", "纳什", "博弈", "囚徒", "帕累托", "逻辑", "悖论"]):
            return "🧩 探索·思维建模与博弈推演"

    # 若未命中任何特定学科，统一规范归入 🧩 探索
    if question:
        t = re.sub(r'\\frac\{([^\{\}]+)\}\{([^\{\}]+)\}', r'\1/\2', question)
        t = re.sub(r'\\sqrt\{([^\{\}]+)\}', r'√\1', t)
        t = t.replace(r'\times', '×').replace(r'\div', '÷').replace(r'\pm', '±').replace(r'\infty', '∞')
        t = re.sub(r'\\(ln|log|sin|cos|tan)\b', r'\1', t)
        t = re.sub(r'\\[a-zA-Z]+', '', t)
        clean = re.sub(r'[\$#\*`\\\{\}_]+', ' ', t).strip()
        clean = re.sub(r'\s+', ' ', clean).strip()
        clean_word = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]+', '', clean)[:6]
        if clean_word:
            return f"🧩 探索·{clean_word}探究"

    return "🧩 探索·思维引导突破"


CHINESE_NUMS = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十"]

def to_chinese_num(n: int) -> str:
    """统一阿拉伯数字转换为规范中文数字（1->一, 2->二, 3->三, 4->四, 5->五...）"""
    if 0 <= n < len(CHINESE_NUMS):
        return CHINESE_NUMS[n]
    return str(n)


def detect_subject_info(question: str, title: str = "") -> dict:
    """根据问题内容与会话标题动态识别学科领域及认知能力画像，绝不机械硬编码"""
    q = (question or "") + " " + (title or "")
    if any(k in q for k in ["导数", "函数", "切线", "极值", "单调", "零点", "对数", "ln", "e^x", "解析几何", "椭圆", "双曲线", "抛物线", "数列", "极限", "求和", "不等式"]):
        return {"subject": "数学", "ability": "严密的数理逻辑推演与深度函数分析素养", "challenge": "高阶综合数学思辨难题"}
    elif any(k in q for k in ["动量", "碰撞", "滑块", "受力", "磁场", "电场", "天体", "引力", "加速度", "机械能", "牛顿", "洛伦兹", "安培"]):
        return {"subject": "物理", "ability": "敏锐的物理建模直觉与状态守恒分析素养", "challenge": "高阶物理图景迁移难题"}
    elif any(k in q for k in ["水解", "电离", "pH", "平衡", "沉淀", "原电池", "电解", "化学", "反应", "氧化还原"]):
        return {"subject": "化学", "ability": "微观动态平衡推演与化学规律守恒素养", "challenge": "复杂反应机理拓展难题"}
    elif any(k in q for k in ["三极管", "比较器", "门限", "555", "电路", "传感", "算法", "动态规划", "通用技术", "信息技术"]):
        return {"subject": "技术与信息", "ability": "工程逻辑闭环与系统控制分析素养", "challenge": "复杂工程系统拓展难题"}
    else:
        return {"subject": "数理科学", "ability": "批判性科学思辨与逻辑建模素养", "challenge": "更高维度的前沿综合思辨难题"}


def build_tier_completion_report(session: dict, max_defined: int) -> str:
    """构建高信息密度、紧扣题意的阶段4全线通关战报，彻底消灭空洞重复套话"""
    diag = session.get("diagnostic_result") or {}
    q_text = session.get("question", "")
    s_title = session.get("title", "")
    info = detect_subject_info(q_text, s_title)

    tier_lines = []
    for t_n in range(1, max_defined + 1):
        t_data = diag.get(f"tier{t_n}_variant", {})
        raw_title = t_data.get("title", f"第{to_chinese_num(t_n)}关变式拓展")
        clean_t = re.sub(r'^(?:Tier\s*\d+\s*[:：]|第\s*\d+\s*关\s*[:：]|第\s*[一二三四五六七八九十]+\s*关\s*[:：])\s*', '', raw_title)
        tier_lines.append(f"- **第{to_chinese_num(t_n)}关**：{clean_t}（✅ 通关达成）")

    tier_matrix = "\n".join(tier_lines)
    blindspot = diag.get("blindspot_type", "思维卡点")
    breakthrough = diag.get("key_breakthrough", "自主逻辑重构")

    return f"""🏆 **阶段 4 · 对抗变式全线通关战报**

恭喜！你已连续攻克【{info['subject']}】领域的全部 **{to_chinese_num(max_defined)}** 重递进关卡，展现了{info['ability']}！

📊 **通关矩阵与攻坚成果**：
{tier_matrix}

🎯 **认知跃迁历程**：
- **突破卡点**：{blindspot}
- **认知重构**：{breakthrough}

👉 **进阶建议**：本核心模块已实现全维度认知闭环。如想挑战更高阶的{info['challenge']}，可点击下方或右侧看板的 **【🔥 再来一题 (第{to_chinese_num(max_defined + 1)}关)】** 按钮继续进阶！"""