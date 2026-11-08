@echo off
rem Starts the screening application and opens it in a browser.
rem
rem Double-click this file. It also works from a copy somewhere else, such as
rem the Desktop: dragging a file to the Desktop MOVES it on the same drive
rem rather than copying it, and the first version of this script assumed the
rem project was always in the folder it sat in, so a dragged copy stopped
rem working. It now finds the project rather than assuming it.

setlocal EnableDelayedExpansion
set "PORT=8000"
set "URL=http://localhost:%PORT%/"

echo.
echo   TB Screening
echo   ============
echo.

rem Beside this file first, which is the normal case, then the usual place.
set "PROJECT="
if exist "%~dp0manage.py" set "PROJECT=%~dp0"
if not defined PROJECT if exist "%USERPROFILE%\Desktop\tb-screening-system\manage.py" set "PROJECT=%USERPROFILE%\Desktop\tb-screening-system\"
if not defined PROJECT if exist "%USERPROFILE%\tb-screening-system\manage.py" set "PROJECT=%USERPROFILE%\tb-screening-system\"

if not defined PROJECT (
    echo   Cannot find the project folder.
    echo.
    echo   Looked beside this file, and in:
    echo       %USERPROFILE%\Desktop\tb-screening-system
    echo       %USERPROFILE%\tb-screening-system
    echo.
    echo   If the project has moved, put a copy of this file in it and run
    echo   that one instead.
    echo.
    pause
    exit /b 1
)

cd /d "%PROJECT%"
set "PYTHON=%PROJECT%.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo   Found the project at:
    echo       %PROJECT%
    echo   but it has no virtual environment yet. Create it once with:
    echo.
    echo       py -3.11 -m venv .venv
    echo       .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

rem Clicking the icon twice is the commonest thing that goes wrong: the second
rem server cannot have the port and dies with a stack trace that looks far
rem worse than it is. If something is already serving, just open the browser.
netstat -ano | findstr /r /c:"LISTENING" | findstr /c:":%PORT% " >nul 2>&1
if not errorlevel 1 (
    echo   Already running on %URL%
    echo   Opening the browser. The window that started it is the one to
    echo   close when you are finished.
    start "" "%URL%"
    timeout /t 3 >nul
    exit /b 0
)

rem Django connects to PostgreSQL lazily, so without this check the server
rem starts happily and the first page shows a database error instead.
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
rem in the foreground of this window and would never reach a line after it.
start "" /min powershell -NoProfile -Command "Start-Sleep -Seconds 4; Start-Process '%URL%'"

echo.
echo   Starting on %URL%
echo   The browser opens in a moment. Keep this window open.
echo   Press Ctrl+C here to stop the application.
echo.

"%PYTHON%" manage.py runserver %PORT%

echo.
echo   The server has stopped.
pause
