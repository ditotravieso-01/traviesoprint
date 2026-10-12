#!/bin/bash
# ============================================================
#  TraviesoPrint · Sincronización manual con Odoo
#  Ejecuta flask sync-odoo con el .env del proyecto.
#
#  Uso:
#    ./scripts/sync_odoo.sh
#    sudo -u travieso ./scripts/sync_odoo.sh
#
#  Pensado para pruebas manuales. En producción lo ejecuta el
#  cron cada minuto llamando al mismo comando.
# ============================================================
set -euo pipefail

# Detectar la raíz del proyecto a partir de la ubicación del script
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${APP_DIR}/.env"
VENV="${APP_DIR}/venv"

if [ ! -f "${ENV_FILE}" ]; then
    echo "ERROR: no existe ${ENV_FILE}" >&2
    echo "Copiá la plantilla y completá los valores reales:" >&2
    echo "  cp ${APP_DIR}/.env.example ${ENV_FILE}" >&2
    exit 1
fi

if [ ! -x "${VENV}/bin/flask" ]; then
    echo "ERROR: no se encontró el ejecutable flask en ${VENV}/bin" >&2
    exit 1
fi

if ! grep -qE '^ODOO_ENABLED=True' "${ENV_FILE}"; then
    echo "WARN: ODOO_ENABLED no es True en ${ENV_FILE}" >&2
    echo "      El comando sync-odoo fallará si las variables ODOO_* no están activas." >&2
fi

cd "${APP_DIR}"
set -a
source "${ENV_FILE}"
set +a

exec "${VENV}/bin/flask" sync-odoo
