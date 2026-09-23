@echo off
rem FontCop 启动壳（Windows）：双击起本地服务并自动打开浏览器。
rem 要停服务用页面右上角「⏻ 关闭服务」按钮（调 /api/shutdown）。
rem 依赖同目录的 python-runtime\python.exe（由 build_python.sh 生成）。
cd /d "%~dp0"

if not exist python-runtime\python.exe (
    echo [FontCop] 未找到 python-runtime\python.exe
    echo 请先运行：bash build_python.sh  （首次需联网下载独立 Python + 依赖，约 5 分钟）
    pause
    exit /b 1
)

rem 已在运行则只开浏览器，不重复起服务（服务自身也会开浏览器）
python-runtime\python.exe -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8642/healthz',timeout=1)" >nul 2>&1
if %errorlevel%==0 (
    start "" "http://127.0.0.1:8642"
    exit /b 0
)

rem 无控制台黑窗：pythonw 起服务，出错时回退用 start.bat 看输出
start "" "python-runtime\pythonw.exe" -m src.server
