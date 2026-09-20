@echo off
rem FontCop launcher: dependency check + start server (opens browser automatically)
cd /d %~dp0

if not exist .venv\Scripts\python.exe (
    echo [ERROR] .venv not found. Run in project root:
    echo     python -m venv .venv
    echo     .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

.venv\Scripts\python.exe -c "import numpy, PIL" >nul 2>&1
if errorlevel 1 (
    echo [INFO] First run: installing dependencies...
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] pip install failed. Check network and retry.
        pause
        exit /b 1
    )
)

.venv\Scripts\python.exe -m src.server
if errorlevel 1 pause
