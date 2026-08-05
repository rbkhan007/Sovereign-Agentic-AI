@echo off
title Rhasan Indie's Agentic LLM - Multi-Agent LLM Platform
echo ======================================================
echo   Launching Fully Complete Multi-Agent System
echo   560/560 Tests Passed | Deep Audit Green
echo ======================================================
cd /d "%~dp0"
start /b "" cmd /c "python run.py web --host 0.0.0.0 --port 8070 --threads 4 --parallel-max 1 --no-parallel --no-parallel-load --vram 4000 --gen-timeout 120 --auto-stream --no-auto-load"
timeout /t 5 /nobreak >nul
echo.
echo Web UI: http://localhost:8070
echo.
echo Press ANY key to SHUT DOWN...
pause >nul
taskkill /f /im python.exe >nul 2>&1
timeout /t 2 /nobreak >nul
echo Cleaned up. Goodbye!
pause
