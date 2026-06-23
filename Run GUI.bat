@echo off
REM Shortcut to launch the GUI using the project's venv.
cd /d "%~dp0"
".venv\Scripts\pythonw.exe" src\gui.py
