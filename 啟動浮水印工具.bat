@echo off
chcp 65001 >nul
title PDF Watermark Tool
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0watermark_gui.pyw" %*
    goto end
)
where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw "%~dp0watermark_gui.pyw" %*
    goto end
)
echo [!] pythonw not found. Please install Python from https://www.python.org/downloads/
echo     (remember to check "Add Python to PATH" during installation)
pause
:end
