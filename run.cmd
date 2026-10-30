@echo off
REM Launch the COTW population map. Opens the UI once the server is up.
setlocal
cd /d "%~dp0"

set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY where python >nul 2>nul && set PY=python
if not defined PY (
  echo Python 3 was not found on PATH.
  echo Install it from https://www.python.org/downloads/ and run this again.
  pause
  exit /b 1
)

start "" http://127.0.0.1:8765/
%PY% -m cotw.server --port 8765 %*
