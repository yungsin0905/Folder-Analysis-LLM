@echo off
REM ==========================================
REM 一键启动 Docbot 后端 + ngrok 固定隧道
REM 双击这个文件即可，不用再手动敲命令
REM 也可以把这个文件的快捷方式放进开机启动文件夹，实现开机自动运行
REM ==========================================

REM 如果你的项目路径不是这个，改成你实际的路径
cd /d "C:\Users\user\Desktop\Website"

echo 正在启动后端 (uvicorn)...
start "Docbot Backend" cmd /k "call .venv\Scripts\activate.bat && uvicorn llm.phase1:app --reload --host 127.0.0.1 --port 8000"

REM 等5秒，确保后端先启动起来，再开隧道
timeout /t 5 /nobreak >nul

echo 正在启动 ngrok 固定隧道...
start "ngrok Tunnel" cmd /k "ngrok http 8000 --url=https://alias-bamboo-float.ngrok-free.dev"

echo.
echo 已启动两个窗口：一个是后端，一个是 ngrok 隧道。
echo 固定地址是: https://alias-bamboo-float.ngrok-free.dev
echo 这个地址不会变，不用再更新前端配置。
echo 这两个窗口不要关闭，关闭了服务就停了。
pause