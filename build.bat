@echo off
rem ===========================================================================
rem  CAPTURAS - compilar a un UNICO archivo .exe
rem  Resultado:  dist\Capturas.exe   (doble clic, sin consola)
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
call ".venv\Scripts\python.exe" -m pip install pyinstaller

echo [3/3] Compilando con PyInstaller...
call ".venv\Scripts\python.exe" -m PyInstaller ^
  --noconfirm --clean --onefile --windowed ^
  --name "Capturas" ^
  --icon "icon.ico" ^
  --add-data "icon.ico;." ^
  --add-data "icon.png;." ^
  capturas.py

echo.
echo ============================================================
echo  LISTO.  Tu ejecutable esta en:  dist\Capturas.exe
echo ============================================================
pause
endlocal
