@echo off
REM ========================================================================
REM THE SENTINEL - Live Runner (PSX KMIALL)
REM ========================================================================
REM
REM Starts the live collector + decision engine. Runs continuously during
REM market hours and sleeps overnight / over weekends.
REM
REM Usage:
REM   start_live.bat               Run in foreground
REM   start_live.bat --dry-run     Collect but don't write or decide
REM   start_live.bat --test        Test decide on existing data
REM
REM To run in background (minimal window):
REM   start /min start_live.bat
REM
REM ========================================================================

cd /d "%~dp0"

REM Silence pandas/numpy library warnings (fragmentation notices etc).
REM The live runner logs everything that matters via the logger.
set PYTHONWARNINGS=ignore

.venv\Scripts\python.exe src\live.py %*

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Live runner exited with code %ERRORLEVEL%
    pause
)
