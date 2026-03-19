@echo off
setlocal

:: Populate the build\ directory with defaults for a new user.
:: Re-run when dev\VERSION changes to pick up new defaults.

set SCRIPT_DIR=%~dp0
set PROJECT_DIR=%SCRIPT_DIR%..
set BUILD_DIR=%PROJECT_DIR%\build
set DEV_DIR=%SCRIPT_DIR%

echo Setting up build\ directory...

:: Create directory structure
for %%D in (data story writing chats forge generated-images portraits) do (
    if not exist "%BUILD_DIR%\%%D" mkdir "%BUILD_DIR%\%%D"
)

:: Copy content defaults (only if target dir is missing or empty)
call :copy_defaults "%DEV_DIR%defaults\lore"           "%BUILD_DIR%\lore"
call :copy_defaults "%DEV_DIR%defaults\persona"        "%BUILD_DIR%\persona"
call :copy_defaults "%DEV_DIR%defaults\writing-styles" "%BUILD_DIR%\writing-styles"
call :copy_defaults "%DEV_DIR%defaults\council"        "%BUILD_DIR%\council"
call :copy_defaults "%DEV_DIR%defaults\layouts"        "%BUILD_DIR%\layouts"
call :copy_defaults "%DEV_DIR%defaults\layout-images"  "%BUILD_DIR%\layout-images"
call :copy_defaults "%DEV_DIR%defaults\forge-prompts"  "%BUILD_DIR%\forge-prompts"

:: Config file
if not exist "%BUILD_DIR%\config.yaml" (
    echo   Creating config.yaml
    copy "%DEV_DIR%config.yaml.default" "%BUILD_DIR%\config.yaml" >nul
)

:: .env file
if not exist "%BUILD_DIR%\.env" (
    echo   Creating .env from example
    copy "%DEV_DIR%.env.example" "%BUILD_DIR%\.env" >nul
    echo.
    echo   *** Edit build\.env to add your API key, or configure providers in the UI. ***
    echo.
)

:: Write version stamp
copy "%DEV_DIR%VERSION" "%BUILD_DIR%\.setup-version" >nul

echo Setup complete. Your personal data lives in build\
echo Back up this directory — it contains your configs, lore, and stories.
goto :eof

:copy_defaults
set SRC=%~1
set DST=%~2
if not exist "%DST%" (
    echo   Populating %DST%
    xcopy /e /i /q "%SRC%" "%DST%" >nul
) else (
    dir /b "%DST%" 2>nul | findstr "." >nul && (
        echo   Skipping %DST% (already has content)
    ) || (
        echo   Populating %DST%
        xcopy /e /i /q "%SRC%" "%DST%" >nul
    )
)
goto :eof
