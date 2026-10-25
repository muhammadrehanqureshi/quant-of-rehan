@echo off
rem Charts of Rehan: start the charting service on loopback and open it.
rem Closing this window stops the service. Nothing is left running.
rem
rem A second click must not start a second copy: two servers on one port
rem would both poll the broker feed, and the page would be answered by
rem whichever process happened to win. If the service already answers,
rem this only opens a tab on it.
setlocal
cd /d "%~dp0"
set PORT=8788

powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 'http://127.0.0.1:%PORT%/api/health'; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if not errorlevel 1 (
  echo Charts of Rehan is already running at http://127.0.0.1:%PORT%/ .
  start "" "http://127.0.0.1:%PORT%/"
  exit /b 0
)

echo Starting Charts of Rehan at http://127.0.0.1:%PORT%/ ...
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:%PORT%/'"
python -m charts --port %PORT%
echo.
echo The service has stopped. Press any key to close this window.
pause >nul
