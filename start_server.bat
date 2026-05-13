@echo off
REM Arranca uvicorn + cloudflared (Quick Tunnel) en una sola consola.
cd /d "%~dp0"
py start_server.py %*
pause
