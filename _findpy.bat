@echo off
REM ===========================================================
REM  Find a usable Python and put it in PY. Called by other bats.
REM
REM  ASCII ONLY - do not put Korean text in .bat files.
REM  cmd.exe re-reads the batch file by byte offset after each
REM  command; multi-byte characters desync that offset and cmd
REM  starts reading from the middle of a line ("echo" -> "cho").
REM  All Korean UI lives in the .py files instead.
REM
REM  Note: a machine with no real Python still has a python.exe
REM  stub under WindowsApps that only opens the Microsoft Store.
REM  "where python" cannot tell them apart, so we actually run it.
REM ===========================================================

set PY=
py -3 -c "import sys" >nul 2>&1 && set PY=py -3
if not defined PY python -c "import sys" >nul 2>&1 && set PY=python
if not defined PY python3 -c "import sys" >nul 2>&1 && set PY=python3
exit /b 0
