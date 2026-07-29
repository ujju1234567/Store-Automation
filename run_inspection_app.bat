@echo off
title Incoming Goods Inspection
color 0A

echo ========================================================
echo   AI-POWERED INCOMING GOODS INSPECTION
echo ========================================================
echo.
echo Please ensure you have set the GEMINI_API_KEY environment variable.
echo Example: set GEMINI_API_KEY=your_api_key_here
echo.

set PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
set FLAGS_enable_pir_api=0
set FLAGS_use_mkldnn=0

"C:\Users\shailesh\Desktop\Ujjval\08-Softwares\01-Python3.11\python.exe" -m streamlit run ui.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Failed to start Streamlit app.
    pause
) else (
    pause
)
