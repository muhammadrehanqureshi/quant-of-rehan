@echo off
REM The Sentinel - owner launcher
REM One double-click. Registers the local spark (idempotent - safe to run
REM any time), opens the live STATUS page, and gets out of your way.
REM Your PC does NOT run the bot; GitHub does. This only guarantees that
REM a stalled cadence gets rescued even when GitHub's scheduler blacks out.

cd /d "%~dp0"

REM Register the spark task (no error if it already exists)
schtasks /create /f /tn "Sentinel Spark" /tr "\"%CD%\.venv\Scripts\python.exe\" \"%CD%\src\spark.py\"" /sc minute /mo 5 /f >nul 2>&1
schtasks /run /tn "Sentinel Spark" >nul 2>&1

echo.
echo   The Sentinel is running on GitHub's machines.
echo   Opening your live status page...
echo.
echo   (Signals also arrive by email via the repo's signals issue.)
echo.
timeout /t 4 >nul
start "" "https://github.com/muhammadrehanqureshi/the-sentinel/blob/master/STATUS.md"
exit /b 0
