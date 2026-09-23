@echo off
rem FontCop 本地启动脚本（Windows）：双击即起服务并打开浏览器。
rem 依赖同目录的 python-runtime\python.exe（独立 Python，由 build_python.bat 生成）。
cd /d %~dp0

if not exist python-runtime\python.exe (
    echo [FontCop] 未找到 python-runtime\python.exe
    echo 请先运行：build_python.bat  （首次需联网下载独立 Python + 依赖，约 5 分钟）
    pause
    exit /b 1
)

echo [FontCop] 启动本地服务…
python-runtime\python.exe -m src.server
