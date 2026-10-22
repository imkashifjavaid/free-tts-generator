@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Creating a local Python environment...
    python -m venv .venv
    if errorlevel 1 goto :failed
)
echo Checking speech dependencies...
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check --timeout 10 --retries 1 --upgrade -r requirements.txt
if errorlevel 1 (
    echo Could not check for updates. Checking the installed version...
    ".venv\Scripts\python.exe" -c "from tts_core import check_dependency; check_dependency()"
    if errorlevel 1 goto :failed
)
".venv\Scripts\python.exe" tts_gui.py
if errorlevel 1 goto :failed
exit /b 0
:failed
echo.
echo Setup or launch failed. Check the message above and your Python installation.
pause
exit /b 1
