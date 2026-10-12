#!/bin/bash
# ============================================================
#  TraviesoPrint · Instalador de la integración con Odoo
#
#  Qué hace:
#   1. Verifica que el código de la integración esté desplegado.
#   2. Pregunta los datos de conexión a Odoo y los guarda en .env.
#   3. Reinicia el servicio.
#   4. Ejecuta un sync manual de prueba.
#   5. Si funciona, instala el cron cada 1 minuto.
#   6. Verifica que el cron haya quedado bien escrito.
#   7. Espera 90s y confirma que corrió.
#
#  Uso:
#    sudo ./scripts/install_odoo_sync.sh
#
#  Es idempotente: se puede volver a ejecutar sin duplicar nada.
# ============================================================

set -euo pipefail

# ----- Detectar rutas y usuario -----
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${APP_DIR}/.env"
VENV="${APP_DIR}/venv"
SERVICE="traviesoprint"
LOG_DIR="/var/log/traviesoprint"
LOG_FILE="${LOG_DIR}/sync.log"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${BLUE}[INSTALL]${NC} $*"; }
ok()   { echo -e "${GREEN}[  OK  ]${NC} $*"; }
warn() { echo -e "${YELLOW}[ WARN ]${NC} $*"; }
err()  { echo -e "${RED}[ FAIL ]${NC} $*"; }

if [ "$EUID" -ne 0 ]; then
    err "Ejecutar como root: sudo $0"
    exit 1
fi

if [ ! -d "${APP_DIR}/.git" ]; then
    err "No se encontró el repo en ${APP_DIR}"
    exit 1
fi

if [ ! -f "${ENV_FILE}" ]; then
    err "Falta ${ENV_FILE}"
    err "Copiá la plantilla y completá los valores base antes de continuar:"
    err "  cp ${APP_DIR}/.env.example ${ENV_FILE}"
    err "  nano ${ENV_FILE}"
    exit 1
fi

# ----- Detectar usuario del servicio -----
DETECTED_USER="$(stat -c '%U' "${APP_DIR}" 2>/dev/null || echo travieso)"
if [ "${DETECTED_USER}" = "root" ] || [ -z "${DETECTED_USER}" ]; then
    DETECTED_USER="travieso"
fi

echo ""
read -rp "Usuario que ejecuta el servicio [${DETECTED_USER}]: " input_user
APP_USER="${input_user:-${DETECTED_USER}}"

if ! id "${APP_USER}" >/dev/null 2>&1; then
    err "El usuario '${APP_USER}' no existe en el sistema."
    exit 1
fi

# Línea del cron: ahora apunta al script, no al comando inline.
CRON_LINE="* * * * * ${APP_DIR}/scripts/sync_odoo.sh >> ${LOG_FILE} 2>&1"

# ----- 1. Verificar código -----
log "Verificando código de la integración..."
for f in app/services/odoo_service.py app/cli.py scripts/sync_odoo.sh; do
    if [ ! -f "${APP_DIR}/${f}" ]; then
        err "No existe ${f}"
        err "Ejecutá ./deploy.sh primero para traer el código."
        exit 1
    fi
done
if [ ! -x "${APP_DIR}/scripts/sync_odoo.sh" ]; then
    warn "scripts/sync_odoo.sh no es ejecutable. Corrigiendo..."
    chmod +x "${APP_DIR}/scripts/sync_odoo.sh"
fi
ok "Código presente."

# ----- 2. Configurar variables ODOO_* en .env -----
log "Revisando variables ODOO_* en .env..."

if grep -qE '^ODOO_ENABLED=' "${ENV_FILE}"; then
    ok "El bloque ODOO_* ya está definido. No se toca."
    if grep -qE '^ODOO_PASSWORD=(cambiar|tu_api_key_aqui|)$' "${ENV_FILE}"; then
        warn "ODOO_PASSWORD parece un placeholder."
        warn "Edita ${ENV_FILE} y pone la API key real antes de continuar."
        read -rp "¿Continuar igual? [s/N]: " cont
        if [[ ! "${cont}" =~ ^[sS]$ ]]; then
            exit 0
        fi
    fi
else
    warn "No existe el bloque ODOO_* en .env. Se preguntarán los datos."
    echo ""
    echo "Introducí los datos de conexión. Enter acepta el valor por defecto."
    echo ""

    read -rp "ODOO_URL [https://odoo.example.local]: " odoo_url
    odoo_url="${odoo_url:-https://odoo.example.local}"

    read -rp "ODOO_DB [odoo]: " odoo_db
    odoo_db="${odoo_db:-odoo}"

    read -rp "ODOO_USER [sync_user@example.local]: " odoo_user
    odoo_user="${odoo_user:-sync_user@example.local}"

    read -rsp "ODOO_PASSWORD (API key de Odoo): " odoo_pass
    echo ""
    if [ -z "${odoo_pass}" ]; then
        err "La API key no puede estar vacía. Abortando."
        exit 1
    fi

    {
        echo ""
        echo "# ===== Odoo API (añadido por install_odoo_sync.sh) ====="
        echo "ODOO_ENABLED=True"
        echo "ODOO_URL=${odoo_url}"
        echo "ODOO_DB=${odoo_db}"
        echo "ODOO_USER=${odoo_user}"
        echo "ODOO_PASSWORD=${odoo_pass}"
    } >> "${ENV_FILE}"

    chmod 600 "${ENV_FILE}"
    chown "${APP_USER}:${APP_USER}" "${ENV_FILE}"
    ok "Bloque ODOO_* añadido a ${ENV_FILE}."
fi

# ----- 3. Preparar logs -----
log "Preparando directorio de logs..."
mkdir -p "${LOG_DIR}"
chown "${APP_USER}:${APP_USER}" "${LOG_DIR}"
chmod 755 "${LOG_DIR}"
ok "Log dir: ${LOG_DIR}"

# ----- 4. Reiniciar servicio -----
log "Reiniciando ${SERVICE}..."
systemctl restart "${SERVICE}.service"
sleep 3
if systemctl is-active --quiet "${SERVICE}.service"; then
    ok "Servicio activo."
else
    err "El servicio no arrancó. Revisá: journalctl -u ${SERVICE} -n 50"
    exit 1
fi

# ----- 5. Sync manual de prueba -----
log "Ejecutando primer sync manual..."
if sudo -u "${APP_USER}" bash -c "
    cd '${APP_DIR}'
    set -a; source .env; set +a
    '${VENV}/bin/flask' sync-odoo
"; then
    ok "Sync inicial correcto."
else
    err "El sync falló. Revisá las credenciales en ${ENV_FILE}."
    err "No se instalará el cron hasta que el sync funcione."
    exit 1
fi

# ----- 6. Instalar cron (idempotente + verificado) -----
log "Configurando cron..."

TMP_CRON=$(mktemp)
trap 'rm -f "${TMP_CRON}"' EXIT

# Leer crontab actual (si no existe, crear vacío)
if ! crontab -u "${APP_USER}" -l > "${TMP_CRON}" 2>/dev/null; then
    : > "${TMP_CRON}"
fi

if grep -qF "${APP_DIR}/scripts/sync_odoo.sh" "${TMP_CRON}"; then
    ok "El cron ya estaba configurado. No se toca."
else
    # Eliminar cualquier línea previa con 'flask sync-odoo' (formato viejo)
    grep -vF 'flask sync-odoo' "${TMP_CRON}" > "${TMP_CRON}.clean" || true
    mv "${TMP_CRON}.clean" "${TMP_CRON}"

    # Añadir la línea correcta
    echo "${CRON_LINE}" >> "${TMP_CRON}"

    # Instalar el archivo entero
    if crontab -u "${APP_USER}" "${TMP_CRON}"; then
        ok "Cron instalado para el usuario ${APP_USER}."
    else
        err "No se pudo instalar el cron. Verificá permisos de ${APP_USER}."
        exit 1
    fi
fi

# Verificación: leer el crontab de nuevo y confirmar que la línea está
if crontab -u "${APP_USER}" -l 2>/dev/null | grep -qF "${APP_DIR}/scripts/sync_odoo.sh"; then
    ok "Verificación: la línea del cron está presente."
else
    err "Verificación fallida: la línea no aparece en el crontab de ${APP_USER}."
    err "Crontab actual:"
    crontab -u "${APP_USER}" -l 2>/dev/null || echo "(vacío)"
    exit 1
fi

# ----- 7. Verificación del primer ciclo -----
log "Esperando 90s para verificar el primer ciclo del cron..."
sleep 90

if [ -f "${LOG_FILE}" ]; then
    last_line=$(tail -n 1 "${LOG_FILE}" || true)
    if echo "${last_line}" | grep -q 'Sync OK'; then
        ok "El cron está funcionando. Última línea:"
        echo "  ${last_line}"
    else
        warn "El log existe pero no tiene 'Sync OK'. Última línea:"
        echo "  ${last_line}"
        warn "Esperá unos minutos más o revisá manualmente:"
        warn "  tail -f ${LOG_FILE}"
    fi
else
    warn "Aún no existe ${LOG_FILE}. El cron puede tardar hasta 1 minuto."
fi

echo ""
ok "Instalación completada."
echo ""
echo "Para verificar manualmente:"
echo "  sudo crontab -u ${APP_USER} -l"
echo "  sudo tail -f ${LOG_FILE}"