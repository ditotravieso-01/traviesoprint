#!/bin/bash
# ================================================================
# TraviesoPrint - Script de instalación automática
# Compatible con Ubuntu 24.04 LTS
# ================================================================

set -e  # Salir si hay error

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}==================================================${NC}"
echo -e "${GREEN}   TraviesoPrint - Instalación automática v1.0   ${NC}"
echo -e "${GREEN}==================================================${NC}"

# ------------------------------------------------
# 1. Verificar que se ejecuta como root
# ------------------------------------------------
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Este script debe ejecutarse como root. Usa: sudo ./install.sh${NC}"
    exit 1
fi

# ------------------------------------------------
# 2. Variables de configuración (puedes cambiarlas)
# ------------------------------------------------
APP_USER="travieso"
APP_DIR="/home/$APP_USER/traviesoprint"
REPO_URL="https://github.com/ditotravieso-01/cairostudiokit.git"  # Cambia cuando actualices el nombre
SERVER_IP=$(hostname -I | awk '{print $1}')  # IP automática
DOMAIN=${SERVER_IP}  # Puedes cambiarlo por un dominio

# Preguntar por el dominio/IP
read -p "🌐 Dominio o IP pública [$SERVER_IP]: " input_domain
if [ ! -z "$input_domain" ]; then
    DOMAIN="$input_domain"
fi

# ------------------------------------------------
# 3. Actualizar sistema e instalar dependencias
# ------------------------------------------------
echo -e "${YELLOW}📦 Actualizando sistema...${NC}"
apt update && apt upgrade -y

echo -e "${YELLOW}📦 Instalando dependencias del sistema...${NC}"
apt install -y \
    python3 python3-pip python3-venv python3-dev \
    git nginx supervisor \
    build-essential libpango1.0-dev libcairo2-dev \
    libjpeg-dev libgif-dev librsvg2-dev libffi-dev \
    libxml2-dev libxslt1-dev shared-mime-info \
    xdg-utils libharfbuzz-dev libfontconfig1-dev \
    ufw fail2ban openssl

# ------------------------------------------------
# 4. Crear usuario de la aplicación (si no existe)
# ------------------------------------------------
if ! id "$APP_USER" &>/dev/null; then
    echo -e "${YELLOW}👤 Creando usuario $APP_USER...${NC}"
    useradd -m -s /bin/bash "$APP_USER"
fi

# ------------------------------------------------
# 5. Clonar/actualizar repositorio
# ------------------------------------------------
echo -e "${YELLOW}📂 Obteniendo el código fuente...${NC}"
if [ -d "$APP_DIR" ]; then
    echo -e "${YELLOW}Directorio existe. Actualizando...${NC}"
    sudo -u "$APP_USER" bash -c "cd $APP_DIR && git pull origin main"
else
    sudo -u "$APP_USER" bash -c "git clone $REPO_URL $APP_DIR"
fi

# ------------------------------------------------
# 6. Crear entorno virtual e instalar dependencias Python
# ------------------------------------------------
echo -e "${YELLOW}🐍 Configurando entorno virtual...${NC}"
sudo -u "$APP_USER" bash -c "cd $APP_DIR && python3 -m venv venv"
sudo -u "$APP_USER" bash -c "cd $APP_DIR && source venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt gunicorn python-dotenv weasyprint"

# ------------------------------------------------
# 7. Crear directorios necesarios y asignar permisos
# ------------------------------------------------
echo -e "${YELLOW}📁 Creando directorios...${NC}"
sudo -u "$APP_USER" mkdir -p "$APP_DIR/instance"
sudo -u "$APP_USER" mkdir -p "$APP_DIR/app/static/uploads"
sudo -u "$APP_USER" mkdir -p "$APP_DIR/logs"
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"
chmod 755 "$APP_DIR"
chmod 755 "$APP_DIR/instance"
chmod 755 "$APP_DIR/app/static/uploads"

# ------------------------------------------------
# 8. Configurar variables de entorno (.env)
# ------------------------------------------------
echo -e "${YELLOW}🔐 Generando .env...${NC}"
SECRET_KEY=$(openssl rand -base64 32)
sudo -u "$APP_USER" bash -c "cat > $APP_DIR/.env <<EOF
SECRET_KEY=$SECRET_KEY
DATABASE_URL=sqlite:///$APP_DIR/instance/traviesoprint.db
FLASK_DEBUG=False
FLASK_APP=app:create_app
EOF"

# ------------------------------------------------
# 9. Inicializar la base de datos (vacía, sin datos)
# ------------------------------------------------
echo -e "${YELLOW}🗄️ Creando estructura de base de datos...${NC}"
sudo -u "$APP_USER" bash -c "cd $APP_DIR && source venv/bin/activate && export FLASK_APP=app:create_app && flask shell -c 'from app import db; db.create_all()'"

# ------------------------------------------------
# 10. Configurar servicio systemd
# ------------------------------------------------
echo -e "${YELLOW}⚙️ Configurando servicio systemd...${NC}"
cat > /etc/systemd/system/traviesoprint.service <<EOF
[Unit]
Description=TraviesoPrint - Gunicorn server
After=network.target

[Service]
User=$APP_USER
Group=www-data
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/venv/bin"
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/gunicorn --workers 3 --bind unix:$APP_DIR/traviesoprint.sock app:create_app()
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable traviesoprint.service

# ------------------------------------------------
# 11. Configurar Nginx
# ------------------------------------------------
echo -e "${YELLOW}🌐 Configurando Nginx...${NC}"
cat > /etc/nginx/sites-available/traviesoprint <<EOF
server {
    listen 80;
    server_name $DOMAIN;

    location /static/ {
        alias $APP_DIR/app/static/;
        expires 30d;
    }

    location / {
        include proxy_params;
        proxy_pass http://unix:$APP_DIR/traviesoprint.sock;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

ln -sf /etc/nginx/sites-available/traviesoprint /etc/nginx/sites-enabled/
nginx -t && systemctl restart nginx

# ------------------------------------------------
# 12. Iniciar el servicio
# ------------------------------------------------
echo -e "${YELLOW}🚀 Iniciando TraviesoPrint...${NC}"
systemctl start traviesoprint.service

# ------------------------------------------------
# 13. Configurar firewall (UFW)
# ------------------------------------------------
echo -e "${YELLOW}🛡️ Configurando firewall...${NC}"
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# ------------------------------------------------
# 14. Mostrar información final
# ------------------------------------------------
echo -e "${GREEN}==================================================${NC}"
echo -e "${GREEN}✅ Instalación completada con éxito!${NC}"
echo -e "${GREEN}==================================================${NC}"
echo -e "🌐 Accede a la aplicación: http://$DOMAIN"
echo -e "📂 Directorio: $APP_DIR"
echo -e "👤 Usuario: $APP_USER"
echo -e ""
echo -e "Comandos útiles:"
echo -e "  - Ver logs: sudo journalctl -u traviesoprint.service -f"
echo -e "  - Reiniciar: sudo systemctl restart traviesoprint.service"
echo -e "  - Estado: sudo systemctl status traviesoprint.service"
echo -e ""
echo -e "${YELLOW}⚠️  IMPORTANTE:${NC}"
echo -e "  1. Abre http://$DOMAIN en tu navegador."
echo -e "  2. Se mostrará el asistente de instalación (setup)."
echo -e "  3. Completa los pasos para crear el usuario administrador."
echo -e "  4. Después del setup, inicia sesión y usa el sistema."
echo -e "${GREEN}==================================================${NC}"
