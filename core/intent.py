"""
CogniScaffold 意图分类与脱轨检测模块 (Intent Classifier & Off-topic Detector)
负责检测用户是否偏离数理答疑场景，提供有教育温度的优雅拉回，严禁状态机错误推进
"""

import re
from typing import Tuple

# 数理学科核心词与公式特征（在轨判定依据）
_STEM_INDICATORS = [
    r"[a-zA-Z]\s*[=><\+\-\*/\^]",  # 代数式
    r"\\(frac|sqrt|sin|cos|tan|ln|log|alpha|beta|theta|pi|int|sum|lim)",  # LaTeX 公式
    r"(导数|极值|单调|斜率|切线|零点|函数|定义域|值域|方程|不等式)",
    r"(动量|冲量|能量|功|动能|势能|守恒|受力|牛顿|加速度|速度|合外力|摩擦力|支持力|分量|矢量)",
    r"(化学|平衡|水解|电离|浓度|沉淀|溶液|PH|电荷|物料|离子)",
    r"(代码|算法|二叉树|逻辑门|比较器|电平|电阻|电容|电压|电流|电路)",
    r"(几何|三角形|高|斜边|面积|体积|角度|垂线|平分线|圆|抛物线|双曲线|椭圆)"
]
_COMPILED_STEM = re.compile("|".join(_STEM_INDICATORS), re.IGNORECASE)

# 显式非数理脱轨话题（文史、翻译、哲学、常识闲聊）
_OFF_TOPIC_INDICATORS = [
    r"(翻译成英文|英文怎么说|翻译一下|translate)",
    r"(李白|杜甫|唐朝|宋朝|清朝|秦始皇|汉武帝|历史事件|鸦片战争|三国演义)",
    r"(唯物辩证|存在主义|哲学思考|人生意义|爱情是什么|讲个笑话|陪我聊天)",
    r"(明天天气|今天几号|北京时间|股票行情|黄金价格|球赛结果|娱乐明星)"
]
_COMPILED_OFF_TOPIC = re.compile("|".join(_OFF_TOPIC_INDICATORS), re.IGNORECASE)


def classify_user_intent(student_text: str, current_question: str = "") -> Tuple[str, str]:
    """
    分类用户意图:
    - 'IN_TOPIC': 数理答疑、解题思路、卡点求助、求特例隐喻
    - 'LOW_INFO': 极简回应（如“不知道”、“？”、“...”、“然后呢”），需要继续搭脚手架，但不能跳关
    - 'OFF_TOPIC': 完全脱离数理场景的文史/翻译/闲聊话题，需要优雅拉回
    
    返回: (intent_type, message_or_guidance)
    """
    text = student_text.strip()
    
    # 1. 低信息量输入判定 (纯问号、单字语气词、完全无具体数理内容)
    if re.fullmatch(r"[\?\？\.\。\…\！\!]+", text) or text in ["不知道", "不懂", "不会", "不懂啊", "不明白", "没思路", "不知道怎么做"]:
        return "LOW_INFO", ""

    # 2. 显式脱轨检测 (明显属于文科/常识/闲聊)
    if _COMPILED_OFF_TOPIC.search(text):
        pullback_msg = (
            "我注意到你提出了一个与当前数理分析无关的话题。"
            "作为你的数理思维脚手架导师，让我们先把注意力集中在眼前的这道题目上。"
            "你能先观察一下这道题目的已知条件，试着挑出一个你最熟悉的量告诉我吗？"
        )
        return "OFF_TOPIC", pullback_msg

    # 3. 如果包含明确的数理特征，直接属于 IN_TOPIC
    if _COMPILED_STEM.search(text):
        return "IN_TOPIC", ""

    # 4. 包含思维启发式求助词汇（如隐喻、线索、图景、特例）
    if any(k in text for k in ["隐喻", "线索", "图景", "特例", "极端", "抽象", "反例", "草稿"]):
        return "IN_TOPIC", ""

    # 5. 长度较短且无明显数理特征的普通提问（如“请回答我的问题”、“快点给答案”）
    if any(k in text for k in ["请回答我的问题", "回答我", "快点", "直接说", "别废话", "答案是什么"]):
        return "DEMAND_ANSWER", ""

    return "IN_TOPIC", ""
