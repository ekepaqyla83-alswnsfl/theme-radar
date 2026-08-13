@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

call "%~dp0_findpy.bat"
if not defined PY goto nopy

!PY! diagnose.py

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
