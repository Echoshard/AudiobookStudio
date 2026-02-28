@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set PYTHON_DIR=python_embedded
set PYTHON_EXE=%PYTHON_DIR%\python.exe
set PYTHON_ZIP=python-3.12.6-embed-amd64.zip
set PYTHON_URL=https://www.python.org/ftp/python/3.12.6/%PYTHON_ZIP%
set GET_PIP_URL=https://bootstrap.pypa.io/get-pip.py
set INSTALLED_FLAG=%PYTHON_DIR%\.installed

set FFMPEG_DIR=ffmpeg
set FFMPEG_EXE=%FFMPEG_DIR%\ffmpeg.exe
set FFMPEG_ZIP=ffmpeg-release-essentials.zip
set FFMPEG_URL=https://www.gyan.dev/ffmpeg/builds/%FFMPEG_ZIP%

REM Keep HuggingFace model cache inside the project directory
set HF_HOME=%~dp0models

REM ============================================================
REM  Step 1: Download and set up embedded Python (first run only)
REM ============================================================
if exist "%PYTHON_EXE%" goto :check_ffmpeg

echo ============================================================
echo  Downloading Embedded Python 3.12.6...
echo ============================================================
curl -L -# -o "%PYTHON_ZIP%" "%PYTHON_URL%"
if errorlevel 1 (
    echo ERROR: Failed to download Python. Check your internet connection.
    pause
    exit /b 1
)

echo Extracting Python...
mkdir "%PYTHON_DIR%" 2>nul
powershell -Command "Expand-Archive -Path '%PYTHON_ZIP%' -DestinationPath '%PYTHON_DIR%' -Force"
del "%PYTHON_ZIP%"

REM Enable pip/site-packages by uncommenting "import site" in the ._pth file
echo Configuring Python for pip support...
powershell -Command "(Get-Content '%PYTHON_DIR%\python312._pth') -replace '#import site','import site' | Set-Content '%PYTHON_DIR%\python312._pth'"

REM Bootstrap pip
echo Downloading pip...
curl -L -# -o "%PYTHON_DIR%\get-pip.py" "%GET_PIP_URL%"
"%PYTHON_EXE%" "%PYTHON_DIR%\get-pip.py" --no-warn-script-location
if errorlevel 1 (
    echo ERROR: Failed to install pip.
    pause
    exit /b 1
)
del "%PYTHON_DIR%\get-pip.py"

:check_ffmpeg
REM ============================================================
REM  Step 2: Download FFmpeg (first run only)
REM ============================================================
if exist "%FFMPEG_EXE%" goto :check_installed

echo ============================================================
echo  Downloading FFmpeg...
echo ============================================================
mkdir "%FFMPEG_DIR%" 2>nul
curl -L -# -o "%FFMPEG_ZIP%" "%FFMPEG_URL%"
if errorlevel 1 (
    echo WARNING: Failed to download FFmpeg. MP3 merging and speed adjustment will not work.
    goto :check_installed
)

echo Extracting FFmpeg...
powershell -Command "$zip = '%FFMPEG_ZIP%'; $dest = '%FFMPEG_DIR%'; Add-Type -Assembly System.IO.Compression.FileSystem; $archive = [System.IO.Compression.ZipFile]::OpenRead($zip); foreach ($entry in $archive.Entries) { if ($entry.Name -match '^(ffmpeg|ffprobe)\.exe$') { $targetPath = Join-Path $dest $entry.Name; [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $targetPath, $true) } }; $archive.Dispose()"
del "%FFMPEG_ZIP%"

if exist "%FFMPEG_EXE%" (
    echo FFmpeg installed successfully.
) else (
    echo WARNING: FFmpeg extraction failed. MP3 merging will not work.
)

:check_installed
REM ============================================================
REM  Step 3: Install dependencies (first run only)
REM ============================================================
if exist "%INSTALLED_FLAG%" goto :launch

echo ============================================================
echo  Installing PyTorch (CPU-only, ~200MB)...
echo ============================================================
"%PYTHON_EXE%" -m pip install torch --index-url https://download.pytorch.org/whl/cpu --no-warn-script-location
if errorlevel 1 (
    echo ERROR: Failed to install PyTorch.
    pause
    exit /b 1
)

echo ============================================================
echo  Installing other dependencies...
echo ============================================================
"%PYTHON_EXE%" -m pip install -r requirements.txt --no-warn-script-location
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

REM Mark as installed so we skip this next time
echo installed > "%INSTALLED_FLAG%"

echo ============================================================
echo  Pre-downloading PocketTTS model (first run only)...
echo ============================================================
"%PYTHON_EXE%" -c "from pocket_tts import TTSModel; print('[System] Downloading model...'); TTSModel.load_model(); print('[System] Model downloaded successfully.')"
if errorlevel 1 (
    echo WARNING: Model pre-download failed. It will download on first use.
)

:launch
REM ============================================================
REM  Step 4: Launch PocketTTS
REM ============================================================

echo.
echo ============================================================
echo  Starting PocketTTS Generator...
echo ============================================================
"%PYTHON_EXE%" PocketTTSUI.py

pause
