#!/bin/bash
# 停止 CogniScaffold
if docker compose version &> /dev/null; then
    docker compose down
elif command -v docker-compose &> /dev/null; then
    docker-compose down
else
    echo "未检测到 Docker Compose"
    exit 1
fi
echo "CogniScaffold 已安全停止"
