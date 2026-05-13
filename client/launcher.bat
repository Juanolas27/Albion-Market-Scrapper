@echo off
REM Albion Market Launcher - arranca como Administrador y abre el navegador.
cd /d "%~dp0\.."

REM Pide elevacion si no la tenemos.
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Solicitando permisos de Administrador...
    powershell -Command "Start-Process -Verb RunAs '%~f0'"
    exit /b
)

echo Arrancando launcher...
py client\launcher.py
pause
