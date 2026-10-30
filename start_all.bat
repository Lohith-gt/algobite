@echo off
title Food Discovery AI - Launch All Services
echo ========================================================
echo   Food Discovery Assistant - Starting All Services
echo ========================================================
echo.

cd /d "%~dp0"

echo [1/2] Starting Ingestion API Server (Port 8000)...
start "Food Discovery API Server (:8000)" cmd /k ".\venv\Scripts\python.exe api_server.py"

timeout /t 2 /nobreak >nul

echo [2/2] Starting Streamlit Web App (Port 8501)...
start "Food Discovery Web UI (:8501)" cmd /k ".\venv\Scripts\streamlit.exe run app.py"

echo.
echo ========================================================
echo   Services are running!
echo   - Web App UI:       http://localhost:8501
echo   - Ingestion API:    http://localhost:8000
echo   - API Documentation: http://localhost:8000/docs
echo ========================================================
echo.
