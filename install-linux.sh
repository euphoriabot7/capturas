#!/usr/bin/env bash
# Crea una entrada de aplicacion (menu de apps + opcion de acceso directo).
# Uso:  ./install-linux.sh
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "[1/2] Creando entorno virtual e instalando dependencias..."
    python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip >/dev/null
    .venv/bin/python -m pip install -r requirements.txt >/dev/null
fi

echo "[2/2] Creando entrada de escritorio..."
APPS="$HOME/.local/share/applications"
mkdir -p "$APPS"
ENTRY="$APPS/capturas.desktop"

cat > "$ENTRY" <<EOF
[Desktop Entry]
Type=Application
Name=Capturas
Comment=Capturas de pantalla completas o recortadas
Exec=$PWD/.venv/bin/python $PWD/capturas.py
Icon=$PWD/icon.png
Terminal=false
Categories=Utility;Graphics;
Keywords=captura;screenshot;pantalla;
EOF

chmod +x capturas.py
update-desktop-database "$APPS" 2>/dev/null || true

echo ""
echo "LISTO: $ENTRY"
echo "Busca 'Capturas' en el menu de aplicaciones."
echo "Consejo: en Ajustes > Teclado puedes asignarle un atajo de teclado."
