@echo off
chcp 65001 >nul
title CogniScaffold (智构思维导师)
echo ========================================================
echo  [CogniScaffold] 正在启动智构思维导师容器...
echo ========================================================

where docker >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 本机未检测到 Docker，请先安装 Docker Desktop！
    pause
    exit /b 1
)

if exist cogni-scaffold-image.tar.gz (
    echo 正在检查离线镜像包...
    docker load -i cogni-scaffold-image.tar.gz
)

if not exist data mkdir data

docker compose up -d

echo ========================================================
echo  CogniScaffold 启动完成！
echo  本机访问地址: http://localhost:8501
echo ========================================================
pause
