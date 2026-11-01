@echo off
rem ===========================================================================
rem  CAPTURAS - ejecutar desde el codigo fuente (sin compilar)
rem  Doble clic. La primera vez crea el entorno virtual e instala Pillow.
rem ===========================================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\" (
    echo [1/3] Creando entorno virtual...
    python -m venv .venv
)

echo [2/3] Instalando dependencias...
call ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
call ".venv\Scripts\python.exe" -m pip install -r requirements.txt

echo [3/3] Arrancando Capturas...
start "" ".venv\Scripts\pythonw.exe" capturas.py

endlocal
