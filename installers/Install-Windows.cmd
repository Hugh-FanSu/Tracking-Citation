@echo off
cd /d "%~dp0"
py -3.12 install.py
if errorlevel 1 echo Installation failed. Please read the error above.
pause
