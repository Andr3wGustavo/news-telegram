@echo off
echo Preparando ambiente virtual (pode demorar na primeira vez)...
if not exist "venv\Scripts\activate.bat" (
    python -m venv venv
)
call venv\Scripts\activate.bat
pip install -r requirements.txt --quiet
echo Iniciando o Oraculo em segundo plano...
start "" "venv\Scripts\pythonw.exe" main.py
exit
