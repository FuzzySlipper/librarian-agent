@echo off
setlocal

:: Narrative Orchestration System — Launch Script (Windows)
:: Usage: start.bat [--update] [--build-frontend]

cd /d "%~dp0"

set PORT=8005
set HOST=0.0.0.0
set VENV_DIR=.venv
set STATIC_DIR=static

:: Parse arguments
set DO_UPDATE=0
set BUILD_FRONTEND=0
:parse_args
if "%~1"=="" goto :done_args
if "%~1"=="--update" set DO_UPDATE=1
if "%~1"=="--build-frontend" set BUILD_FRONTEND=1
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
    uv pip install -r requirements.txt --quiet
) || (
    pip install -r requirements.txt --quiet
)

:: .env setup
if not exist .env (
    if exist .env.example (
        echo.
        echo No .env file found. Creating from .env.example...
        echo Edit .env to add your API key, or configure providers in the UI.
        copy .env.example .env >nul
        echo.
    )
)

:: Frontend build (optional)
if %BUILD_FRONTEND%==1 (
    where npm >nul 2>&1 && (
        echo Building frontend...
        cd frontend && npm install && npm run build && cd ..
        if exist "%STATIC_DIR%" rmdir /s /q "%STATIC_DIR%"
        xcopy /e /i /q frontend\dist "%STATIC_DIR%"
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

:: Create runtime directories
if not exist data mkdir data
if not exist story mkdir story
if not exist writing mkdir writing
if not exist chats mkdir chats
if not exist code-requests mkdir code-requests
if not exist forge mkdir forge
if not exist generated-images mkdir generated-images

:: Launch server
echo.
echo Starting server on http://localhost:%PORT%
echo Press Ctrl+C to stop.
echo.

python -m uvicorn src.web.server:app --host %HOST% --port %PORT%
