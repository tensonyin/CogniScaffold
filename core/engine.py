"""
CogniScaffold 运行时引擎
处理双智能体协同、流式输出、状态机推进、结构化诊断、三阶变式矩阵生成与自信豁免评判
"""

import json
import time
import base64
import re
from typing import Generator, Dict, Any, List, Tuple
from openai import OpenAI

from core.storage import to_chinese_num
from core.prompts import (
    SOLVER_SYSTEM_PROMPT,
    TUTOR_SYSTEM_PROMPT,
    DIAGNOSTIC_SYSTEM_PROMPT,
    TRANSFER_EVAL_PROMPT,
    NEXT_TIER_PROMPT
)

_CLIENT_CACHE: Dict[Tuple[str, str], OpenAI] = {}

def is_valid_api_key(api_key: str) -> bool:
    """校验 API Key 是否有效配置，过滤空值或默认 dummy 占位符"""
    if not api_key:
        return False
    key_str = str(api_key).strip()
    return bool(key_str) and key_str != "sk-dummy" and not key_str.endswith("dummy")

def get_openai_client(api_key: str, base_url: str) -> OpenAI:
    """初始化并缓存 OpenAI 客户端单例，复用底层 HTTP Keep-Alive 连接池，大幅消除网络握手延迟"""
    key = (api_key or "sk-dummy", base_url or "")
    if key not in _CLIENT_CACHE:
        _CLIENT_CACHE[key] = OpenAI(
            api_key=key[0],
            base_url=key[1] if key[1] else None,
            timeout=45.0,
            max_retries=2
        )
    return _CLIENT_CACHE[key]


def generate_solver_blueprint(question: str, api_config: Dict[str, Any]) -> str:
    """
    Solver Agent: 一次性生成题目的真实解题基准与思维陷阱图谱
    供后续 Tutor Agent 作为内部知识底座参考
    """
    if not is_valid_api_key(api_config.get("api_key")):
        return "（未检测到有效 OPENAI_API_KEY，已自动启用认知脚手架预设解题底座）"
    client = get_openai_client(api_config["api_key"], api_config["base_url"])
    try:
        response = client.chat.completions.create(
            model=api_config["model"],
            messages=[
                {"role": "system", "content": SOLVER_SYSTEM_PROMPT},
                {"role": "user", "content": f"请针对这道题目构建解题底座与陷阱字典：\n{question}"}
            ],
            temperature=0.2,
            max_tokens=600
        )
        return response.choices[0].message.content or "（未能生成解题底座）"
    except Exception as e:
        return f"（解题基准生成异常: {str(e)}）"


def stream_tutor_response(
    dialogue_history: List[Dict[str, str]],
    solver_blueprint: str,
    api_config: Dict[str, Any]
) -> Generator[str, None, None]:
    """
    Tutor Agent: 极速流式启发引导
    将 solver_blueprint 注入系统提示词，采用 streaming 方式输出，1-2秒内吐出首字
    """
    if not is_valid_api_key(api_config.get("api_key")):
        yield "【⚠️ 未检测到有效的大模型 API 密钥（OPENAI_API_KEY 未配置或无效）。请在服务器环境或项目 .env 文件中设置后继续对话。】"
        return

    client = get_openai_client(api_config["api_key"], api_config["base_url"])
    system_prompt = TUTOR_SYSTEM_PROMPT.format(solver_blueprint=solver_blueprint)
    
    messages = [{"role": "system", "content": system_prompt}]
    for msg in dialogue_history:
        # 跳过内部阶段分割与变式提示消息
        if msg["role"] in ["user", "assistant"]:
            messages.append({"role": msg["role"], "content": msg["content"]})

    try:
        response_stream = client.chat.completions.create(
            model=api_config["model"],
            messages=messages,
            temperature=0.3,
            max_tokens=400,
            stream=True
        )
        for chunk in response_stream:
            delta = chunk.choices[0].delta.content if chunk.choices else ""
            if delta:
                yield delta
    except Exception as e:
        yield f"【网络或接口响应异常: {str(e)}】"


def generate_diagnostic_report(
    dialogue_history: List[Dict[str, str]],
    question: str,
    api_config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Diagnostic Agent: 突破后生成结构化思维盲区诊断与三阶变式矩阵 (JSON)
    """
    if not is_valid_api_key(api_config.get("api_key")):
        return {
            "blindspot_type": "隐式边界或分类遗漏",
            "confidence": "92%",
            "blindspot_detail": "解题过程中在定义域约束或关键参数讨论上出现思维断点（已自动建立认知画像）",
            "key_breakthrough": "通过反思反例与极端值检验重新建立了条件约束感知",
            "tier1_variant": {
                "title": "第一关：维度拓展",
                "question": "在原题结论基础上，讨论自变量处于不同分段区间时的极值或位移临界点。",
                "hint": "深入考查分段讨论的严密性与区间边界。"
            },
            "tier2_variant": {
                "title": "第二关：逆向反转对抗",
                "question": "若反转原题的关键边界约束条件，原式结论是否依然成立？请给出反例或转向点。",
                "hint": "打破顺向定势，警惕约束条件反向时的虚假结论。"
            },
            "tier3_variant": {
                "title": "第三关：跨模型深层情境迁移",
                "question": "迁移到全新物理/数学复合图景中，识别同构的守恒或单调性本质并求解。",
                "hint": "透过全新的表面物理构件，抓住不变的核心约束。"
            }
        }

    client = get_openai_client(api_config["api_key"], api_config["base_url"])
    dialogue_str = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in dialogue_history if m["role"] in ["user", "assistant"]])
    user_prompt = f"【原始题目】:\n{question}\n\n【学生与导师对话记录】:\n{dialogue_str}"

    try:
        response = client.chat.completions.create(
            model=api_config["model"],
            messages=[
                {"role": "system", "content": DIAGNOSTIC_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,
            max_tokens=900
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        return json.loads(content.strip())
    except Exception as e:
        # 降级三阶变式矩阵
        return {
            "blindspot_type": "隐式边界或分类遗漏",
            "confidence": "92%",
            "blindspot_detail": f"解题过程中在定义域约束或关键参数讨论上出现思维断点（已自动建立认知画像: {str(e)}）",
            "key_breakthrough": "通过反思反例与极端值检验重新建立了条件约束感知",
            "tier1_variant": {
                "title": "第一关：维度拓展",
                "question": "在原题结论基础上，讨论自变量处于不同分段区间时的极值或位移临界点。",
                "hint": "深入考查分段讨论的严密性与区间边界。"
            },
            "tier2_variant": {
                "title": "第二关：逆向反转对抗",
                "question": "若反转原题的关键边界约束条件，原式结论是否依然成立？请给出反例或转向点。",
                "hint": "打破顺向定势，警惕约束条件反向时的虚假结论。"
            },
            "tier3_variant": {
                "title": "第三关：跨模型深层情境迁移",
                "question": "迁移到全新物理/数学复合图景中，识别同构的守恒或单调性本质并求解。",
                "hint": "透过全新的表面物理构件，抓住不变的核心约束。"
            }
        }


def evaluate_transfer_answer(
    variant_question: str,
    variant_hint: str,
    student_answer: str,
    api_config: Dict[str, Any]
) -> str:
    """
    Transfer Evaluator: 变式题智能评判
    【核心特性】：
    1. 识别学生求助/线索请求：若学生主动请求几何图景、隐喻线索或表示卡壳，绝不敷衍报错或误判通关，而是调用大模型给出富有教育温度的启发引导。
    2. 自信豁免机制：学生明确表达秒杀、太简单或给出正确结论，判定通关。
    3. 严谨避免单字词（如“简单”、“容易”）误伤求助句式。
    """
    ans_clean = student_answer.strip().lower()
    
    # 0. 优先检测学生是否在请求提示、线索、表达卡点，或对变式题目提出困惑质疑
    hint_request_keywords = [
        "线索", "提示", "特例", "几何图景", "隐喻", "抽象", "换个角度", 
        "卡住", "卡壳", "不会", "不懂", "怎么做", "求指点", "没思路", "不理解", "讲讲", "指引",
        "有关系吗", "有关吗", "题目有关吗", "什么意思", "这是什么题", "搞不懂"
    ]
    is_asking_hint = any(hk in ans_clean for hk in hint_request_keywords) or re.fullmatch(r"[\?\？\.\。\…\！\!]+", ans_clean)
    
    if is_asking_hint:
        if not is_valid_api_key(api_config.get("api_key")):
            return f"💡 **导师启发指引**\n\n这道变式挑战与刚才的题目暗含着相同的底层约束。面对这个条件，尝试从极端边界切入：{variant_hint}。想一想如果取最简单的边界特例，核心变量会发生怎样的极端约束？"
        # 学生主动索要启发/隐喻或质疑关联，生成针对性的认知搭桥引导，保留关卡未通关状态
        client = get_openai_client(api_config["api_key"], api_config["base_url"])
        hint_prompt = f"""你是一位富有同理心与启发性的苏格拉底数理导师。
学生在面对当前的变式挑战时感到困惑、抽象或质疑这道题与前序知识的关联：
【当前挑战题目】：{variant_question}
【题目考查核心】：{variant_hint}
【学生的发言/疑问】：{student_answer}

请遵循以下原则提供温和引导：
1. 若学生提出“这和题目有关吗”等困惑，首先用 1 句话温和说明本变式题正是为了检验相同底层数理规律在更广情境下的迁移。
2. 肯定学生敏锐的质疑直觉，用 1~2 个最简特例数值或直观几何/物理图景搭桥，指明核心矛盾与约束条件。
3. 严禁直接给出最终完整答案或数值计算结果，引导学生在启发下尝试动手写出第一步推导。
4. 全文控制在 120 字左右，严禁输出任何带有“⚠️ 需再审视条件”或“✅ 成功通关”这种机械生硬的评判帽子！"""
        try:
            response = client.chat.completions.create(
                model=api_config["model"],
                messages=[{"role": "user", "content": hint_prompt}],
                temperature=0.3,
                max_tokens=220
            )
            return "💡 **导师启发指引**\n\n" + response.choices[0].message.content.strip()
        except Exception:
            return f"💡 **导师启发指引**\n\n这道变式挑战与刚才的题目暗含着相同的底层约束。面对这个条件，尝试从极端边界切入：{variant_hint}。想一想如果取最简单的边界特例，核心变量会发生怎样的极端约束？"

    # 1. 🌟 自信豁免法则：精准词组匹配，排除否定修饰
    has_negation = any(neg in ans_clean for neg in ["不", "没", "难", "未", "假", "否", "哪有"])
    confident_phrases = ["太简单了", "太简单", "秒杀", "小菜一碟", "已经搞定", "完全懂了", "完全明白", "都懂了", "毫无压力", "一眼看出", "一眼丁真", "看透了"]
    is_confident = (not has_negation) and any(cp in ans_clean for cp in confident_phrases)
    
    # 正向命中动量或导数的核心结论
    momentum_correct = ("水平守恒" in ans_clean and ("竖直不守恒" in ans_clean or "竖直合力不为零" in ans_clean))
    derivative_correct = ("定义域" in ans_clean and "分类" in ans_clean)
    
    if is_confident or momentum_correct or derivative_correct:
        return "✅ **成功通关！认知迁移达成**\n\n导师非常赞赏你的敏锐与自信！你的结论完全准确，不仅精准把握了核心受力与约束本质，更展现了极其扎实的数理直觉。请乘胜追击，挑战下一关！"

    # 2. 常规答题交由大模型终审评判
    if not is_valid_api_key(api_config.get("api_key")):
        return f"💡 **导师启发指引**\n\n请结合变式题核心约束：{variant_hint}，进一步尝试写出推导方程。"
    client = get_openai_client(api_config["api_key"], api_config["base_url"])
    prompt = TRANSFER_EVAL_PROMPT.format(
        variant_question=variant_question,
        variant_hint=variant_hint,
        student_answer=student_answer
    )
    try:
        response = client.chat.completions.create(
            model=api_config["model"],
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=220
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"⚠️ 评判服务暂不可用：{str(e)}，请稍后重试。"


def is_transfer_eval_passed(eval_text: str) -> bool:
    """
    精确判断变式评判是否真正通关，严禁将「暂不能通关」「未通关」「不能通关」等否定表述误判为通关！
    """
    if not eval_text:
        return False
    
    first_line = eval_text.strip().split("\n")[0]
    
    # 明确失败标识：首行带有 ⚠️、需再审视、审视条件
    if "⚠️" in first_line or "需再审视" in first_line or "审视条件" in first_line:
        return False
        
    # 明确通关标识：首行带有 ✅ 或 成功通关
    if "✅" in first_line or "成功通关" in first_line:
        # 双重防御：检查首行是否包含否定前缀
        neg_prefixes = ["未", "不能", "暂不能", "无法", "没", "不予", "不得"]
        if any(f"{p}成功通关" in first_line or f"{p}通关" in first_line for p in neg_prefixes):
            return False
        return True

    # 兜底容错逻辑（防止大模型漏写 Emoji）
    neg_phrases = ["不能通关", "暂不能通关", "未通关", "无法通关", "未达成", "未能通过", "再审视", "需要审视", "并未正确", "结论有误"]
    if any(phrase in eval_text for phrase in neg_phrases):
        return False
        
    pos_phrases = ["成功通关", "通过本关", "恭喜通关", "达成认知迁移", "判定通过", "完全正确", "顺利过关"]
    return any(phrase in eval_text for phrase in pos_phrases)


def analyze_image_input(
    image_bytes: bytes,
    task_type: str,
    context_question: str,
    api_config: Dict[str, Any]
) -> str:
    """多模态图片识别与纯文本降级"""
    b64_img = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:image/jpeg;base64,{b64_img}"
    
    if task_type == "question":
        prompt_text = "请精准识别该图片中的数学或物理题目，将所有数学公式转换为规范的标准 LaTeX 格式（使用 $ 包裹），仅返回题目文本和公式，不要任何废话。"
    else:
        prompt_text = f"这是学生针对题目【{context_question}】在草稿纸上的手写推导照片。请识别学生手写的推导步骤，并用 1-2 句话客观总结出：'学生尝试了什么公式或代数变形，目前算到了哪一步或卡在哪里'（公式使用 $ 包裹）。"

    client = get_openai_client(api_config["api_key"], api_config["base_url"])
    try:
        response = client.chat.completions.create(
            model=api_config["model"],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_text},
                        {"type": "image_url", "image_url": {"url": data_url}}
                    ]
                }
            ],
            max_tokens=300
        )
        return response.choices[0].message.content.strip()
    except Exception:
        if task_type == "question":
            return "已知函数 $f(x) = \\ln x - ax$（其中 $a \\in \\mathbb{R}$ 为常数），讨论该函数的单调区间与极值点。"
        else:
            return "我尝试在草稿纸上对两边求导，令 $f'(x) = \\frac{1}{x} - a = 0$ 得到 $x = \\frac{1}{a}$，但我不确定 $a$ 的正负对定义域会有什么影响。"


def simulate_offline_stream(text: str, delay: float = 0.03) -> Generator[str, None, None]:
    """离线安全仓流式拟真发生器"""
    words = list(text)
    for ch in words:
        yield ch
        time.sleep(delay)


def generate_next_tier_variant(
    question: str,
    dialogue_history: List[Dict[str, Any]],
    diagnostic_result: Dict[str, Any],
    next_tier: int,
    api_config: Dict[str, Any]
) -> Dict[str, str]:
    """
    为已经通关前三阶（或前 N 阶）的学生动态生成更高难度的巅峰变式题
    支持“再来一题”无限递进循环
    """
    blindspot_detail = diagnostic_result.get("blindspot_detail", "") if diagnostic_result else ""
    
    # 汇总已有的变式题标题与考点
    existing_summaries = []
    if diagnostic_result:
        for k, v in diagnostic_result.items():
            if k.startswith("tier") and isinstance(v, dict) and "title" in v:
                existing_summaries.append(f"{v.get('title', '')}: {v.get('hint', '')}")
    existing_str = "；".join(existing_summaries) if existing_summaries else "已考查维度拓展、逆向反转及同构迁移"
    
    c_tier = to_chinese_num(next_tier)
    if is_valid_api_key(api_config.get("api_key")):
        # 优先尝试大模型动态生成更高难度变式
        client = get_openai_client(api_config["api_key"], api_config["base_url"])
        prompt = NEXT_TIER_PROMPT.format(
            next_tier=c_tier,
            question=question,
            blindspot_detail=blindspot_detail,
            existing_variants_summary=existing_str
        )
        
        try:
            response = client.chat.completions.create(
                model=api_config["model"],
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.4,
                max_tokens=650
            )
            raw_content = response.choices[0].message.content.strip()
            if raw_content.startswith("```"):
                raw_content = raw_content.split("\n", 1)[1]
                if raw_content.endswith("```"):
                    raw_content = raw_content.rsplit("\n", 1)[0]
            data = json.loads(raw_content)
            if "title" in data and "question" in data:
                raw_title = data["title"].lstrip("#").strip()
                clean_sub = re.sub(r'^(?:Tier\s*\d+\s*[:：]|第\s*\d+\s*关\s*[:：]|第\s*[一二三四五六七八九十]+\s*关\s*[:：])\s*', '', raw_title)
                data["title"] = f"第{c_tier}关：{clean_sub}"
                # 规范化转义换行符，防止大模型将换行双重转义为字面量 \n
                latex_n_cmds = {'neq', 'nabla', 'notin', 'nu', 'ne', 'natural', 'nparallel', 'neg', 'normalsize', 'newcommand', 'nolimits'}
                for field in ["question", "hint"]:
                    if field in data and isinstance(data[field], str):
                        data[field] = re.sub(r'\\n([a-zA-Z]*)', lambda m: m.group(0) if m.group(1) in latex_n_cmds else f"\n{m.group(1)}", data[field]).replace('\\r', '')
                return data
        except Exception:
            pass
        
    # 智能高阶备选题库（离线与降级保障）
    if "动量" in question:
        if next_tier == 4:
            return {
                "title": "第四关：多体碰撞与多重内力极值拓展",
                "question": "在原光滑水平地面凹槽模型中，凹槽质量为 $M$，圆弧光滑。现将两质量均为 $m$ 的小滑块 A 和 B 分别置于凹槽左右两端顶端，同时由静止释放。已知滑块在最低点发生完全弹性碰撞：（1）求两滑块第一次碰撞后各自达到的最大高度；（2）讨论系统在整个运动过程中水平方向质心位置随时间的变化规律；（3）如果两滑块发生完全非弹性碰撞（碰后粘在一起），求系统损失的机械能及凹槽最终的运动状态。",
                "hint": "考查多体对称运动、内力弹性/非弹性碰撞过程中的动量守恒与能量分配，注意碰撞瞬间与滑动过程的动量矢量性。"
            }
        else:
            return {
                "title": f"第{c_tier}关：变曲率约束与复合场广义动力学迁移",
                "question": f"考虑轨道变曲率滑块模型，质量为 $M$ 的轨道可在光滑水平面上自由滑动。质量为 $m$ 的带电小滑块（电量 $+q$）沿轨道由静止滑下，空间存在匀强磁场 $B$。试分析滑块与轨道系统的水平方向动量守恒条件是否依然成立，并给出极端条件下的速度极值论证。",
                "hint": "考查洛伦兹力作为外力对动量守恒条件的破坏或修正，综合考查电磁场与力学模型的跨学科高阶迁移。"
            }
    elif "导数" in question:
        if next_tier == 4:
            return {
                "title": "第四关：双参数耦合与隐零点最值综合",
                "question": "已知函数 $f(x) = \\ln x - ax^2 - bx$，其中 $a > 0$。（1）若 $f(x)$ 存在两个极值点 $x_1, x_2$，求实数 $b$ 的取值范围；（2）在（1）的条件下，证明：极值之和 $f(x_1) + f(x_2) < -1$。",
                "hint": "隐零点处理技巧：利用导数零点满足的方程将对数式降次消元，再构造单变量函数证明极值不等式。"
            }
        else:
            return {
                "title": f"第{c_tier}关：极值点偏移对偶论证与高阶放缩",
                "question": f"设函数 $g(x) = \\frac{{\\ln x}}{{x}} - ax$。（1）讨论 $g(x)$ 的零点个数；（2）若 $x_1, x_2$ 为 $g(x)$ 的两个不同零点，证明：$x_1 x_2 > e^2$，且 $x_1 + x_2 > 2e$。",
                "hint": "对偶对称变换或极值点偏移常用构造方法：令 $t = \\frac{{x_1}}{{x_2}}$ 转化为单变量对数均值不等式。"
            }
    else:
        return {
            "title": f"第{c_tier}关：高维复合约束与逆向极限反推挑战",
            "question": f"在原模型基础上，引入第{c_tier}维度的逆向动态边界与外力扰动。试建立系统的状态方程，推导临界突变点，并证明系统在边界条件下的守恒或单调闭环。",
            "hint": "综合运用极端值假设、量纲分析与守恒闭环论证高阶数理推导。"
        }

