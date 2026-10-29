@echo off
chcp 65001 >nul
echo 正在停止 CogniScaffold 服务...
docker compose down
echo CogniScaffold 服务已安全停止。
pause
