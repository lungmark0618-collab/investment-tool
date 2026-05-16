@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ===============================================
echo  長期投資決策工具 — Streamlit 啟動中...
echo ===============================================
echo.
python -m streamlit run app.py --server.port 8501
pause
