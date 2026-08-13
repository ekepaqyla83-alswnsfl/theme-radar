@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

call "%~dp0_findpy.bat"
if not defined PY goto nopy

!PY! collector.py --source rss --hours 24 --xlsx

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
