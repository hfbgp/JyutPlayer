@echo off
setlocal enabledelayedexpansion

echo =======================================================
echo          JyutPlayer - Build Script (English)
echo =======================================================

:: 1. Check Python version
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python not found in PATH. Please install Python 3.11.9.
    pause
    exit /b 1
)

:: 2. Check or Install uv
where uv >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [*] Installing uv package manager...
    python -m pip install --upgrade uv
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Failed to install uv.
        pause
        exit /b 1
    )
)

:: 3. Create virtual environment using uv
echo [*] Creating uv virtual environment (.venv)...
if not exist ".venv" (
    uv venv .venv --python 3.11
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Failed to create virtual environment with uv.
        pause
        exit /b 1
    )
)

:: Activate Virtual Environment
call .venv\Scripts\activate.bat

:: 4. Install dependencies
echo [*] Installing required packages...
uv pip install -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to install requirements.
    pause
    exit /b 1
)

:: 5. Check libmpv-2.dll
if not exist "libmpv-2.dll" (
    echo [WARNING] libmpv-2.dll not found in current folder.
    echo Please make sure libmpv-2.dll is placed in this directory!
) else (
    echo [*] Preparing mpv-2.dll alias...
    copy /Y "libmpv-2.dll" "mpv-2.dll" >nul 2>&1
)

:: 6. Build standalone executable via PyInstaller
echo [*] Building JyutPlayer executable...

set ADD_DATA=
if exist "libmpv-2.dll" (
    set ADD_DATA=!ADD_DATA! --add-binary "libmpv-2.dll;."
)
if exist "mpv-2.dll" (
    set ADD_DATA=!ADD_DATA! --add-binary "mpv-2.dll;."
)
if exist "ffmpeg.exe" (
    set ADD_DATA=!ADD_DATA! --add-binary "ffmpeg.exe;."
)

pyinstaller --noconfirm --onedir --windowed --name "JyutPlayer" ^
    !ADD_DATA! ^
    --collect-all PyQt6 ^
    --collect-all pysubs2 ^
    main.py

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] PyInstaller build failed.
    pause
    exit /b 1
)

:: Copy local DLLs to dist folder directly as fallback
if exist "libmpv-2.dll" (
    copy /Y "libmpv-2.dll" "dist\JyutPlayer\" >nul 2>&1
    copy /Y "libmpv-2.dll" "dist\JyutPlayer\mpv-2.dll" >nul 2>&1
)
if exist "ffmpeg.exe" (
    copy /Y "ffmpeg.exe" "dist\JyutPlayer\" >nul 2>&1
)

echo.
echo =======================================================
echo  BUILD SUCCESSFUL!
echo  Executable location: dist\JyutPlayer\JyutPlayer.exe
echo =======================================================
pause