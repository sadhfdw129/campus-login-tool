@echo off
cd /d "%~dp0"
if exist "D:\py3.10.9\python.exe" (
    start "" "D:\py3.10.9\python.exe" gui.py
) else (
    start "" python gui.py
)
