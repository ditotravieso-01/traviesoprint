#!/bin/bash
# ============================================================
# Script de desarrollo: Resetea la DB local para demos
# ============================================================

set -e
cd "$(dirname "$0")/.."

echo "Borrando base de datos actual..."
rm -f instance/traviesoprint.db

echo "Creando tablas desde modelos..."
python -c "from app import create_app, db; app = create_app(); app.app_context().push(); db.create_all()"

echo "Sellando migraciones de Alembic..."
flask db stamp head

echo "¡Base de datos lista para usar!"