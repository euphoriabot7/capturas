#!/usr/bin/env bash
# ===========================================================================
#  CAPTURAS - ejecutar desde el codigo fuente (macOS / Linux)
#  La primera vez crea el entorno virtual e instala Pillow.
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

echo "[3/3] Arrancando Capturas..."
exec .venv/bin/python capturas.py "$@"
