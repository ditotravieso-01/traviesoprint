#!/bin/bash
# ============================================================
#  TraviesoPrint - Instalador del sync de ÓRDENES desde Odoo
#  Idempotente: se puede correr varias veces sin efectos.
#
#  Uso: sudo /opt/traviesoprint/scripts/install_odoo_orders_sync.sh
# ============================================================

set -euo pipefail

APP_NAME="traviesoprint"
APP_USER="travieso"
APP_DIR="/opt/${APP_NAME}"
VENV="${APP_DIR}/venv"
LOG_DIR="/var/log/traviesoprint"
LOG_FILE="${LOG_DIR}/sync_orders.log"
CRON_LINE="* * * * * ${APP_DIR}/scripts/sync_odoo_orders.sh >> ${LOG_FILE} 2>&1"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${BLUE}[INSTALL]${NC} $*"; }
ok()   { echo -e "${GREEN}[  OK   ]${NC} $*"; }
warn() { echo -e "${YELLOW}[ WARN  ]${NC} $*"; }
fail() { echo -e "${RED}[ FAIL  ]${NC} $*"; exit 1; }

# --- 0. Debe correr como root ---
if [ "$EUID" -ne 0 ]; then
    fail "Ejecutar como root: sudo $0"
fi

log "Instalando sync de ÓRDENES desde Odoo"

# --- 1. Verificar que existe el wrapper ---
WRAPPER="${APP_DIR}/scripts/sync_odoo_orders.sh"
if [ ! -f "${WRAPPER}" ]; then
    fail "No existe ${WRAPPER}. Crea el archivo primero."
fi
if [ ! -x "${WRAPPER}" ]; then
    chmod +x "${WRAPPER}"
    ok "Wrapper marcado como ejecutable"
fi

# --- 2. Verificar que existe el .env y tiene las claves Odoo ---
if [ ! -f "${APP_DIR}/.env" ]; then
    fail "No existe ${APP_DIR}/.env"
fi
# shellcheck disable=SC1091
ODOO_ENABLED_VAL=$(grep -E '^ODOO_ENABLED=' "${APP_DIR}/.env" | cut -d= -f2 | tr -d '"' | tr -d "'" || echo "False")
if [ "${ODOO_ENABLED_VAL,,}" != "true" ] && [ "${ODOO_ENABLED_VAL}" != "1" ]; then
    warn "ODOO_ENABLED no está en True en .env (valor: ${ODOO_ENABLED_VAL})"
    warn "El sync no hará nada. Edita .env y reinicia el servicio."
fi
for k in ODOO_URL ODOO_DB ODOO_USER ODOO_PASSWORD; do
    if ! grep -qE "^${k}=" "${APP_DIR}/.env"; then
        fail "Falta ${k} en .env"
    fi
done
ok ".env con credenciales Odoo"

# --- 3. Verificar que la migración está aplicada ---
log "Verificando migración de base de datos..."
CURRENT_REV=$(sudo -u "${APP_USER}" bash -c "cd '${APP_DIR}' && set -a && source .env && set +a && '${VENV}/bin/flask' db current 2>/dev/null | tail -1 | awk '{print \$1}'")
if [ "${CURRENT_REV}" != "a7f3e91c4d28" ]; then
    warn "Migración actual: ${CURRENT_REV}. Esperado: a7f3e91c4d28"
    warn "Ejecuta 'flask db upgrade' antes de continuar."
    warn "Deteniendo instalación."
    exit 1
fi
ok "Migración aplicada: ${CURRENT_REV}"

# --- 4. Crear directorio de logs ---
mkdir -p "${LOG_DIR}"
chown "${APP_USER}:${APP_USER}" "${LOG_DIR}" || true
if [ ! -f "${LOG_FILE}" ]; then
    touch "${LOG_FILE}"
    chown "${APP_USER}:${APP_USER}" "${LOG_FILE}" || true
    ok "Log creado: ${LOG_FILE}"
else
    ok "Log ya existe: ${LOG_FILE}"
fi

# --- 5. Instalar/verificar cron ---
log "Verificando entrada de cron..."
CRON_EXISTING=$(sudo -u "${APP_USER}" crontab -l 2>/dev/null || true)

if echo "${CRON_EXISTING}" | grep -qF "sync_odoo_orders.sh"; then
    ok "Entrada de cron ya existe para sync_odoo_orders.sh"
else
    echo "${CRON_EXISTING}" | grep -v '^$' > /tmp/cron_new.txt || true
    echo "${CRON_LINE}" >> /tmp/cron_new.txt
    sudo -u "${APP_USER}" crontab /tmp/cron_new.txt
    rm -f /tmp/cron_new.txt
    ok "Entrada de cron añadida"
fi

# Verificar que el cron de clientes sigue intacto
if echo "${CRON_EXISTING}" | grep -qF "sync_odoo.sh"; then
    ok "Cron de clientes intacto (sync_odoo.sh detectado)"
else
    warn "No se detecta el cron de clientes. ¿Está instalado?"
fi

# --- 6. Ejecutar el sync UNA vez para verificar ---
log "Ejecutando sync una vez para verificar..."
sudo -u "${APP_USER}" "${WRAPPER}" || warn "El primer sync devolvió error. Revisa ${LOG_FILE}"
ok "Instalación completada."

# --- 7. Resumen ---
echo ""
echo -e "${GREEN}════════════════════════════════════════════════${NC}"
echo -e "${GREEN} Sync de ÓRDENES instalado correctamente${NC}"
echo -e "${GREEN}════════════════════════════════════════════════${NC}"
echo ""
echo "  Script:      ${WRAPPER}"
echo "  Log:         ${LOG_FILE}"
echo "  Cron:        ${CRON_LINE}"
echo ""
echo "  Ver estado:  sudo -u ${APP_USER} crontab -l"
echo "  Ver log:     sudo /opt/${APP_NAME}/scripts/show_orders_sync_log.sh"
echo "  Log en vivo: tail -f ${LOG_FILE}"
echo ""
echo "  IMPORTANTE: El toggle 'Activar sincronización automática'"
echo "  en https://print.cairostudio.cu/ordenes/ debe estar en ON."
echo ""
