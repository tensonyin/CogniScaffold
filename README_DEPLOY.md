# 🎓 CogniScaffold (智构思维导师) - 学校内网服务器部署指南

> 本指南专为学校老师及校园信息化管理员编写，采用 **Docker 容器化一键部署** 方案，无需手动配置复杂的 Python 运行环境或编译依赖。

---

## 一、交付安装包内容清单

解压本安装包后，目录包含以下核心文件：

| 文件 / 文件夹 | 用途说明 |
| :--- | :--- |
| `cogni-scaffold-image.tar.gz` | **Docker 离线完整镜像包**（已预装所有系统与 AI 交互依赖，约 69MB） |
| `deploy.sh` | **Linux 一键自动化部署脚本**（自动加载镜像、初始化配置并启动容器） |
| `docker-compose.yml` | Docker 容器编排配置文件（已预设端口映射与数据持久化） |
| `.env` | **大模型环境配置文件**（已预填当前可用的 DeepSeek API Key 与模型配置，开箱即用） |
| `.env.example` | 配置模板文件（备用参考） |
| `data/` | **数据持久化目录**（存放 SQLite 数据库文件与所有师生对话/画像数据） |
| `start.sh` / `stop.sh` | Linux 快捷启动与停止脚本 |
| `start.bat` / `stop.bat` | Windows 环境快捷启动与停止脚本（若学校使用 Windows Server + Docker） |
| `server.py`、`core/`、`static/` | 完整系统源码与前端资源（供学校教研组技术审计或二次扩展） |

---

## 二、部署环境要求

1. **服务器操作系统**：
   - 推荐：Ubuntu 20.04 / 22.04 LTS、Debian 11/12、CentOS 7/8/9、Rocky Linux、AlmaLinux 等主流 Linux 系统；
   - 亦支持：Windows 10/11 或 Windows Server（需安装 Docker Desktop）。
2. **运行环境依赖**：
   - 需预装 **Docker** 与 **Docker Compose**（如未安装，可联系网络管理员运行 `curl -fsSL https://get.docker.com | bash` 一键安装）。
3. **网络要求**：
   - **出站网络**：服务器需允许访问外网的大模型 API 地址（如 `https://api.deepseek.com`）。
   - **入站网络**：校园局域网内的学生平板或电脑需能通过 IP 访问该服务器的 `8501` 端口。

---

## 三、三步极速部署流程（Linux 服务器）

### 第一步：解压安装包
将收到的压缩包上传到服务器的任意工作目录（例如 `/opt/cogni-scaffold` 或 `/home/teacher/cogni-scaffold`），并解压进入目录：
```bash
# 假设上传的为 zip 压缩包
unzip CogniScaffold_School_Release.zip -d cogni-scaffold
cd cogni-scaffold

# 或者若是 tar.gz 压缩包
tar -zxvf CogniScaffold_School_Release.tar.gz
cd cogni-scaffold
```

### 第二步：执行一键部署脚本
赋予执行权限并运行 `deploy.sh`：
```bash
chmod +x deploy.sh start.sh stop.sh
./deploy.sh
```
> 脚本将自动完成：检测 Docker 环境 ➔ 导入离线镜像 ➔ 挂载数据持久化目录 ➔ 启动服务并执行健康检查。

### 第三步：访问与登录
部署成功后，终端将输出访问链接：
- **服务器本机访问**：`http://localhost:8501`
- **局域网学生与平板访问**：`http://<服务器内网IP>:8501`

---

## 四、系统初始账号与安全指引

系统首次启动时会自动初始化安全数据库，并创建默认账号：

### 1. 管理员账号（用于学生管理、限额配置、对话审查）
- **用户名**：`admin`
- **初始密码**：`Admin@Cogni2026!`
- **安全提醒**：系统开启了强安全策略，管理员账号首次登录后，**会自动弹出安全加固界面，强制要求设置密保问题并修改为您的专属新密码**，修改后旧密码将立即失效。

### 2. 预置示例学生账号
- **用户名**：`student01`
- **初始密码**：`Student@2026!`
- （管理员可在管理员后台直接批量创建全班学生的账号或导出导入）。

---

## 五、校园防火墙与网络放行（常见配置）

如果局域网内的平板或电脑无法打开网页，通常是由于服务器系统防火墙拦截了 `8501` 端口：

### 1. Ubuntu / Debian (UFW 防火墙)
```bash
sudo ufw allow 8501/tcp
sudo ufw reload
```

### 2. CentOS / RHEL (Firewalld 防火墙)
```bash
sudo firewall-cmd --zone=public --add-port=8501/tcp --permanent
sudo firewall-cmd --reload
```

---

## 六、日常运维与常见问题 (FAQ)

### Q1: 如何停止或重启系统？
- **快捷停止**：在安装目录下执行 `./stop.sh`（或 `docker compose down`）
- **快捷启动**：在安装目录下执行 `./start.sh`（或 `docker compose up -d`）
- **查看运行日志**：`docker compose logs -f`

### Q2: 如何更改对外访问端口？（例如想改成 80 端口）
打开 `docker-compose.yml` 文件，将 `ports:` 部分的 `"8501:8501"` 修改为 `"80:8501"` 即可：
```yaml
ports:
  - "80:8501" # 冒号前面为您希望对外暴露的端口
```
修改后执行 `./stop.sh && ./start.sh` 生效。

### Q3: 师生对话数据与学生答题记录保存在哪里？如何备份？
所有核心数据持久化保存在安装目录下的 `./data` 文件夹内（SQLite 数据库文件为 `data/cogni_scaffold.db`）。
- **数据备份**：只需定期复制或压缩 `data` 文件夹备份即可；
- **版本升级**：后续升级系统镜像或代码时，保留现有的 `data` 文件夹，数据绝不丢失。

### Q4: 如何更换大模型 API Key 或模型名称？
直接编辑目录下的 `.env` 文件：
```bash
OPENAI_API_KEY=您的新APIKey
OPENAI_BASE_URL=https://api.deepseek.com
MODEL_NAME=deepseek-chat
```
保存后执行 `./stop.sh && ./start.sh` 即可即时生效。
