@echo off
setlocal EnableExtensions

title Tkinter Embed Installer

set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%" >nul 2>&1

set "PY_DIR="
if not "%~1"=="" (
    set "PY_DIR=%~1"
) else (
    for /d %%D in ("%SCRIPT_DIR%python-embed-*") do (
        if exist "%%~fD\python.exe" (
            set "PY_DIR=%%~fD"
            goto found_python
        )
    )
)

:found_python
if not defined PY_DIR (
    echo ERROR: Could not find an embedded Python folder.
    echo Expected something like: python-embed-3.12.10
    echo.
    echo Usage:
    echo   install_tkinter_embed.bat
    echo   install_tkinter_embed.bat "C:\path\to\python-embed-3.12.10"
    pause
    popd >nul 2>&1
    exit /b 1
)

if not exist "%PY_DIR%\python.exe" (
    echo ERROR: python.exe was not found in:
    echo   %PY_DIR%
    pause
    popd >nul 2>&1
    exit /b 1
)

set "PY_EXE=%PY_DIR%\python.exe"
set "PTH_FILE="
for %%F in ("%PY_DIR%\python*._pth") do (
    set "PTH_FILE=%%~fF"
    goto found_pth
)

:found_pth
if not defined PTH_FILE (
    echo ERROR: Could not find the embedded Python ._pth file.
    pause
    popd >nul 2>&1
    exit /b 1
)

echo.
echo ==========================================
echo   Tkinter Embed Installer
echo ==========================================
echo Runtime: %PY_DIR%
echo.

findstr /B /C:"import site" "%PTH_FILE%" >nul
if errorlevel 1 (
    echo [1/4] Enabling import site in %PTH_FILE% ...
    powershell -NoProfile -Command ^
        "$p = '%PTH_FILE%';" ^
        "$c = Get-Content -Raw $p;" ^
        "$c = $c -replace '(?m)^#\s*import site\s*$', 'import site';" ^
        "if($c -notmatch '(?m)^import site\s*$'){ $c = $c.TrimEnd() + [Environment]::NewLine + 'import site' + [Environment]::NewLine };" ^
        "Set-Content -Path $p -Value $c -Encoding ASCII"
    if errorlevel 1 (
        echo ERROR: Failed to update the embedded Python ._pth file.
        pause
        popd >nul 2>&1
        exit /b 1
    )
) else (
    echo [1/4] import site is already enabled.
)

echo [2/4] Checking pip ...
"%PY_EXE%" -m pip --version >nul 2>&1
if errorlevel 1 (
    echo pip was not found. Bootstrapping pip...
    powershell -NoProfile -Command ^
        "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile '%PY_DIR%\get-pip.py'"
    if errorlevel 1 (
        echo ERROR: Failed to download get-pip.py
        pause
        popd >nul 2>&1
        exit /b 1
    )
    "%PY_EXE%" "%PY_DIR%\get-pip.py" --no-warn-script-location
    if errorlevel 1 (
        echo ERROR: Failed to install pip into the embedded runtime.
        pause
        popd >nul 2>&1
        exit /b 1
    )
    del "%PY_DIR%\get-pip.py" 2>nul
)

set "TK_EMBED_VERSION="
for %%D in ("%PY_DIR%") do set "PY_DIR_NAME=%%~nxD"
for /f "tokens=3 delims=-" %%V in ("%PY_DIR_NAME%") do set "PY_FULL_VERSION=%%V"
for /f "tokens=1,2 delims=." %%A in ("%PY_FULL_VERSION%") do set "TK_EMBED_VERSION=%%A.%%B.0"
if not defined TK_EMBED_VERSION (
    echo ERROR: Could not determine the embedded Python version.
    echo Expected an embedded folder name like python-embed-3.12.10
    pause
    popd >nul 2>&1
    exit /b 1
)

echo [3/4] Installing setuptools into the embedded runtime ...
"%PY_EXE%" -m pip install --upgrade setuptools --target "%PY_DIR%" --no-warn-script-location
if errorlevel 1 (
    echo ERROR: Failed to install setuptools.
    pause
    popd >nul 2>&1
    exit /b 1
)

echo [4/4] Installing tkinter-embed==%TK_EMBED_VERSION% into the embedded runtime ...
"%PY_EXE%" -m pip install --upgrade "tkinter-embed==%TK_EMBED_VERSION%" --target "%PY_DIR%" --no-warn-script-location
if errorlevel 1 (
    echo ERROR: Failed to install tkinter-embed==%TK_EMBED_VERSION%
    echo Try checking whether that exact package version exists for this Python version.
    pause
    popd >nul 2>&1
    exit /b 1
)

echo.
echo [OK] tkinter-embed was installed into:
echo   %PY_DIR%
echo.
echo You can now test it with:
echo   "%PY_EXE%" "%SCRIPT_DIR%app.py"
echo.

pause
popd >nul 2>&1
exit /b 0
