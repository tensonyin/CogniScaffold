@echo off
chcp 65001 >nul
title CogniScaffold (智构思维导师)
echo [CogniScaffold] 正在启动智构思维导师交互系统...
.\.venv\Scripts\streamlit.exe run app.py --server.port 8501
pause
