@echo off
setlocal
set "BASE=%~dp0"
if exist "%BASE%KnightAgent.exe" (
  start "" "%BASE%KnightAgent.exe" --config "%BASE%config.yaml"
  exit /b 0
)
if not exist "%BASE%.venv\Scripts\pythonw.exe" (
  echo Ambiente virtual ausente. Consulte README.md para instalar.
  pause
  exit /b 1
)
start "" "%BASE%.venv\Scripts\pythonw.exe" -m knightagent.gui.main --config "%BASE%config.yaml"
