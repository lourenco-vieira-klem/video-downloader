@echo off
REM Atalho para abrir a GUI usando a venv do projeto.
cd /d "%~dp0"
".venv\Scripts\pythonw.exe" src\gui.py
