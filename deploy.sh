#!/bin/bash
# ============================================================
#  TraviesoPrint - Script de actualización / deploy
#  Uso: sudo ./deploy.sh
# ============================================================

set -euo pipefail

APP_NAME="traviesoprint"
APP_USER="travieso"
APP_DIR="/opt/${APP_NAME}"
SERVICE_NAME="traviesoprint"
VENV="${APP_DIR}/venv"

# Colores
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; RED='\033[0;31m'; NC='\033[0m'
log() { echo -e "${BLUE}[DEPLOY]${NC} $*"; }
ok()  { echo -e "${GREEN}[  OK  ]${NC} $*"; }
warn(){ echo -e "${YELLOW}[ WARN ]${NC} $*"; }

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Ejecutar como root: sudo ./deploy.sh${NC}"
    exit 1
fi

# Detectar APP_DIR si se ejecuta desde dentro del repo
if [ -f "./app/__init__.py" ] && [ -d "./.git" ]; then
    APP_DIR="$(pwd)"
    VENV="${APP_DIR}/venv"
fi

if [ ! -d "${APP_DIR}/.git" ]; then
    echo -e "${RED}No se encontró un repo git en ${APP_DIR}${NC}"
    exit 1
fi

log "Actualizando desde ${APP_DIR}"
cd "${APP_DIR}"

# Backup rápido de la BD
DB="${APP_DIR}/instance/traviesoprint.db"
if [ -f "${DB}" ]; then
    BACKUP="${APP_DIR}/instance/backups/traviesoprint_$(date +%Y%m%d_%H%M%S).db"
    mkdir -p "$(dirname "${BACKUP}")"
    cp "${DB}" "${BACKUP}"
    ok "Backup BD: ${BACKUP}"
fi

# Git pull
log "git pull..."
sudo -u "${APP_USER}" git fetch --all -q
sudo -u "${APP_USER}" git reset --hard origin/main -q
ok "Código actualizado."

# Dependencias
log "Instalando dependencias Python..."
sudo -u "${APP_USER}" "${VENV}/bin/pip" install -r "${APP_DIR}/requirements.txt" -q
ok "Dependencias actualizadas."

# Migraciones
log "Aplicando migraciones..."
sudo -u "${APP_USER}" bash -c "
    cd '${APP_DIR}'
    set -a; source .env; set +a
    '${VENV}/bin/flask' db upgrade
"
ok "Migraciones aplicadas."

# Reiniciar servicio
log "Reiniciando ${SERVICE_NAME}..."
systemctl restart "${SERVICE_NAME}.service"
sleep 2

if systemctl is-active --quiet "${SERVICE_NAME}.service"; then
    ok "Servicio reiniciado correctamente."
else
    echo -e "${RED}El servicio no arrancó. Revisa:${NC}"
    echo "  journalctl -u ${SERVICE_NAME} -n 50"
    exit 1
fi

systemctl reload nginx || true

ok "Deploy completado."