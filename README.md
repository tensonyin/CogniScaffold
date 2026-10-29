# 知阶 CogniScaffold

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue.svg" alt="Python 3.11+" />
  <img src="https://img.shields.io/badge/FastAPI-0.110+-009688.svg" alt="FastAPI" />
  <img src="https://img.shields.io/badge/LLM-DeepSeek%20%2F%20OpenAI-green.svg" alt="LLM Compatible" />
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License MIT" />
  <img src="https://img.shields.io/badge/Live%20Demo-Online-brightgreen.svg" alt="Live Demo" />
</p>

> **“拒绝答案馈赠，通过维果茨基认知脚手架实现启发式推导与思维盲区精准透视的全学科 AI 导师系统。”**
>
> 深度适配**浙江新高考十门学科（语文、数学、英语 + 物理、化学、生物、政治、历史、地理、技术）**拔尖思辨与**通用跨学科探究拓展**需求。

🌐 **在线体验入口**：[https://buildfuture.tech/cogni-scaffold/](https://buildfuture.tech/cogni-scaffold/)

---

## 📖 核心教育理念与设计哲学

传统搜题答题工具往往直接给出完整解答步骤或套路范文，极易诱发学习者的**“虚假理解错觉”**与认知怠惰。

**知阶 CogniScaffold** 严格遵循维果茨基（Lev Vygotsky）的**“最近发展区（ZPD）”**与苏格拉底**“产婆术”**教育哲学：
1. **绝不直接提供最终答案、标准步骤或范文套话**，始终扮演启发式提问者；
2. **微步反思推导**：每次交互输出严格受限（建议 150–250 字），单次聚焦推进一个思维微台阶；
3. **思维归因透视**：在学生突破关键卡点后，自动生成结构化诊断画像，剖析认知偏差成因，并提供三阶对抗变式矩阵检验真实迁移能力。

---

## 🌟 核心特性与架构亮点

### 1. 文理分流双轨制架构（Dual-Track Cognitive Architecture）
系统内置智能学科感知分类器，针对不同学科特性自动切换到最适配的认知脚手架模式：
- **📐 数理技术推导轨（STEM & Tech Track）**：
  - 覆盖数学、物理、化学、生物、通用技术与信息技术；
  - 核心引导方法：严密数理逻辑演绎、隐式边界审视、极端特例检验、公式与算法解构、受力几何微图景隐喻。
- **📚 人文社科思辨轨（Humanities & Social Sciences Track）**：
  - 覆盖语文、英语、历史、思想政治、地理及通识逻辑；
  - 核心引导方法：史料/文本证据实证、核心概念内涵与外延辨析、多维因果机制拆解、反事实推演（Counterfactual Thinking）、立场对立反驳与论证漏洞审查。

### 2. 双智能体解题与思辨底座（Dual-Agent Architecture）
- **真值基准底座（Solver Blueprint Agent）**：学生开题时，后台先验构建隐式知识蓝图与思维暗坑预测字典（缓存于会话后端，学生端不可见），消除大语言模型的幻觉追问与无序发散。
- **极速启发导师（Tutor Stream Agent）**：遵循启发三铁律，采用 SSE 流式实时响应，首字延迟控制在 1 秒左右，严禁替代学生做出定性结论。

### 3. 上下文动态意图对齐与早退路由（Intent Classifier & Early-Exit Router）
- **解禁人文学科深度探讨**：全面放行文史哲、语言翻译、政治经济与地理综合要素的学术探讨；
- **精准拦截无意义闲聊**：将脱轨（OFF_TOPIC）聚焦于纯娱乐八卦、网络水聊与恶意注入，根据当前题目的文理轨道优雅拉回当前探究核心；
- **Meta 逻辑质疑温和释疑**：当学生质疑变式题目关联时，由导师温和解释底层认知同构逻辑。

### 4. 全学科三阶渐进对抗变式矩阵（Adaptive 3-Tier Variant Matrix）
突破原始卡点后，诊断 Agent 生成针对性的三阶强化闯关关卡，并支持“再来一题”无限层层递进：
- **第一关：维度拓展（Tier 1）**：数理拓展区间参数，文史拓展更广时空背景或多元利益维度；
- **第二关：逆向反转对抗（Tier 2）**：数理反转边界条件，文史设置反事实假设或对立派别立场，专门破坏思维惯性；
- **第三关：跨模型深层情境迁移（Tier 3）**：脱离原题表面构件，跨入全新复合图景或时代议题，检验底层同构规律；
- **自信豁免评判**：落实尊重学生的自主表达，对清晰掌握底层逻辑的学生给予热烈肯定并快速通关，杜绝诛心式恶意挑刺。

### 5. 现代化全学科工作台与全景色彩模式（Light / Dark Mode）
- **像素级 Chrome 标签栏**：支持 HTML5 原生拖拽排序、多会话并行探索、一键新建、星标收藏与历史归档抽屉。
- **文理均衡经典案例库**：内置数学导数、物理动量、历史史料、语文论证思辨等多学科黄金示范案例，配备分类筛选切换 Tab。
- **全学科公式与 Markdown 渲染**：KaTeX 极速排版与全学科数学物理符号快捷键盘。
- **离线演示安全仓（Offline Demo Mode）**：内置离线仿真剧本，即使在无网络或外部 API 限流场景下，亦能 100% 稳定运行。

---

## 🚀 快速启动

### 1. 克隆代码与依赖准备
```bash
git clone https://github.com/tensonyin/CogniScaffold.git
cd CogniScaffold

# 创建并激活 Python 3.11+ 虚拟环境
python -m venv .venv
# Windows:
.\.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置大模型 API 密钥
复制模板文件并填写你的 OpenAI 兼容 API 密钥（推荐 DeepSeek、GPT-4o 等）：
```bash
cp .env.example .env
```
编辑 `.env`：
```ini
OPENAI_API_KEY=sk-xxxxxx
OPENAI_BASE_URL=https://api.deepseek.com
MODEL_NAME=deepseek-chat
```

### 3. 运行本地开发服务
```bash
# Windows
run.bat
# 或使用 PowerShell
.\run.ps1
# 或直接启动 uvicorn
uvicorn server:app --host 0.0.0.0 --port 8000
```
在浏览器打开 `http://localhost:8000` 即可体验。

---

## 🐳 Docker 生产部署

本项目已针对生产容器化与云端反向代理深度优化：

```bash
# 1. 构建 Docker 镜像
docker build -t cogni-scaffold-app:latest .

# 2. 运行容器（挂载外部持久化数据目录与配置文件）
docker run -d --name cogni-scaffold \
  -p 127.0.0.1:8501:8501 \
  --env-file .env \
  -v $(pwd)/.env:/app/.env:ro \
  -v $(pwd)/data:/app/data \
  --restart always \
  cogni-scaffold-app:latest
```

如需配置 Nginx / OpenResty 反向代理（支持子路径与 SSE 流式穿透），可参考项目中的 `buildfuture.tech.conf` 模板。

---

## 📁 目录结构

```text
cogni-scaffold/
├── server.py               # 高性能 FastAPI 服务、路由分发与 SSE 流式驱动
├── static/
│   ├── index.html          # 纯前端现代化全学科工作台（支持暗亮模式/全学科案例/Chrome拖拽标签）
│   └── vendor/             # 离线 KaTeX 与 Marked.js 静态引擎资源
├── core/
│   ├── engine.py           # 双智能体逻辑、文理双轨流式生成与有限状态机调度
│   ├── prompts.py          # 导师宪法、双轨解题底座与认知诊断提示词工程
│   ├── intent.py           # 学科分类识别、意图分类与早退路由
│   ├── presets.py          # 浙江十科与高阶思辨黄金案例库与离线拟真剧本
│   ├── latex_presets.py    # 常用全学科数理化技术 LaTeX 符号分类体系
│   └── storage.py          # 多会话持久化存储、排序与归档管理
├── data/                   # 本地持久化题库与学生会话历史记录
├── Dockerfile              # 生产级 Docker 镜像构建清单
├── requirements.txt        # Python 核心依赖清单
├── .env.example            # 环境变量模板
└── README.md               # 项目主说明文档
```

---

## 📄 开源许可证

本项目基于 [MIT License](LICENSE) 开源。
