#!/usr/bin/env bash
# ===========================================================================
#  CAPTURAS - compilar a un unico ejecutable (macOS / Linux)
#  Resultado:  dist/Capturas   (en macOS: dist/Capturas.app)
# ===========================================================================
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "[1/3] Creando entorno virtual..."
    python3 -m venv .venv
fi

echo "[2/3] Instalando dependencias..."
.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install -r requirements.txt >/dev/null
.venv/bin/python -m pip install pyinstaller >/dev/null

echo "[3/3] Compilando con PyInstaller..."
.venv/bin/python -m PyInstaller \
  --noconfirm --clean --onefile --windowed \
  --name "Capturas" \
  --add-data "icon.ico:." \
  --add-data "icon.png:." \
  capturas.py

echo
echo "============================================================"
echo " LISTO.  Ejecutable en:  dist/Capturas"
echo "============================================================"
