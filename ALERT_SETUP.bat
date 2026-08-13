@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

call "%~dp0_findpy.bat"
if not defined PY goto nopy

!PY! notify.py --setup
start "" notepad "%~dp0notify.json"
echo.
echo   Fill in notify.json if you want Telegram or Slack, then save it.
echo   Press any key here to send a test alert.
pause
!PY! notify.py --test

goto end

:nopy
echo.
echo   [ERROR] Python not found.
echo.
echo   Opening the setup guide in Notepad...
echo.
start "" notepad "%~dp0PYTHON_SETUP.txt"

:end
echo.
pause
