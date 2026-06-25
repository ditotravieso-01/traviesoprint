#!/bin/bash
set -e

REPO_DIR="/opt/cairostudiokit"
VENV_ETIQUETAS="/opt/venvs/calculadora/bin"
VENV_LONA="/opt/venvs/lona/bin"

echo "📥 Descargando cambios..."
cd "$REPO_DIR"
git pull origin main
git fetch --tags

echo "📦 Verificando dependencias..."
$VENV_ETIQUETAS/pip install -r requirements.txt -q
$VENV_LONA/pip install -r requirements.txt -q

echo "🔄 Reiniciando servicios..."
sudo systemctl restart calculadora lona-calculadora

echo "✅ Despliegue completado."