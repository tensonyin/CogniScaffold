# CogniScaffold（智构思维导师）

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue.svg" alt="Python 3.11+" />
  <img src="https://img.shields.io/badge/Streamlit-1.35+-FF4B4B.svg" alt="Streamlit" />
  <img src="https://img.shields.io/badge/LLM-OpenAI%20%2F%20DeepSeek-green.svg" alt="LLM Compatible" />
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License MIT" />
  <img src="https://img.shields.io/badge/Live%20Demo-Online-brightgreen.svg" alt="Live Demo" />
</p>

> **“拒绝答案馈赠，通过维果茨基认知脚手架实现启发式推导与思维盲区精准透视的下一代 AI 导师系统。”**

🌐 **在线体验入口**：[https://buildfuture.tech/cogni-scaffold/](https://buildfuture.tech/cogni-scaffold/)

---

## 📖 核心教育理念与设计哲学

传统 AI 搜题或答题工具往往直接给出完整解答步骤，极易诱发学习者的**“虚假理解错觉”**与认知怠惰。

**CogniScaffold** 严格遵循维果茨基（Lev Vygotsky）的**“最近发展区（ZPD）”**与**“认知脚手架（Cognitive Scaffolding）”**理论：
1. **绝不直接提供最终答案或解题全貌**，始终扮演苏格拉底式提问者；
2. **微步反思推导**：每次交互输出严格受限（$<100$ 字），单次仅抛出一个关键引导提问；
3. **思维归因透视**：在学生突破难点后，输出结构化诊断报告，精准定位概念盲区并生成同源认知变式题，检验真实迁移能力。

---

## 🌟 核心特性与架构亮点

### 1. 双智能体解题底座（Dual-Agent Architecture）
- **解题真值底座（Solver Blueprint Agent）**：学生录入或选择题目时，后台先验生成隐式解题蓝图、核心步骤图谱及常见思维陷阱预测（完全缓存于会话后端，学生端不可见），彻底避免大语言模型的解题幻觉与盲目追问。
- **极速启发导师（Tutor Stream Agent）**：遵循启发三铁律，采用 SSE 流式实时响应，首字延迟控制在 1 秒以内。

### 2. 受控有限状态机（Controlled FSM）
- **阶段 1：锚定与推导**：启发式双向探究。
- **阶段 2：突破校验**：支持模型自主判定 `[TRIGGER_DIAGNOSIS]`，或由学生主动触发「请求突破校验」（内置防偷跑机制：必须完成至少 3 轮实质交互后才解锁）。
- **阶段 3：深度思维诊断**：从直觉层、概念层、逻辑链条三个维度生成透视分析报告。
- **阶段 4：同构变式强化**：提供同源题测试，检验概念迁移闭环。

### 3. 多学科支持与多模态公式渲染
- **跨学科题目库**：内置数学（高考导数单调性）、物理（带电粒子在复合场运动）、化学（平衡常数移动与多重平衡）、信息学（区间动态规划最优化）等多学科黄金示范案例。
- **LaTeX 极速公式支持**：支持行内 `$ ... $` 与块级 `$$ ... $$` 实时渲染，配备紧凑公式快捷输入芯片（$x^2$, $\sqrt{x}$, $\frac{a}{b}$, $\ln(x)$, $f'(x)$, $\int$ 等）。

### 4. 演示安全仓（Offline Demo Mode）
- 内置离线拟真剧本与黄金交互流，即使在无外部网络或 API 限流场景下，亦能 100% 稳定进行学术汇报与教学路演演示。

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
OPENAI_BASE_URL=https://api.openai.com/v1
MODEL_NAME=deepseek-chat
```

### 3. 运行本地开发服务
```bash
streamlit run app.py
```
在浏览器打开 `http://localhost:8501` 即可体验。

---

## 🐳 Docker 生产部署

本项目已针对生产容器化与云端反向代理优化：

```bash
# 1. 构建 Docker 镜像
docker build -t cogni-scaffold-app:latest .

# 2. 运行容器（挂载外部持久化数据目录）
docker run -d --name cogni-scaffold \
  -p 8501:8501 \
  -v $(pwd)/data:/app/data \
  --restart always \
  cogni-scaffold-app:latest
```

如需配置 Nginx / OpenResty 反向代理（支持子路径与 WebSocket 穿透），可参考项目中的 `buildfuture.tech.conf` 模板。

---

## 📁 目录结构

```text
cogni-scaffold/
├── app.py                  # Streamlit 主交互页面与前端逻辑
├── core/
│   ├── engine.py           # 双智能体逻辑、流式生成与状态机调度
│   ├── prompts.py          # 导师宪法、解题底座与认知诊断提示词工程
│   └── presets.py          # 多学科黄金案例库与离线拟真剧本
├── components/             # 前端定制 UI 组件库
├── data/                   # 本地持久化题库与学生会话历史记录
├── Dockerfile              # 生产级多阶段 Docker 镜像构建清单
├── requirements.txt        # Python 核心依赖清单
├── .env.example            # 环境变量模板
└── README.md               # 项目主说明文档
```

---

## 📄 开源许可证

本项目基于 [MIT License](LICENSE) 开源。
