@echo off
setlocal

chcp 65001>nul
set "SCRIPT_DIR=%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHON_EXE="
set "PYTHON_ARGS="

where python >nul 2>nul
if %ERRORLEVEL%==0 (
    set "PYTHON_EXE=python"
) else (
    where py >nul 2>nul
    if %ERRORLEVEL%==0 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARGS=-3"
    ) else (
        echo [ERROR] Python launcher not found. 1>&2
        endlocal & exit /b 1
    )
)

if not exist "%SCRIPT_DIR%infra\logging\logs.py" (
    echo [ERROR] infra\logging\logs.py not found. 1>&2
    endlocal & exit /b 1
)

call "%PYTHON_EXE%" %PYTHON_ARGS% "%SCRIPT_DIR%infra\logging\logs.py" %*
set "EXIT_CODE=%ERRORLEVEL%"

endlocal & exit /b %EXIT_CODE%
