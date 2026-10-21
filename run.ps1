Write-Host "[CogniScaffold] 正在启动智构思维导师系统 (100% 原版界面 极速平板架构)..." -ForegroundColor Cyan
Write-Host "本机访问:   http://localhost:8000" -ForegroundColor Green
Write-Host "局域网访问: http://192.168.110.133:8000" -ForegroundColor Yellow
& ".\.venv\Scripts\uvicorn.exe" server:app --host 0.0.0.0 --port 8000
