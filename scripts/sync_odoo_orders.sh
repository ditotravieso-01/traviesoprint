#!/bin/bash
# ============================================================
#  TraviesoPrint - Sync de ÓRDENES desde Odoo
#  Wrapper para el cron. Llama a flask sync-odoo-orders.
#
#  Uso manual:  sudo -u travieso /opt/traviesoprint/scripts/sync_odoo_orders.sh
#  Cron:        * * * * * (ver install_odoo_orders_sync.sh)
# ============================================================

set -euo pipefail

APP_DIR="/opt/traviesoprint"
VENV="${APP_DIR}/venv"
LOG_DIR="/var/log/traviesoprint"
LOCK_FILE="/tmp/traviesoprint_sync_orders.lock"

# Asegurar directorio de logs
mkdir -p "${LOG_DIR}"

# Evitar solapamiento: si hay otro sync corriendo, salir.
# Usa flock para exclusión mutua sin bloquear.
exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Sync de órdenes ya en curso. Skip."
    exit 0
fi

cd "${APP_DIR}"

# Cargar .env (necesario para ODOO_* y config de Flask)
set -a
# shellcheck disable=SC1091
source .env
set +a

# Ejecutar comando (el log se captura con >> en la entrada del cron)
exec "${VENV}/bin/flask" sync-odoo-orders
