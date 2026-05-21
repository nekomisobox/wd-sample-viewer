@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_CMD="

python --version >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=python"
)

if "%PYTHON_CMD%"=="" (
  py -3 --version >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
  )
)

if "%PYTHON_CMD%"=="" (
  echo Python was not found.
  echo Please install Python 3.10 or newer from https://www.python.org/downloads/
  echo If Python is already installed, disable the Microsoft Store Python alias:
  echo Settings ^> Apps ^> Advanced app settings ^> App execution aliases
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating Python virtual environment...
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 (
    echo Retrying with py -3...
    py -3 -m venv .venv
  )
  if errorlevel 1 (
    echo Failed to create virtual environment. Please install Python 3.10 or newer.
    pause
    exit /b 1
  )
)

call ".venv\Scripts\activate.bat"

if not exist ".venv\.installed" (
  echo Installing dependencies...
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Failed to install dependencies.
    pause
    exit /b 1
  )
  echo ok> ".venv\.installed"
)

if not exist ".venv\.florence-installed-v3" (
  echo Installing Florence dependencies...
  python -m pip install -r requirements-florence.txt
  if errorlevel 1 (
    echo Failed to install Florence dependencies.
    pause
    exit /b 1
  )
  echo ok> ".venv\.florence-installed-v3"
)

for /f "usebackq delims=" %%u in (`python -c "import os,sys; os.chdir(r'%CD%'); sys.path.insert(0,'bridge'); import server; print(server.sync_bridge_config())"`) do set "BRIDGE_URL=%%u"
start "" "%BRIDGE_URL%/"
python bridge\server.py
pause
