@echo off
title Rhasan Indie's Agentic LLM - No-DB Mode
python run.py full --port 8070
if %errorlevel% neq 0 (
    echo [ERROR] Exited with code %errorlevel% (port busy? run.py auto-switches)
    pause
)
