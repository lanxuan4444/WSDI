@echo off
chcp 65001 >nul
echo ==========================================
echo   Build Driver Index (one-time operation)
echo ==========================================
echo.
echo This will scan all 104 driver packages and build a search index.
echo Takes about 1-2 minutes. Only needs to run once (or when packages change).
echo.

"C:\Users\Administrator\AppData\Local\Programs\Python\Python315\python.exe" "D:\WSDI\server\build_index.py"

echo.
echo Done! Restart server.py to use the new index.
pause
