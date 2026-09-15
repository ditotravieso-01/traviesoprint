#!/bin/bash
# ============================================================
#  migrate_db.sh — Migración segura de BD entre servidores
#  Uso:
#    En el ORIGEN:  sudo ./migrate_db.sh backup
#    En el DESTINO: sudo ./migrate_db.sh restore <archivo.db>
# ============================================================

set -euo pipefail

APP_DIR="/opt/traviesoprint"
APP_USER="travieso"
SERVICE_NAME="traviesoprint"
DB_FILE="${APP_DIR}/instance/traviesoprint.db"

GREEN='\033[0;32m'; BLUE='\033[0;34m'; RED='\033[0;31m'; NC='\033[0m'

log() { echo -e "${BLUE}[DB]${NC} $*"; }
ok()  { echo -e "${GREEN}[OK]${NC} $*"; }
err() { echo -e "${RED}[ERR]${NC} $*"; }

if [ "$EUID" -ne 0 ]; then
    err "Ejecutar como root: sudo ./migrate_db.sh ..."
    exit 1
fi

ACTION="${1:-help}"

case "${ACTION}" in

# ============================================================
backup)
    log "Deteniendo ${SERVICE_NAME}..."
    systemctl stop "${SERVICE_NAME}"
    trap 'systemctl start "${SERVICE_NAME}"' EXIT

    log "Consolidando WAL..."
    sudo -u "${APP_USER}" sqlite3 "${DB_FILE}" "PRAGMA wal_checkpoint(TRUNCATE);"

    log "Verificando integridad..."
    RESULT=$(sudo -u "${APP_USER}" sqlite3 "${DB_FILE}" "PRAGMA integrity_check;" | head -1)
    if [ "${RESULT}" != "ok" ]; then
        err "Integridad fallida: ${RESULT}"
        exit 1
    fi

    BACKUP="/tmp/traviesoprint_backup_$(date +%Y%m%d_%H%M%S).db"
    log "Copiando a ${BACKUP}..."
    sudo -u "${APP_USER}" cp "${DB_FILE}" "${BACKUP}"

    log "Verificando backup..."
    SIZE=$(stat -c%s "${BACKUP}")
    ok "Backup listo: ${BACKUP} (${SIZE} bytes)"

    log "Reiniciando ${SERVICE_NAME}..."
    ;;

# ============================================================
restore)
    SRC="${2:-}"
    if [ -z "${SRC}" ] || [ ! -f "${SRC}" ]; then
        err "Uso: sudo ./migrate_db.sh restore <archivo.db>"
        exit 1
    fi

    log "Deteniendo ${SERVICE_NAME}..."
    systemctl stop "${SERVICE_NAME}"

    # Backup de la BD actual
    if [ -f "${DB_FILE}" ]; then
        BACKUP="${APP_DIR}/instance/backups/pre_restore_$(date +%Y%m%d_%H%M%S).db"
        mkdir -p "$(dirname "${BACKUP}")"
        cp "${DB_FILE}" "${BACKUP}"
        log "Backup previo: ${BACKUP}"
    fi

    log "Eliminando archivos residuales..."
    rm -f "${DB_FILE}" "${DB_FILE}-wal" "${DB_FILE}-shm" "${DB_FILE}-journal"

    log "Copiando nueva BD..."
    cp "${SRC}" "${DB_FILE}"
    chown "${APP_USER}:www-data" "${DB_FILE}"
    chmod 640 "${DB_FILE}"

    log "Verificando integridad..."
    RESULT=$(sudo -u "${APP_USER}" sqlite3 "${DB_FILE}" "PRAGMA integrity_check;" | head -1)
    if [ "${RESULT}" != "ok" ]; then
        err "Integridad fallida en la BD importada: ${RESULT}"
        exit 1
    fi

    TABLES=$(sudo -u "${APP_USER}" sqlite3 "${DB_FILE}" \
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table';")
    log "Tablas detectadas: ${TABLES}"

    log "Aplicando migraciones pendientes..."
    sudo -u "${APP_USER}" bash -c "
        cd '${APP_DIR}'
        set -a; source .env; set +a
        '${APP_DIR}/venv/bin/flask' db upgrade
    "

    log "Arrancando ${SERVICE_NAME}..."
    systemctl start "${SERVICE_NAME}"
    sleep 2

    if systemctl is-active --quiet "${SERVICE_NAME}"; then
        ok "Servicio activo. Migración completada."
    else
        err "El servicio no arrancó. Log:"
        journalctl -u "${SERVICE_NAME}" -n 30 --no-pager
        exit 1
    fi
    ;;

# ============================================================
*)
    cat <<USAGE
Uso: sudo ./migrate_db.sh <acción> [args]

Acciones:
  backup                Detiene el servicio, consolida WAL, verifica y
                        copia la BD a /tmp/traviesoprint_backup_YYYYMMDD_HHMMSS.db

  restore <archivo.db>  Detiene el servicio, elimina archivos residuales,
                        copia la BD del archivo, ajusta permisos, verifica,
                        aplica migraciones y arranca el servicio.

Ejemplo de flujo:
  1. En el servidor origen:    sudo ./migrate_db.sh backup
  2. Copiar el archivo a /tmp del nuevo servidor (scp, USB, etc.)
  3. En el servidor destino:   sudo ./migrate_db.sh restore /tmp/traviesoprint_backup_*.db
USAGE
    ;;
esac