"""
CogniScaffold 架构级断路器 (Circuit Breaker & Guardrails)
负责前置安全审查硬熔断与大模型后置拒答检测防御
"""

import re
from typing import Tuple, Optional

# 敏感与违规高风险模式库（覆盖政治事件、色情暴力、违法乱纪、系统注入攻击）
_SENSITIVE_PATTERNS = [
    r"天安门", r"六四", r"8964", r"八九民运", r"法轮功", r"李洪志", r"真善忍",
    r"颠覆政权", r"分裂国家", r"独立运动", r"西藏独立", r"新疆独立", r"台湾独立",
    r"翻墙教程", r"vpn翻墙", r"购买毒品", r"制作炸弹", r"自杀方法", r"色情视频",
    r"约炮", r"黄色网站", r"枪支购买", r"暗网网址", r"黑客攻击教程", r"洗钱指南",
    r"代开假发票", r"高考作弊器材", r"买卖高考答案"
]

_COMPILED_SENSITIVE = re.compile("|".join(_SENSITIVE_PATTERNS), re.IGNORECASE)

# 统一合规拒答文案
STANDARD_REFUSAL_MESSAGE = (
    "抱歉，该内容涉及敏感或违规话题，我无法予以回应。"
    "如果你在数理化学科学习或题目分析上有任何疑问，我很乐意继续陪你一起探讨。"
)

# 大模型输出的拒答特征检测
_MODEL_REFUSAL_PATTERNS = [
    r"我无法回应这个内容",
    r"我无法回答此问题",
    r"抱歉，我不能讨论",
    r"涉及敏感话题",
    r"违背了安全准则",
    r"根据相关法律法规.*无法",
    r"作为一个人工智能.*无法讨论"
]
_COMPILED_MODEL_REFUSAL = re.compile("|".join(_MODEL_REFUSAL_PATTERNS), re.IGNORECASE)


def check_input_guardrail(text: str) -> Tuple[bool, Optional[str]]:
    """
    断路器 1：前置安全与合规检测 (Fast Circuit Breaker)
    返回: (is_blocked: bool, refusal_response: Optional[str])
    若命中敏感违规，立即返回 True 和标准拒答文本，直接阻断后续大模型调用与状态机流转。
    """
    if not text or not isinstance(text, str):
        return False, None
        
    cleaned = text.strip()
    if _COMPILED_SENSITIVE.search(cleaned):
        return True, STANDARD_REFUSAL_MESSAGE
        
    return False, None


def check_output_refusal(model_output: str) -> bool:
    """
    断路器 2：后置大模型安全拒答熔断器 (Output Guardrail)
    检测大模型返回的文本中是否包含合规拒答特征。
    如果包含，立即执行熔断剥离，禁止任何后续阶段推进与题库拼接！
    """
    if not model_output or not isinstance(model_output, str):
        return False
        
    return bool(_COMPILED_MODEL_REFUSAL.search(model_output))
