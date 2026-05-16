@echo off
cd /d "%~dp0"
echo.
echo === Deploy to Streamlit Cloud ===
echo.
set /p MSG="Commit message (press Enter for default): "
if "%MSG%"=="" set MSG=Update from local
echo.
echo [1/3] git add ...
git add .
echo.
echo [2/3] git commit ...
git commit -m "%MSG%"
echo.
echo [3/3] git push ...
git push
echo.
echo === Done ===
echo Streamlit Cloud will auto-redeploy in 1-2 minutes.
echo App URL: https://investment-tool-mark.streamlit.app/
echo.
pause
