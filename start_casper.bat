@echo off
setlocal
:: Casper Flow launcher - double-click to start. A tray icon will appear.
:: Prefers the project venv (created by install.ps1) over whatever "python"
:: happens to be on PATH, because the dependencies live in the venv.

cd /d "%~dp0"

set "PYW="

:: 1. venv pythonw (preferred - no console window)
if exist "venv\Scripts\pythonw.exe" set "PYW=venv\Scripts\pythonw.exe"

:: 2. system pythonw
if not defined PYW (
    for /f "delims=" %%I in ('where pythonw.exe 2^>nul') do (
        if not defined PYW set "PYW=%%I"
    )
)

if not defined PYW goto :nopython

start "" "%PYW%" "main.py"
exit /b 0

:nopython
echo.
echo Could not find a Python interpreter with Casper Flow's dependencies.
echo.
echo Run the installer first:
echo     powershell -ExecutionPolicy Bypass -File install.ps1
echo.
echo (Requires Python 3.10+ from https://python.org - tick "Add Python to PATH".)
echo.
pause
exit /b 1
