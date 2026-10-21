@echo off
chcp 65001 >nul
title CogniScaffold (智构思维导师 - 极速内网引擎)
echo ========================================================
echo  [CogniScaffold] 正在启动智构思维导师系统 (100%% 原版界面 极速平板架构)...
echo  本机访问地址:   http://localhost:8000
echo  局域网平板访问: http://192.168.110.133:8000
echo ========================================================
.\.venv\Scripts\uvicorn.exe server:app --host 0.0.0.0 --port 8000
pause
