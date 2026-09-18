#!/bin/zsh
# FontCop 一键启动：虚拟环境 + 服务 + 托盘
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv && .venv/bin/pip install -q pillow numpy scipy fonttools pystray; fi
.venv/bin/python -m src.server &
SERVER_PID=$!
sleep 2
.venv/bin/python -m src.tray &
TRAY_PID=$!
echo "FontCop 运行中: http://127.0.0.1:8642  (server=$SERVER_PID tray=$TRAY_PID)"
echo "退出: kill $SERVER_PID $TRAY_PID"
wait
