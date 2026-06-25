#!/bin/bash
# =============================================================================
# CairostudioKit – Script de instalación en LXC nuevo
# =============================================================================
set -e

echo "=== Instalando dependencias del sistema ==="
apt update
apt install -y python3 python3-pip python3-venv nginx git curl

echo "=== Creando usuario cairokit ==="
id -u cairokit &>/dev/null || useradd -m -s /bin/bash cairokit

echo "=== Copiando proyecto a /opt/cairokit ==="
mkdir -p /opt/cairokit
cp -r . /opt/cairokit
chown -R cairokit:cairokit /opt/cairokit

echo "=== Creando entornos virtuales ==="
mkdir -p /opt/venvs
python3 -m venv /opt/venvs/calculadora
python3 -m venv /opt/venvs/lona

/opt/venvs/calculadora/bin/pip install -r /opt/cairokit/requirements.txt
/opt/venvs/lona/bin/pip install -r /opt/cairokit/requirements.txt

chown -R cairokit:cairokit /opt/venvs

echo "=== Instalando servicios systemd ==="
cp /opt/cairokit/services/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable calculadora lona-calculadora calculadora-monitor

echo "=== Configurando sudo para reinicio de servicios ==="
echo "cairokit ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart calculadora.service, /usr/bin/systemctl restart lona-calculadora.service" > /etc/sudoers.d/cairokit

echo "=== Configurando Nginx ==="
cp /opt/cairokit/config/nginx-cairokit.conf /etc/nginx/sites-available/cairokit
ln -sf /etc/nginx/sites-available/cairokit /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx

echo "=== Iniciando servicios ==="
systemctl start calculadora lona-calculadora calculadora-monitor

echo "=== Verificación ==="
sleep 2
curl -s http://127.0.0.1:5000/ > /dev/null && echo "✅ Calculadora de etiquetas OK" || echo "❌ Falló etiquetas"
curl -s http://127.0.0.1:5001/ > /dev/null && echo "✅ Calculadora de lona OK" || echo "❌ Falló lona"
curl -s http://127.0.0.1/ > /dev/null && echo "✅ Portal OK" || echo "❌ Falló portal"

echo "=== ¡Despliegue completado! ==="
echo "Accede a:"
echo "  http://10.10.10.25/          (portal)"
echo "  http://calculadora.cairostudio.cu/"
echo "  http://lona.cairostudio.cu/"