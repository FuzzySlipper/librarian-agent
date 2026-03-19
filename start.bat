@echo off
setlocal

:: Narrative Orchestration System — Launch Script (Windows)
:: Usage: start.bat [--update] [--build-frontend] [--setup]

cd /d "%~dp0"

set PORT=8005
set HOST=0.0.0.0
set VENV_DIR=.venv
set STATIC_DIR=static
set BUILD_DIR=build
set DEV_DIR=dev

:: Parse arguments
set DO_UPDATE=0
set BUILD_FRONTEND=0
set FORCE_SETUP=0
:parse_args
if "%~1"=="" goto :done_args
if "%~1"=="--update" set DO_UPDATE=1
if "%~1"=="--build-frontend" set BUILD_FRONTEND=1
if "%~1"=="--setup" set FORCE_SETUP=1
if "%~1"=="--help" goto :show_help
if "%~1"=="-h" goto :show_help
shift
goto :parse_args

:show_help
echo Usage: start.bat [OPTIONS]
echo.
echo Options:
echo   --update           Pull latest code and update dependencies
echo   --build-frontend   Rebuild frontend (requires Node.js)
echo   --setup            Force re-run setup (won't overwrite your data)
echo   -h, --help         Show this help
exit /b 0

:done_args

:: Git update
if %DO_UPDATE%==1 (
    echo Pulling latest changes...
    git pull --ff-only || (
        echo Git pull failed. Resolve conflicts and retry.
        exit /b 1
    )
)

:: Build directory setup
set NEEDS_SETUP=0

if not exist "%BUILD_DIR%" set NEEDS_SETUP=1
if not exist "%BUILD_DIR%\.setup-version" set NEEDS_SETUP=1
if %FORCE_SETUP%==1 set NEEDS_SETUP=1

:: Check version stamp
if %NEEDS_SETUP%==0 (
    fc /b "%DEV_DIR%\VERSION" "%BUILD_DIR%\.setup-version" >nul 2>&1
    if errorlevel 1 (
        echo New version detected — running setup to apply updates...
        set NEEDS_SETUP=1
    )
)

if %NEEDS_SETUP%==1 (
    call "%DEV_DIR%\setup.bat"
)

:: Python virtual environment
if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo Creating Python virtual environment...
    where uv >nul 2>&1 && (
        uv venv %VENV_DIR%
    ) || (
        python -m venv %VENV_DIR%
    )
)

call %VENV_DIR%\Scripts\activate.bat

echo Installing Python dependencies...
where uv >nul 2>&1 && (
    uv pip install -r %DEV_DIR%\requirements.txt --quiet
) || (
    pip install -r %DEV_DIR%\requirements.txt --quiet
)

:: Frontend build (optional)
if %BUILD_FRONTEND%==1 (
    where npm >nul 2>&1 && (
        echo Building frontend...
        cd %DEV_DIR%\frontend && npm install && npm run build && cd ..\..
        if exist "%STATIC_DIR%" rmdir /s /q "%STATIC_DIR%"
        xcopy /e /i /q %DEV_DIR%\frontend\dist "%STATIC_DIR%"
        echo Frontend built.
    ) || (
        echo Warning: npm not found. Cannot build frontend.
    )
)

if not exist "%STATIC_DIR%" (
    echo.
    echo Warning: No %STATIC_DIR%\ directory found.
    echo Run with --build-frontend to build, or ensure pre-built files are present.
    echo.
)

:: Launch server
set CONFIG_PATH=%BUILD_DIR%\config.yaml
set DOTENV_PATH=%BUILD_DIR%\.env

echo.
echo Starting server on http://localhost:%PORT%
echo Press Ctrl+C to stop.
echo.

python -m uvicorn src.web.server:app --host %HOST% --port %PORT%
