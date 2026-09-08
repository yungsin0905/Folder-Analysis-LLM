@echo off
REM ==========================================
REM 一键启动 Docbot 后端 + Cloudflare Tunnel
REM 双击这个文件即可，不用再手动敲命令
REM ==========================================

REM 如果你的项目路径不是这个，改成你实际的路径
cd /d "C:\Users\user\Desktop\Website"

echo 正在启动后端 (uvicorn)...
start "Docbot Backend" cmd /k "call .venv\Scripts\activate.bat && uvicorn llm.phase1:app --reload --host 127.0.0.1 --port 8000"

REM 等5秒，确保后端先启动起来，再开隧道
timeout /t 5 /nobreak >nul

echo 正在启动 Cloudflare Tunnel...
start "Cloudflare Tunnel" cmd /k "C:\cloudflared\cloudflared.exe tunnel --url http://127.0.0.1:8000"

echo.
echo 已启动两个窗口：一个是后端，一个是隧道。
echo 请在"Cloudflare Tunnel"窗口里查看新生成的网址，并更新到网页前端配置里。
echo 这两个窗口不要关闭，关闭了服务就停了。
pause