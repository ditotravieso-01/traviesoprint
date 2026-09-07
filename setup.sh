#!/bin/bash
# =============================================================================
# Cairostudiokit – Instalación inicial en LXC nuevo
# =============================================================================
set -e

PROJECT_DIR="/opt/cairostudiokit"

echo "=== Instalando dependencias del sistema ==="
apt update
apt install -y python3 python3-pip python3-venv nginx git curl cron

echo "=== Creando usuario cairostudiokit ==="
id -u cairostudiokit &>/dev/null || useradd -m -s /bin/bash cairostudiokit

echo "=== Ajustando permisos del proyecto ==="
chown -R cairostudiokit:cairostudiokit "$PROJECT_DIR"

echo "=== Creando entornos virtuales ==="
mkdir -p /opt/venvs
python3 -m venv /opt/venvs/etiquetas
python3 -m venv /opt/venvs/carteles

/opt/venvs/etiquetas/bin/pip install -r "$PROJECT_DIR/requirements.txt"
/opt/venvs/carteles/bin/pip install -r "$PROJECT_DIR/requirements.txt"

chown -R cairostudiokit:cairostudiokit /opt/venvs

echo "=== Instalando servicios systemd ==="
cp "$PROJECT_DIR/services"/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable etiquetas carteles calculadora-monitor

echo "=== Configurando sudo para reinicio de servicios ==="
echo "cairostudiokit ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart etiquetas.service, /usr/bin/systemctl restart carteles.service" > /etc/sudoers.d/cairostudiokit

echo "=== Generando certificado SSL autofirmado para *.cairostudio.cu ==="
mkdir -p /etc/nginx/ssl
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout /etc/nginx/ssl/cairostudiokit.key \
  -out /etc/nginx/ssl/cairostudiokit.crt \
  -subj "/C=CU/ST=LaHabana/L=Centro/O=CairoStudio/CN=*.cairostudio.cu"

echo "=== Configurando Nginx ==="
cp "$PROJECT_DIR/config/nginx-cairostudiokit.conf" /etc/nginx/sites-available/cairostudiokit
ln -sf /etc/nginx/sites-available/cairostudiokit /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx

echo "=== Configurando tarea cron para despliegue automático ==="
echo "* * * * * cairostudiokit cd $PROJECT_DIR && bash deploy.sh >> $PROJECT_DIR/deploy.log 2>&1" > /etc/cron.d/cairostudiokit-deploy

echo "=== Iniciando servicios ==="
systemctl enable etiquetas carteles calculadora-monitor
systemctl start etiquetas carteles calculadora-monitor

echo "=== Verificación ==="
sleep 2
curl -s http://127.0.0.1:5000/ > /dev/null && echo "✅ Calculadora de etiquetas OK" || echo "❌ Falló etiquetas"
curl -s http://127.0.0.1:5001/ > /dev/null && echo "✅ Calculadora de lona OK" || echo "❌ Falló lona"
curl -s http://127.0.0.1/ > /dev/null && echo "✅ Portal OK" || echo "❌ Falló portal"

echo ""
echo "=== 🎉 Instalación completada ==="
echo "Portal: http://10.10.10.25/"