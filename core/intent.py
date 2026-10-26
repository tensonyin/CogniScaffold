"""
CogniScaffold 意图分类与早退路由模块 (Intent Classifier & Early-Exit Router)
全面支持浙江高中十门学科（语数英+七选三）及通用拓展：
1. 双轨智能识别：数理技术推导轨 (STEM Track) vs 人文社科思辨轨 (Humanities Track)
2. 情绪发泄与粗俗表达拦截 (PROFANITY)
3. 认知同构与跨关卡逻辑质疑响应 (META_QUESTION)
4. 纯闲聊与脱轨话题温和拉回 (OFF_TOPIC)
5. 启发式作答与深层求助放行 (IN_TOPIC)
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

# 3. 显式脱轨闲聊（非学术、纯娱乐明星八卦、网络水聊、投机金融与无意义闲聊）
_OFF_TOPIC_PATTERNS = [
    r"((?:今天|明天|后天)?天气|今天几号|几点了|北京时间|股票行情|黄金价格|比特币|球赛结果|娱乐明星|明星八卦|谁最帅|谁最漂亮|讲个笑话|玩游戏|王者荣耀|打王者|和平精英|吃鸡|抽卡|原神|崩铁)",
    r"(今天吃什么|中午吃什么|晚上吃什么|陪我聊五毛钱|你多大了|你有感情吗|讲个鬼故事|测算命运|星座运势)"
]
_COMPILED_OFF_TOPIC = re.compile("|".join(_OFF_TOPIC_PATTERNS), re.IGNORECASE)

# 4. 数理技术学科关键词（STEM Track）
_STEM_INDICATORS = [
    r"[a-zA-Z]\s*[=><\+\-\*/\^]",  # 代数式
    r"\\(frac|sqrt|sin|cos|tan|ln|log|alpha|beta|theta|pi|int|sum|lim)",  # LaTeX 公式
    r"(导数|极值|单调|斜率|切线|零点|函数|定义域|值域|方程|不等式|解析几何|椭圆|双曲线|抛物线|三角函数|数列)",
    r"(动量|冲量|能量|功|动能|势能|守恒|受力|牛顿|加速度|速度|合外力|摩擦力|支持力|分量|矢量|电场|磁场|洛伦兹力)",
    r"(化学|平衡|水解|电离|浓度|沉淀|溶液|PH|电荷|物料|离子|原电池|电解池|官能团|同分异构)",
    r"(光合|呼吸|减数分裂|遗传|基因|DNA|染色体|突变|稳态|神经|激素|免疫|生态系统)",
    r"(代码|算法|二叉树|逻辑门|比较器|电平|电阻|电容|电压|电流|电路|555|继电器|三极管)"
]
_COMPILED_STEM = re.compile("|".join(_STEM_INDICATORS), re.IGNORECASE)

# 5. 人文社科思辨关键词（Humanities & Social Sciences Track）
_HUMANITIES_INDICATORS = [
    r"(史料|朝代|变法|改革|战争|条约|封建|殖民|宗法|郡县|科举|洋务|戊戌|辛亥|晚清|民国|资本主义|官僚|阶级)",
    r"(唯物|辩证|矛盾|主观|客观|生产力|生产关系|经济基础|上层建筑|市场调节|宏观调控|民主|法治|制度|价值判断)",
    r"(现代文|文言文|主旨|论点|论据|论证|修辞|隐喻|象征|意象|虚词|通假|古今异义|词类活用|因果链|语境|段落)",
    r"(气候|季风|洋流|大气环流|板块|地形|地貌|水文|区位|人口迁移|城市化|工业区位|农业区位|生态脆弱)",
    r"(因果|逻辑|悖论|假说|稻草人|隐性前提|以偏概全|论证漏洞|立论|驳论|反例证据|自洽|反事实)"
]
_COMPILED_HUMANITIES = re.compile("|".join(_HUMANITIES_INDICATORS), re.IGNORECASE)


def detect_subject_track(context_text: str) -> str:
    """
    根据题目文本或上下文智能推断学科大轨：
    - 'stem': 数理技术推导轨（数学、物理、化学、生物、技术）
    - 'humanities': 人文社科思辨轨（语文、英语、历史、政治、地理、通识逻辑）
    """
    if not context_text:
        return "stem"
    
    stem_matches = len(_COMPILED_STEM.findall(context_text))
    hum_matches = len(_COMPILED_HUMANITIES.findall(context_text))
    
    # 包含 LaTeX 公式结构强烈倾向于理科
    if "$" in context_text or "\\" in context_text:
        stem_matches += 2
        
    if hum_matches > stem_matches:
        return "humanities"
    return "stem"


def classify_user_intent(student_text: str, current_question: str = "") -> Tuple[str, str]:
    """
    全学科早退路由器 (Early-Exit Router):
    - 'PROFANITY': 粗俗发泄，触发温和安抚与边界重设，严格不推新题
    - 'META_QUESTION': 质疑上下文/不是题目/有什么关联，由导师出面解释底层认知同构逻辑
    - 'OFF_TOPIC': 脱离当前学科探究的纯闲聊/八卦话题，优雅拉回
    - 'LOW_INFO': 极简回应（如“不知道”、“？”、“...”、“然后呢”），继续搭脚手架，绝不跳关
    - 'DEMAND_ANSWER': 催促答案或索要范文，委婉拒绝并给台阶
    - 'IN_TOPIC': 正常的学科作答、解题思路、卡点求助、求特例/史料/隐喻线索
    
    返回: (intent_type, guidance_text)
    """
    text = student_text.strip()
    track = detect_subject_track(current_question + " " + text)
    
    # 1. 粗俗语 / 情绪发泄早退拦截
    if _COMPILED_PROFANITY.search(text):
        calm_msg = (
            "我感受到了你的困惑或挫败感，思维推导与深度辨析卡壳时产生情绪是非常自然的现象。"
            "深呼吸，我们可以放慢节奏，把复杂的大问题拆解成几个一目了然的小步骤。"
            "请随时告诉我：对于当前这道题目，你觉得最棘手或者最摸不着头脑的是哪一点？"
        )
        return "PROFANITY", calm_msg

    # 2. Meta 纠错 / 上下文脱节 / 题目关联质疑
    if _COMPILED_META.search(text):
        if track == "humanities":
            meta_msg = (
                "我非常理解你的警觉——这恰恰说明你在严谨关注论证脉络的连贯性！"
                "这里并不是凭空换题，而是当前关卡构造了一个具有**相同认知内核（相同的底层因果机制、反事实对抗逻辑或史料实证陷阱）**的变式情境，专门用来检验能否脱离表面题型进行高阶思维迁移。"
                "你可以把这道变式当成一面镜子：如果你觉得与原题无关，可以先告诉我：你觉得它们在前提条件或论证机制上最大的区别在哪里？"
            )
        else:
            meta_msg = (
                "我非常理解你的困惑与警觉——这恰恰说明你在严谨关注题目逻辑的连贯性！"
                "这里并不是凭空换题，而是当前关卡构造了一个具有**相同数理内核（相同的守恒本质或隐式约束边界）**的变式情境，专门用来检验能否脱离表面题型进行思维迁移。"
                "你可以把这道变式当成一面镜子：如果你觉得与原题无关，可以先告诉我：你觉得它们在已知条件或约束本质上最大的区别在哪里？"
            )
        return "META_QUESTION", meta_msg

    # 3. 显式脱轨检测 (纯闲聊/八卦/游戏/无意义水聊)
    if _COMPILED_OFF_TOPIC.search(text):
        if track == "humanities":
            pullback_msg = (
                "我注意到你的发言偏离了当前的人文社科与批判性思辨议题。"
                "作为你的认知思维脚手架导师，让我们先把注意力集中在眼前的这道题目上。"
                "你能先观察一下这道题目的背景材料，试着挑出一个你认为最关键的论据或概念告诉我吗？"
            )
        else:
            pullback_msg = (
                "我注意到你提出了一个与当前数理推导无关的话题。"
                "作为你的认知思维脚手架导师，让我们先把注意力集中在眼前的这道题目上。"
                "你能先观察一下这道题目的已知条件，试着挑出一个你最熟悉的量告诉我吗？"
            )
        return "OFF_TOPIC", pullback_msg

    # 4. 低信息量输入判定 (纯问号、单字语气词、完全无实质内容)
    if re.fullmatch(r"[\?\？\.\。\…\！\!]+", text) or text in ["不知道", "不懂", "不会", "不懂啊", "不明白", "没思路", "不知道怎么做", "完全不会"]:
        return "LOW_INFO", ""

    # 5. 长度较短且无明显学科特征的催促要答案/要范文
    if any(k in text for k in ["请回答我的问题", "回答我", "快点", "直接说", "别废话", "答案是什么", "给范文", "直接给答案"]):
        return "DEMAND_ANSWER", ""

    # 6. 在轨放行（数理技术、人文社科或思维启发词汇）
    return "IN_TOPIC", ""
