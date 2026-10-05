@echo off
REM ========================================================================
REM THE SENTINEL - Private Web Console launcher
REM ========================================================================
REM
REM Double-click this. It starts the console server (minimized) and opens
REM your browser on it, token already attached.
REM
REM You do NOT need start_live.bat anymore: press "Start the bot" on the
REM web page instead (pick 120s for the light CPU profile). The .bat and
REM the console's Start button both spawn the same bot - use ONE of them,
REM never both at once, or two bots would fight over the same book.
REM
REM ========================================================================

cd /d "%~dp0"
set PYTHONWARNINGS=ignore

set SENTINEL_TOKEN=
if exist data\web_token.txt set /p SENTINEL_TOKEN=<data\web_token.txt

start "" /min .venv\Scripts\python.exe src\web_console.py
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8785/?token=%SENTINEL_TOKEN%"

echo.
echo The Sentinel console is running (minimized window).
echo Your browser should have opened it already.
echo To shut the console down, close that minimized python window.
echo.
