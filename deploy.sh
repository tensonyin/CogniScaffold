#!/bin/bash
# ==============================================================================
# CogniScaffold (智构思维导师) - 学校内网服务器一键自动化部署脚本
# 适用环境：Ubuntu / Debian / CentOS / RHEL / Rocky Linux (需已安装 Docker)
# ==============================================================================

set -e

# 终端输出颜色
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}====================================================================${NC}"
echo -e "${BLUE}        🚀 CogniScaffold (智构思维导师) 学校内网一键部署程序        ${NC}"
echo -e "${BLUE}====================================================================${NC}"

# 1. 检查 Docker 环境
echo -e "\n${YELLOW}[步骤 1/5] 检查 Docker 与 Docker Compose 运行环境...${NC}"
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ 错误：未检测到 Docker！请先安装 Docker (https://docs.docker.com/engine/install/) 后重试。${NC}"
    exit 1
fi

COMPOSE_CMD=""
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
else
    echo -e "${RED}❌ 错误：未检测到 Docker Compose！请安装 Docker Compose 插件。${NC}"
    exit 1
fi
echo -e "${GREEN}✔ Docker 环境检测通过 (${COMPOSE_CMD})${NC}"

# 2. 载入离线 Docker 镜像（如果存在）
echo -e "\n${YELLOW}[步骤 2/5] 检查并加载 Docker 离线镜像...${NC}"
IMAGE_FILE="cogni-scaffold-image.tar.gz"
if [ -f "$IMAGE_FILE" ]; then
    echo -e "发现离线镜像包 $IMAGE_FILE，正在加载至本地 Docker..."
    docker load -i "$IMAGE_FILE"
    echo -e "${GREEN}✔ 离线镜像加载成功：cogni-scaffold-app:latest${NC}"
else
    echo -e "未发现 $IMAGE_FILE，将尝试通过本地已有镜像或自动构建运行。"
fi

# 3. 检查环境变量配置
echo -e "\n${YELLOW}[步骤 3/5] 检查环境配置文件 (.env)...${NC}"
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo -e "${YELLOW}未检测到 .env 文件，已自动从 .env.example 复制生成。${NC}"
        cp .env.example .env
    else
        echo -e "${RED}❌ 错误：缺少 .env 配置文件，请检查压缩包完整性。${NC}"
        exit 1
    fi
fi
echo -e "${GREEN}✔ 配置文件 (.env) 准备就绪${NC}"

# 4. 创建并授权数据目录
echo -e "\n${YELLOW}[步骤 4/5] 初始化持久化数据目录 (./data)...${NC}"
mkdir -p data
chmod 777 data
echo -e "${GREEN}✔ 数据目录已就绪 (SQLite 数据库与学生数据持久保存在 ./data 目录下)${NC}"

# 5. 启动服务容器
echo -e "\n${YELLOW}[步骤 5/5] 启动 CogniScaffold 服务容器...${NC}"
$COMPOSE_CMD down 2>/dev/null || true
$COMPOSE_CMD up -d

echo -e "正在等待系统完成初次初始化与健康检查 (5秒)..."
sleep 5

# 获取本机内网 IP 地址
HOST_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ -z "$HOST_IP" ]; then
    HOST_IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{print $7}')
fi
if [ -z "$HOST_IP" ]; then
    HOST_IP="<服务器内网IP>"
fi

echo -e "\n${GREEN}====================================================================${NC}"
echo -e "${GREEN}        🎉 CogniScaffold (智构思维导师) 部署成功并已启动！        ${NC}"
echo -e "${GREEN}====================================================================${NC}"
echo -e "📌 本地访问地址:       ${BLUE}http://localhost:8501${NC}"
echo -e "📌 局域网平板/电脑访问: ${BLUE}http://${HOST_IP}:8501${NC}"
echo -e "--------------------------------------------------------------------"
echo -e "🔑 预置管理员账号:"
echo -e "   用户名:   ${YELLOW}admin${NC}"
echo -e "   默认密码: ${YELLOW}Admin@Cogni2026!${NC} (首次登录系统会强制要求修改为专属新密码)"
echo -e "🔑 预置示例学生账号:"
echo -e "   用户名:   ${YELLOW}student01${NC}"
echo -e "   默认密码: ${YELLOW}Student@2026!${NC}"
echo -e "--------------------------------------------------------------------"
echo -e "🛠️ 常用运维管理命令:"
echo -e "   查看运行状态: $COMPOSE_CMD ps"
echo -e "   查看实时日志: $COMPOSE_CMD logs -f"
echo -e "   停止服务:     $COMPOSE_CMD down"
echo -e "   重启服务:     $COMPOSE_CMD restart"
echo -e "====================================================================\n"
