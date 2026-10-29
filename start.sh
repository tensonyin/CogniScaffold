#!/bin/bash
# 启动 CogniScaffold
if docker compose version &> /dev/null; then
    docker compose up -d
elif command -v docker-compose &> /dev/null; then
    docker-compose up -d
else
    echo "未检测到 Docker Compose"
    exit 1
fi
echo "CogniScaffold 已启动：http://localhost:8501"
