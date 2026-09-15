#!/bin/bash
# ============================================================
#  TraviesoPrint - Instalador automático
#  Soporta: Ubuntu 22.04 / 24.04 / 26.04 LTS
#  Uso:
#    - Dentro del repo:      sudo ./install.sh
#    - Desde cualquier lado: sudo bash install.sh
# ============================================================

set -euo pipefail

# ---------- Colores ----------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[ OK ]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[FAIL]${NC}  $*"; }

# ---------- Configuración por defecto ----------
APP_NAME="traviesoprint"
APP_USER="travieso"
DEFAULT_APP_DIR="/opt/${APP_NAME}"
REPO_URL="https://github.com/ditotravieso-01/traviesoprint.git"
SERVICE_NAME="traviesoprint"

SSL_CERT="/etc/ssl/certs/${APP_NAME}.crt"
SSL_KEY="/etc/ssl/private/${APP_NAME}.key"

# ============================================================
# 0. Banner
# ============================================================
echo -e "${GREEN}${BOLD}"
echo "=================================================="
echo "   TraviesoPrint - Instalación automática v1.5"
echo "   Gestión para talleres de impresión"
echo "=================================================="
echo -e "${NC}"

# ============================================================
# 1. Verificar root
# ============================================================
if [ "$EUID" -ne 0 ]; then
    log_error "Este script debe ejecutarse como root. Usa: sudo ./install.sh"
    exit 1
fi

# ============================================================
# 2. Detectar sistema operativo
# ============================================================
if [ ! -f /etc/os-release ]; then
    log_error "No se detecta /etc/os-release. Abortando."
    exit 1
fi
# shellcheck disable=SC1091
. /etc/os-release
OS_ID="${ID:-unknown}"
OS_VERSION="${VERSION_ID:-unknown}"
OS_CODENAME="${VERSION_CODENAME:-unknown}"

log_info "Sistema detectado: ${OS_ID} ${OS_VERSION} (${OS_CODENAME})"

case "${OS_ID}" in
    ubuntu|debian) ;;
    *) log_warn "SO no probado oficialmente (${OS_ID}). Continuando bajo tu responsabilidad." ;;
esac

# ============================================================
# 3. Detectar si estamos dentro de un repo clonado
# ============================================================
IS_IN_REPO=false
if [ -f "./app/__init__.py" ] && [ -f "./requirements.txt" ] && [ -d "./migrations" ]; then
    IS_IN_REPO=true
    APP_DIR="$(pwd)"
    log_ok "Repositorio detectado en: ${APP_DIR}"
else
    APP_DIR="${DEFAULT_APP_DIR}"
    log_info "No se detecta repo en el directorio actual. Se instalará en: ${APP_DIR}"
fi

# ============================================================
# 4. Preguntas interactivas
# ============================================================
SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")
DEFAULT_DOMAIN="${SERVER_IP}"

echo ""
read -r -p "🌐 Dominio o IP pública [${DEFAULT_DOMAIN}]: " INPUT_DOMAIN
DOMAIN="${INPUT_DOMAIN:-$DEFAULT_DOMAIN}"

if [[ "${DOMAIN}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    DEFAULT_HOSTNAME="traviesoprint"
else
    DEFAULT_HOSTNAME=$(echo "${DOMAIN}" | cut -d. -f1)
fi

read -r -p "👤 Usuario Linux para la app [${APP_USER}]: " INPUT_USER
APP_USER="${INPUT_USER:-$APP_USER}"

read -r -p "📂 Directorio de instalación [${APP_DIR}]: " INPUT_DIR
APP_DIR="${INPUT_DIR:-$APP_DIR}"

# ------------------------------------------------------------
# Hostname: una sola pregunta, valor por defecto = actual
# ------------------------------------------------------------
echo ""
log_info "Hostname del servidor"
echo "   El hostname aparece en el prompt del shell y en logs."
echo "   NO afecta al funcionamiento de la app."
echo ""
CURRENT_HOSTNAME=$(hostname)
echo "   Hostname actual: ${CURRENT_HOSTNAME}"
echo "   Sugerencia:      ${DEFAULT_HOSTNAME}"
read -r -p "   Nuevo hostname (Enter = sin cambios): " INPUT_HOSTNAME

if [ -z "${INPUT_HOSTNAME}" ]; then
    CHANGE_HOSTNAME=false
    SHORT_HOSTNAME="${CURRENT_HOSTNAME}"
    log_info "Hostname sin cambios (${CURRENT_HOSTNAME})."
else
    SHORT_HOSTNAME="${INPUT_HOSTNAME}"

    if [ ${#SHORT_HOSTNAME} -lt 2 ]; then
        log_error "Hostname demasiado corto (mínimo 2 caracteres): '${SHORT_HOSTNAME}'"
        exit 1
    fi
    if ! [[ "${SHORT_HOSTNAME}" =~ ^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$ ]]; then
        log_error "Hostname inválido: '${SHORT_HOSTNAME}'."
        log_error "Solo letras, números y guiones. No puede empezar/terminar con guion."
        exit 1
    fi

    if [ "${SHORT_HOSTNAME}" = "${CURRENT_HOSTNAME}" ]; then
        CHANGE_HOSTNAME=false
        log_info "Hostname ya es ${SHORT_HOSTNAME}. Sin cambios."
    else
        CHANGE_HOSTNAME=true
    fi
fi

echo ""
read -r -p "🔒 ¿Generar certificado autofirmado y habilitar HTTPS? [S/n]: " INPUT_HTTPS
ENABLE_HTTPS=true
if [[ "${INPUT_HTTPS:-S}" =~ ^[nN]$ ]]; then
    ENABLE_HTTPS=false
fi

echo ""
log_info "Resumen:"
echo "   • Dominio/IP     : ${DOMAIN}"
echo "   • Usuario        : ${APP_USER}"
echo "   • Directorio     : ${APP_DIR}"
echo "   • HTTPS          : $( [ "${ENABLE_HTTPS}" = true ] && echo 'Sí (cert autofirmado, 1 año)' || echo 'No' )"
if [ "${CHANGE_HOSTNAME}" = true ]; then
    echo "   • Hostname       : ${CURRENT_HOSTNAME} → ${SHORT_HOSTNAME}"
else
    echo "   • Hostname       : Sin cambios (${SHORT_HOSTNAME})"
fi
echo ""
read -r -p "¿Continuar? [s/N]: " CONFIRM
if [[ ! "${CONFIRM:-N}" =~ ^[sS]$ ]]; then
    log_warn "Cancelado por el usuario."
    exit 0
fi

# ============================================================
# 5. Configurar hostname del servidor (opcional)
# ============================================================
if [ "${CHANGE_HOSTNAME}" = true ]; then
    log_info "Configurando hostname: ${CURRENT_HOSTNAME} → ${SHORT_HOSTNAME}"

    hostnamectl set-hostname "${SHORT_HOSTNAME}" 2>/dev/null || {
        echo "${SHORT_HOSTNAME}" > /etc/hostname
        hostname "${SHORT_HOSTNAME}"
    }

    if grep -q "^127.0.1.1" /etc/hosts; then
        sed -i '/^127\.0\.1\.1/d' /etc/hosts
    fi
    sed -i "\|[[:space:]]${DOMAIN}[[:space:]]|d" /etc/hosts 2>/dev/null || true
    echo "127.0.1.1    ${DOMAIN}    ${SHORT_HOSTNAME}" >> /etc/hosts

    log_ok "Hostname configurado: ${SHORT_HOSTNAME}"
    log_info "/etc/hosts actualizado: 127.0.1.1 ${DOMAIN} ${SHORT_HOSTNAME}"
fi

# ============================================================
# 6. Actualizar sistema e instalar dependencias
# ============================================================
log_info "Actualizando lista de paquetes..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y

log_info "Instalando dependencias base..."
apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv python3-dev \
    git curl wget ca-certificates \
    nginx \
    build-essential pkg-config \
    ufw fail2ban openssl \
    rsync

log_info "Instalando dependencias de WeasyPrint / PDF..."
apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangoft2-1.0-0 libpangocairo-1.0-0 \
    libcairo2 libcairo2-dev \
    libgdk-pixbuf-2.0-0 libgdk-pixbuf2.0-dev \
    libffi-dev \
    libxml2 libxml2-dev libxslt1-dev libxslt1.1 \
    libjpeg-turbo8 libjpeg-turbo8-dev \
    libopenjp2-7 libopenjp2-7-dev \
    shared-mime-info xdg-utils \
    libharfbuzz0b libharfbuzz-dev \
    libfontconfig1 libfontconfig1-dev \
    fonts-dejavu fonts-liberation \
    || log_warn "Algún paquete de WeasyPrint falló. Se continuará; podría afectar al PDF."

log_ok "Dependencias del sistema instaladas."

# ============================================================
# 7. Crear usuario del sistema
# ============================================================
if ! id "${APP_USER}" &>/dev/null; then
    log_info "Creando usuario del sistema: ${APP_USER}"
    useradd --system --create-home --shell /bin/bash "${APP_USER}"
    log_ok "Usuario ${APP_USER} creado."
else
    log_info "Usuario ${APP_USER} ya existe."
fi

usermod -aG www-data "${APP_USER}" || true

# ============================================================
# 8. Clonar o usar repositorio existente
# ============================================================
if [ "${IS_IN_REPO}" = true ]; then
    log_info "Usando repositorio existente en ${APP_DIR}"
    if [ "$(pwd)" != "${APP_DIR}" ]; then
        log_info "Moviendo repo de $(pwd) → ${APP_DIR}"
        mkdir -p "$(dirname "${APP_DIR}")"
        if [ -e "${APP_DIR}" ]; then
            log_error "${APP_DIR} ya existe y no está vacío. Abortando."
            exit 1
        fi
        mv "$(pwd)" "${APP_DIR}"
    fi
else
    if [ -d "${APP_DIR}/.git" ]; then
        log_info "Repo existente en ${APP_DIR}, actualizando..."
        sudo -u "${APP_USER}" git -C "${APP_DIR}" fetch --all
        sudo -u "${APP_USER}" git -C "${APP_DIR}" reset --hard origin/main
    else
        log_info "Clonando repositorio en ${APP_DIR}..."

        if [ -e "${APP_DIR}" ] && [ -n "$(ls -A "${APP_DIR}" 2>/dev/null)" ]; then
            log_error "${APP_DIR} existe y no está vacío. Abortando."
            exit 1
        fi

        mkdir -p "${APP_DIR}"
        chown "${APP_USER}:www-data" "${APP_DIR}"
        chmod 750 "${APP_DIR}"

        sudo -u "${APP_USER}" git clone "${REPO_URL}" "${APP_DIR}"
    fi
fi

chown -R "${APP_USER}:www-data" "${APP_DIR}"
chmod 750 "${APP_DIR}"

log_ok "Código fuente listo en ${APP_DIR}"

# ============================================================
# 9. Crear directorios necesarios
# ============================================================
log_info "Creando directorios de trabajo..."
sudo -u "${APP_USER}" mkdir -p "${APP_DIR}/instance"
sudo -u "${APP_USER}" mkdir -p "${APP_DIR}/instance/backups"
sudo -u "${APP_USER}" mkdir -p "${APP_DIR}/logs"
sudo -u "${APP_USER}" mkdir -p "${APP_DIR}/app/static/uploads/ordenes"
sudo -u "${APP_USER}" mkdir -p "${APP_DIR}/app/static/uploads/tmp"

chown -R "${APP_USER}:www-data" "${APP_DIR}/instance" "${APP_DIR}/logs" "${APP_DIR}/app/static/uploads"
chmod 750 "${APP_DIR}/instance"
chmod 750 "${APP_DIR}/instance/backups"
chmod 750 "${APP_DIR}/logs"
chmod 755 "${APP_DIR}/app/static/uploads"
chmod 755 "${APP_DIR}/app/static/uploads/ordenes"
chmod 755 "${APP_DIR}/app/static/uploads/tmp"

log_ok "Directorios listos."

# ============================================================
# 10. Crear entorno virtual
# ============================================================
VENV_DIR="${APP_DIR}/venv"

if [ ! -d "${VENV_DIR}" ]; then
    log_info "Creando virtualenv..."
    sudo -u "${APP_USER}" python3 -m venv "${VENV_DIR}"
else
    log_info "Virtualenv existente, reutilizando."
fi

log_info "Actualizando pip..."
sudo -u "${APP_USER}" "${VENV_DIR}/bin/pip" install --upgrade pip wheel setuptools -q

log_info "Instalando dependencias Python (requirements.txt)..."
sudo -u "${APP_USER}" "${VENV_DIR}/bin/pip" install -r "${APP_DIR}/requirements.txt" -q

log_info "Instalando gunicorn y utilidades adicionales..."
sudo -u "${APP_USER}" "${VENV_DIR}/bin/pip" install gunicorn python-dotenv -q

log_ok "Dependencias Python instaladas."

# ============================================================
# 11. Generar .env  (SIN SERVER_NAME ni PREFERRED_URL_SCHEME)
# ============================================================
ENV_FILE="${APP_DIR}/.env"

if [ -f "${ENV_FILE}" ]; then
    log_warn "El archivo .env ya existe. Se conservará."
else
    log_info "Generando .env..."
    SECRET_KEY=$(openssl rand -hex 32)

    # OJO: DATABASE_URL con CUATRO slashes (sqlite:////ruta/absoluta)
    sudo -u "${APP_USER}" bash -c "cat > '${ENV_FILE}' <<EOF
# ============================================================
# TraviesoPrint - Variables de entorno
# ============================================================
SECRET_KEY=${SECRET_KEY}
DATABASE_URL=sqlite:///${APP_DIR}/instance/traviesoprint.db
FLASK_APP=app:create_app
FLASK_DEBUG=False
FLASK_ENV=production

# Rutas
UPLOAD_FOLDER=${APP_DIR}/app/static/uploads
LOG_FOLDER=${APP_DIR}/logs
EOF
"
    chown "${APP_USER}:${APP_USER}" "${ENV_FILE}"
    chmod 600 "${ENV_FILE}"
    log_ok ".env generado en ${ENV_FILE}"
fi

# ============================================================
# 12. Preparar base de datos (schema + migraciones)
# ============================================================
log_info "Preparando base de datos..."

DB_FILE="${APP_DIR}/instance/traviesoprint.db"

TABLE_COUNT=0
if [ -f "${DB_FILE}" ]; then
    TABLE_COUNT=$(sudo -u "${APP_USER}" "${VENV_DIR}/bin/python" -c "
import sqlite3
try:
    conn = sqlite3.connect('${DB_FILE}')
    cur = conn.cursor()
    cur.execute(\"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'\")
    print(cur.fetchone()[0])
    conn.close()
except Exception:
    print(0)
" 2>/dev/null || echo "0")
fi

if [ "${TABLE_COUNT}" -gt 0 ]; then
    log_info "BD existente con ${TABLE_COUNT} tablas. Aplicando migraciones..."

    if sudo -u "${APP_USER}" bash -c "
        cd '${APP_DIR}'
        set -a; source .env; set +a
        '${VENV_DIR}/bin/flask' db upgrade
    "; then
        log_ok "Migraciones aplicadas correctamente."
    else
        log_error "flask db upgrade falló sobre una BD existente."
        exit 1
    fi
else
    log_info "BD vacía o inexistente. Creando schema desde modelos..."

    if [ -f "${DB_FILE}" ]; then
        BACKUP="${APP_DIR}/instance/backups/traviesoprint_preinstall_$(date +%Y%m%d_%H%M%S).db"
        mv "${DB_FILE}" "${BACKUP}"
        log_warn "BD previa sin tablas movida a: ${BACKUP}"
    fi

    if ! sudo -u "${APP_USER}" bash -c "
        cd '${APP_DIR}'
        set -a; source .env; set +a
        '${VENV_DIR}/bin/python' -c '
from app import create_app, db
app = create_app()
with app.app_context():
    db.create_all()
    print(\"Schema creado con db.create_all()\")
'
    "; then
        log_error "db.create_all() falló. Revisa el traceback arriba."
        exit 1
    fi

    if ! sudo -u "${APP_USER}" bash -c "
        cd '${APP_DIR}'
        set -a; source .env; set +a
        '${VENV_DIR}/bin/flask' db stamp head
    "; then
        log_error "flask db stamp head falló. Revisa el traceback arriba."
        exit 1
    fi

    log_ok "Schema creado y migraciones marcadas como aplicadas."
fi

FINAL_COUNT=$(sudo -u "${APP_USER}" "${VENV_DIR}/bin/python" -c "
import sqlite3
conn = sqlite3.connect('${DB_FILE}')
cur = conn.cursor()
cur.execute(\"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'\")
print(cur.fetchone()[0])
conn.close()
" 2>/dev/null || echo "0")

if [ "${FINAL_COUNT}" -lt 1 ]; then
    log_error "La BD no contiene tablas tras la preparación. Algo falló."
    exit 1
fi

log_ok "Base de datos lista (${FINAL_COUNT} tablas)."

# ============================================================
# 13. Servicio systemd
# ============================================================
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SOCKET_FILE="${APP_DIR}/${APP_NAME}.sock"

log_info "Creando servicio systemd..."

cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=TraviesoPrint - Gunicorn
After=network.target

[Service]
Type=simple
User=${APP_USER}
Group=www-data
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env

ExecStartPre=/bin/rm -f ${SOCKET_FILE}

ExecStart=${VENV_DIR}/bin/gunicorn \\
    --workers 3 \\
    --worker-class sync \\
    --bind unix:${SOCKET_FILE} \\
    --access-logfile - \\
    --error-logfile - \\
    --capture-output \\
    --log-level info \\
    --timeout 120 \\
    'app:create_app()'

ExecReload=/bin/kill -s HUP \$MAINPID
Restart=always
RestartSec=3
KillMode=mixed

UMask=0007

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=${APP_DIR}/instance ${APP_DIR}/logs ${APP_DIR}/app/static/uploads

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.service"

rm -f "${SOCKET_FILE}"

log_ok "Servicio systemd configurado."

# ============================================================
# 14. Certificado SSL autofirmado
# ============================================================
if [ "${ENABLE_HTTPS}" = true ]; then
    log_info "Generando certificado SSL autofirmado (válido 1 año)..."

    SAN="DNS:${DOMAIN},DNS:localhost,IP:${SERVER_IP},IP:127.0.0.1"

    mkdir -p "$(dirname "${SSL_CERT}")" "$(dirname "${SSL_KEY}")"

    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout "${SSL_KEY}" \
        -out    "${SSL_CERT}" \
        -subj   "/C=XX/ST=XX/L=XX/O=TraviesoPrint/CN=${DOMAIN}" \
        -addext "subjectAltName=${SAN}" \
        2>/dev/null

    chmod 600 "${SSL_KEY}"
    chmod 644 "${SSL_CERT}"
    chown root:root "${SSL_KEY}" "${SSL_CERT}"

    log_ok "Certificado generado:"
    echo "   • Cert : ${SSL_CERT}"
    echo "   • Key  : ${SSL_KEY}"
    echo "   • Válido hasta: $(openssl x509 -enddate -noout -in ${SSL_CERT} | cut -d= -f2)"
fi

# ============================================================
# 15. Nginx  (SIN include proxy_params, headers explícitos)
# ============================================================
NGINX_CONF="/etc/nginx/sites-available/${APP_NAME}"

log_info "Configurando Nginx..."

if [ "${ENABLE_HTTPS}" = true ]; then
    cat > "${NGINX_CONF}" <<EOF
# Redirección HTTP → HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};
    return 301 https://\$http_host\$request_uri;
}

# Servidor HTTPS (certificado autofirmado)
# "listen ... http2" (sintaxis antigua) por compatibilidad Nginx 1.18–1.24
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${DOMAIN};

    ssl_certificate     ${SSL_CERT};
    ssl_certificate_key ${SSL_KEY};

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    server_tokens off;
    client_max_body_size 50M;

    access_log /var/log/nginx/${APP_NAME}-access.log;
    error_log  /var/log/nginx/${APP_NAME}-error.log;

    location /static/ {
        alias ${APP_DIR}/app/static/;
        expires 30d;
        access_log off;
        add_header Cache-Control "public, immutable";
    }

    location / {
        # Importante: no usar "include proxy_params" — definimos headers
        # explícitamente para asegurar que "Host" llegue correctamente
        # a Gunicorn (evita "Invalid HTTP Header: 'HOST'").
        proxy_pass http://unix:${SOCKET_FILE}:/;
        proxy_http_version 1.1;

        proxy_set_header Host              \$http_host;
        proxy_set_header X-Real-IP         \$remote_addr;
        proxy_set_header X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host  \$http_host;

        proxy_read_timeout 120s;
        proxy_connect_timeout 120s;
        proxy_buffering off;
    }
}
EOF
    log_ok "Nginx configurado con HTTPS (autofirmado)."
else
    cat > "${NGINX_CONF}" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    server_tokens off;
    client_max_body_size 50M;

    access_log /var/log/nginx/${APP_NAME}-access.log;
    error_log  /var/log/nginx/${APP_NAME}-error.log;

    location /static/ {
        alias ${APP_DIR}/app/static/;
        expires 30d;
        access_log off;
        add_header Cache-Control "public, immutable";
    }

    location / {
        proxy_pass http://unix:${SOCKET_FILE}:/;
        proxy_http_version 1.1;

        proxy_set_header Host              \$http_host;
        proxy_set_header X-Real-IP         \$remote_addr;
        proxy_set_header X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host  \$http_host;

        proxy_read_timeout 120s;
        proxy_connect_timeout 120s;
        proxy_buffering off;
    }
}
EOF
    log_ok "Nginx configurado (solo HTTP)."
fi

ln -sf "${NGINX_CONF}" "/etc/nginx/sites-enabled/${APP_NAME}"

if [ -e /etc/nginx/sites-enabled/default ]; then
    rm -f /etc/nginx/sites-enabled/default
fi

nginx -t
systemctl reload nginx || systemctl restart nginx

log_ok "Nginx recargado."

# ============================================================
# 16. Firewall (UFW)
# ============================================================
log_info "Configurando firewall UFW..."
ufw allow 22/tcp   >/dev/null 2>&1 || true
ufw allow 80/tcp   >/dev/null 2>&1 || true
ufw allow 443/tcp  >/dev/null 2>&1 || true
ufw --force enable >/dev/null 2>&1 || true
log_ok "Firewall activo (22, 80, 443)."

# ============================================================
# 17. Arrancar el servicio
# ============================================================
log_info "Iniciando ${SERVICE_NAME}..."
systemctl restart "${SERVICE_NAME}.service"
sleep 3

if systemctl is-active --quiet "${SERVICE_NAME}.service"; then
    log_ok "Servicio activo."
else
    log_error "El servicio no arrancó. Últimas líneas del log:"
    echo ""
    journalctl -u "${SERVICE_NAME}.service" -n 30 --no-pager
    echo ""
    log_error "Revisa el traceback arriba."
    exit 1
fi

# ============================================================
# 18. Prueba final desde el propio servidor
# ============================================================
log_info "Verificando respuesta HTTPS desde el servidor..."
sleep 1
HTTP_CODE=$(curl -k -o /dev/null -s -w "%{http_code}" "https://${DOMAIN}/" 2>/dev/null || echo "000")
if [ "${HTTP_CODE}" = "200" ] || [ "${HTTP_CODE}" = "302" ]; then
    log_ok "Nginx responde correctamente (HTTP ${HTTP_CODE})."
else
    log_warn "Respuesta inesperada del servidor: HTTP ${HTTP_CODE}"
    log_warn "Revisa: sudo journalctl -u ${SERVICE_NAME} -n 30 && sudo tail -30 /var/log/nginx/${APP_NAME}-error.log"
fi

# ============================================================
# 19. Resumen final
# ============================================================
URL_FINAL="http://${DOMAIN}"
[ "${ENABLE_HTTPS}" = true ] && URL_FINAL="https://${DOMAIN}"

echo ""
echo -e "${GREEN}${BOLD}=================================================="
echo "  ✅ Instalación completada"
echo -e "==================================================${NC}"
echo ""
echo -e "  🌐 URL:         ${BOLD}${URL_FINAL}${NC}"
echo -e "  📂 Directorio:  ${APP_DIR}"
echo -e "  👤 Usuario:     ${APP_USER}"
echo -e "  🐍 Virtualenv:  ${VENV_DIR}"
echo -e "  🗄️  BD SQLite:   ${APP_DIR}/instance/traviesoprint.db"
echo -e "  📄 Logs:        ${APP_DIR}/logs/"
echo -e "  🖥️  Hostname:    $(hostname)"

if [ "${ENABLE_HTTPS}" = true ]; then
    echo -e "  🔒 Cert SSL:    ${SSL_CERT}"
    echo -e "                  (autofirmado, expira: $(openssl x509 -enddate -noout -in ${SSL_CERT} | cut -d= -f2))"
fi

echo ""
echo -e "  ${BOLD}Comandos útiles:${NC}"
echo "    systemctl status  ${SERVICE_NAME}"
echo "    systemctl restart ${SERVICE_NAME}"
echo "    journalctl -u ${SERVICE_NAME} -f"
echo "    nginx -t && systemctl reload nginx"
echo ""

if [ "${ENABLE_HTTPS}" = true ]; then
    echo -e "  ${YELLOW}${BOLD}⚠️  CERTIFICADO AUTOFIRMADO:${NC}"
    echo -e "   El navegador mostrará una advertencia de seguridad la primera vez."
    echo -e "   Es normal y esperado: solo acepta la excepción y continúa."
    echo ""
fi

echo -e "  ${YELLOW}${BOLD}PRIMEROS PASOS:${NC}"
echo -e "   1. Abre ${URL_FINAL} en tu navegador."
echo -e "   2. Acepta la advertencia del certificado (si aplica)."
echo -e "   3. Se abrirá el asistente de configuración inicial."
echo -e "   4. Crea el usuario administrador."
echo ""
echo -e "  ${YELLOW}ACTUALIZACIONES FUTURAS:${NC}"
echo -e "   Ejecuta de nuevo:  sudo ${APP_DIR}/install.sh"
echo -e "   O usa el script:   sudo ${APP_DIR}/deploy.sh"
echo ""
echo -e "${GREEN}${BOLD}==================================================${NC}"