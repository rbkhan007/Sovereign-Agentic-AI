@echo off
title Rhasan Indie's Agentic LLM - Multi-Agent System
echo ====================================================
echo   RHASAN INDIE'S AGENTIC LLM - LOCAL MULTI-AGENT SYSTEM
echo ====================================================
echo.

python run.py full --port 8070 --db

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] System exited with code %errorlevel%
    echo Possible issues:
    echo   - Missing GGUF models in models\ folder
    echo   - Port 8070 in use - run.py auto-switches to a free port
    echo   - PostgreSQL not running (use start_simple.bat for no-DB mode)
    echo.
    pause
)
