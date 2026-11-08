@echo off
rem Starts the screening application and opens it in a browser.
rem
rem Double-click this file, or make a shortcut to it on the Desktop. It works
rem from anywhere, because it moves to its own folder first rather than
rem assuming the one the shell happens to be in.
rem
rem The window it opens IS the server. Leaving it open is what keeps the
rem application running; closing it stops the application.

setlocal
cd /d "%~dp0"

set "PYTHON=.venv\Scripts\python.exe"
set "PORT=8000"

echo.
echo   TB Screening
echo   ============
echo.

if not exist "%PYTHON%" (
    echo   The virtual environment is missing from this folder.
    echo.
    echo   Create it once with:
    echo       py -3.11 -m venv .venv
    echo       .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

rem Django connects to PostgreSQL lazily, so without this check the server
rem starts happily and the first page shows a database error instead. Better
rem to say so here, where the reason is obvious.
echo   Checking the database...
"%PYTHON%" manage.py showmigrations screening >nul 2>&1
if errorlevel 1 (
    echo.
    echo   Cannot reach PostgreSQL. Start the postgresql service, then run
    echo   this again. Nothing else is wrong.
    echo.
    echo   Services: press Win+R, type services.msc, find postgresql, Start.
    echo.
    pause
    exit /b 1
)
echo   Database is up.

rem Opened from a second process after a pause, because the server below runs
rem in the foreground of this window and would otherwise never reach the line
rem that opens the browser.
start "" /min powershell -NoProfile -Command "Start-Sleep -Seconds 4; Start-Process 'http://localhost:%PORT%/'"

echo.
echo   Starting on http://localhost:%PORT%/
echo   The browser opens in a moment. Keep this window open.
echo   Press Ctrl+C here to stop the application.
echo.

"%PYTHON%" manage.py runserver %PORT%

echo.
echo   The server has stopped.
pause
