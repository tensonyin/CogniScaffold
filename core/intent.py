"""
CogniScaffold 意图分类与早退路由模块 (Intent Classifier & Early-Exit Router)
负责前置识别：
1. 情绪发泄与粗俗表达 (PROFANITY)
2. Meta 逻辑质疑与纠错 (META_QUESTION) ("这不是题目" / "这有什么关联")
3. 显式脱轨闲聊与跨学科提问 (OFF_TOPIC)
4. 低信息量输入与卡壳 (LOW_INFO)
5. 正常数理作答与求助 (IN_TOPIC)
"""

import re
from typing import Tuple

# 1. 粗俗语、情绪发泄与侮辱性表达
_PROFANITY_PATTERNS = [
    r"\b(fuck|shit|bitch|asshole|bastard|damn|crap)\b",
    r"(操你|草泥马|傻逼|煞笔|脑残|他妈的|妈的|去死|滚蛋|混蛋|王八蛋|二逼|神经病|弱智|狗屎)"
]
_COMPILED_PROFANITY = re.compile("|".join(_PROFANITY_PATTERNS), re.IGNORECASE)

# 2. Meta 纠错、上下文质疑与逻辑质疑
_META_PATTERNS = [
    r"(不是题目|这不是题目|不是刚才的题|不是原题|题目换了|换题了)",
    r"(有关系吗|有关吗|什么关联|有什么关联|和题目有关吗|和原题有关吗|和上一题有关吗)",
    r"(为什么问这个|干嘛问这个|关这个什么事|怎么突然换了|题目不对|牛头不对马嘴)",
    r"(系统bug|搞错了吧|你卡了|答非所问|胡说八道|你在胡说)"
]
_COMPILED_META = re.compile("|".join(_META_PATTERNS), re.IGNORECASE)

# 3. 显式非数理脱轨话题（文史、翻译、哲学、常识闲聊）
_OFF_TOPIC_PATTERNS = [
    r"(翻译成英文|英文怎么说|翻译一下|translate)",
    r"(李白|杜甫|唐朝|宋朝|清朝|秦始皇|汉武帝|历史事件|鸦片战争|三国演义)",
    r"(唯物辩证|存在主义|哲学思考|人生意义|爱情是什么|讲个笑话|陪我聊天)",
    r"(明天天气|今天几号|北京时间|股票行情|黄金价格|球赛结果|娱乐明星)"
]
_COMPILED_OFF_TOPIC = re.compile("|".join(_OFF_TOPIC_PATTERNS), re.IGNORECASE)

# 4. 数理学科核心词与公式特征（在轨判定依据）
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


def classify_user_intent(student_text: str, current_question: str = "") -> Tuple[str, str]:
    """
    早退路由器 (Early-Exit Router):
    - 'PROFANITY': 粗俗发泄，触发温和安抚与边界重设，严格不推新题
    - 'META_QUESTION': 质疑上下文/不是题目/有什么关联，暂停判题流，由导师出面解释认知同构逻辑
    - 'OFF_TOPIC': 完全脱离数理场景的文史/翻译/闲聊话题，优雅拉回
    - 'LOW_INFO': 极简回应（如“不知道”、“？”、“...”、“然后呢”），继续搭脚手架，绝不跳关
    - 'DEMAND_ANSWER': 催促答案，委婉拒绝并给台阶
    - 'IN_TOPIC': 正常的数理答疑、解题思路、卡点求助、求特例隐喻
    
    返回: (intent_type, guidance_text)
    """
    text = student_text.strip()
    
    # 1. 粗俗语 / 情绪发泄早退拦截
    if _COMPILED_PROFANITY.search(text):
        calm_msg = (
            "我感受到了你的挫败感或困惑，解题推导卡壳时产生情绪是非常自然的现象。"
            "深呼吸，我们可以随时放慢节奏，把复杂的大问题拆解成几个一目了然的小步骤。"
            "请随时告诉我：对于当前这道题目，你觉得最棘手或者最摸不着头脑的是哪一点？"
        )
        return "PROFANITY", calm_msg

    # 2. Meta 纠错 / 上下文脱节 / 题目关联质疑
    if _COMPILED_META.search(text):
        meta_msg = (
            "我非常理解你的困惑与警觉——这恰恰说明你在严谨地关注题目逻辑的连贯性！"
            "这里并不是凭空换题，而是当前关卡构造了一个具有**相同数理内核（相同的受力平衡或隐式约束边界）**的变式情境，专门用来检验能否脱离表面题型进行思维迁移。"
            "你可以把这道变式当成一面镜子：如果你觉得与原题无关，可以先告诉我：你觉得它们在已知条件或约束本质上最大的区别在哪里？"
        )
        return "META_QUESTION", meta_msg

    # 3. 显式脱轨检测 (明显属于文科/常识/闲聊)
    if _COMPILED_OFF_TOPIC.search(text):
        pullback_msg = (
            "我注意到你提出了一个与当前数理分析无关的话题。"
            "作为你的数理思维脚手架导师，让我们先把注意力集中在眼前的这道题目上。"
            "你能先观察一下这道题目的已知条件，试着挑出一个你最熟悉的量告诉我吗？"
        )
        return "OFF_TOPIC", pullback_msg

    # 4. 低信息量输入判定 (纯问号、单字语气词、完全无具体数理内容)
    if re.fullmatch(r"[\?\？\.\。\…\！\!]+", text) or text in ["不知道", "不懂", "不会", "不懂啊", "不明白", "没思路", "不知道怎么做"]:
        return "LOW_INFO", ""

    # 5. 如果包含明确的数理特征，直接属于 IN_TOPIC
    if _COMPILED_STEM.search(text):
        return "IN_TOPIC", ""

    # 6. 包含思维启发式求助词汇（如隐喻、线索、图景、特例）
    if any(k in text for k in ["隐喻", "线索", "图景", "特例", "极端", "抽象", "反例", "草稿"]):
        return "IN_TOPIC", ""

    # 7. 长度较短且无明显数理特征的普通催促提问
    if any(k in text for k in ["请回答我的问题", "回答我", "快点", "直接说", "别废话", "答案是什么"]):
        return "DEMAND_ANSWER", ""

    return "IN_TOPIC", ""
