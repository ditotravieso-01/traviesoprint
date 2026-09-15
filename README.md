# TraviesoPrint - Gestión para talleres de impresión

**TraviesoPrint** es una plataforma web para gestionar talleres de impresión
y estudios creativos. Administra órdenes, inventario híbrido (unidades y
metros), workflow Kanban, clientes, empleados, calendario, generación de
etiquetas, conteos semanales de inventario y más.

**Versión actual:** v1.2

---

## 📦 ¿Qué incluye?

- **Órdenes de trabajo** con cálculo de etiquetas (ancho × alto, m² o unidades)
- **Merma operativa** con fórmula Opción C (aire sobrante reduce el gap)
- **Inventario** con soporte híbrido (rollos, metros lineales, m²)
- **Conteos semanales** con cálculo de merma imprevista
- **Módulo de etiquetas** con modo inteligente (rotación automática)
- **Workflow Kanban** de producción
- **Clientes, empleados, calendario, notificaciones**
- **Generación de PDF** de órdenes con WeasyPrint
- **Roles y permisos** (admin, comercial, económico, diseñador, operario, odalys)
- **HTTPS con certificado autofirmado** desde la instalación

---

## 🚀 Instalación en servidor

### Requisitos mínimos

| Requisito | Mínimo | Recomendado |
|-----------|--------|-------------|
| Sistema operativo | Ubuntu 22.04 LTS | Ubuntu 24.04 / 26.04 LTS |
| RAM | 2 GB | 4 GB |
| Disco | 20 GB | 40 GB |
| CPU | 2 vCPU | 4 vCPU |
| Red | IP pública o dominio | Dominio + HTTPS |

> También funciona en Debian 12+, pero solo Ubuntu está testeado oficialmente.

---

### Opción A — Instalación automática (recomendada)

**Un solo comando.** El script se encarga de todo: instala dependencias,
configura Nginx, systemd, firewall, HTTPS y prepara la base de datos.

```bash
# Descargar y ejecutar
curl -fsSL https://raw.githubusercontent.com/ditotravieso-01/traviesoprint/main/install.sh -o install.sh
sudo bash install.sh
```

El script te preguntará:

1. **Dominio o IP pública** — autodetecta la IP si pulsas Enter.
2. **Usuario Linux** para la app — por defecto `travieso`.
3. **Directorio de instalación** — por defecto `/opt/traviesoprint`.
4. **¿Habilitar HTTPS?** — genera un certificado autofirmado (responde `S` o `N`).

Al terminar, abre la URL que te indique y completa el asistente de
configuración inicial.

---

### Opción B — Clonar el repo y ejecutar el instalador

Útil si quieres inspeccionar el código antes de instalar, o si vas a
modificar algo.

```bash
git clone https://github.com/ditotravieso-01/traviesoprint.git
cd traviesoprint
sudo ./install.sh
```

El script detecta que ya estás dentro del repo y **no vuelve a clonar**.
Si decides instalar en otro directorio, moverá el repo a la ubicación que
elijas.

---

## 🔄 Actualizaciones

### Vía `deploy.sh` (recomendado)

Si instalaste en `/opt/traviesoprint`:

```bash
sudo /opt/traviesoprint/deploy.sh
```

Esto:

1. Hace backup automático de la BD SQLite.
2. Descarga los últimos cambios (`git pull`).
3. Actualiza dependencias Python.
4. Aplica migraciones Alembic.
5. Reinicia el servicio.
6. Recarga Nginx.

### Vía `install.sh` de nuevo

El instalador es idempotente. Puedes volver a ejecutarlo y detectará que
ya está instalado, aplicará solo lo que falte, y reiniciará los servicios.

```bash
sudo bash /opt/traviesoprint/install.sh
```

> ⚠️ El `.env` existente se conserva. No se regenera la `SECRET_KEY`
> ni la base de datos.

---

## 🔒 HTTPS

### Certificado autofirmado (automático)

Si durante la instalación elegiste **generar certificado autofirmado**,
ya tienes HTTPS funcionando desde el primer minuto.

El certificado:

- Es válido por **1 año** desde la instalación.
- Incluye el dominio/IP, `localhost` y `127.0.0.1` como nombres alternativos (SAN).
- Está ubicado en:
  - **Certificado:** `/etc/ssl/certs/traviesoprint.crt`
  - **Clave privada:** `/etc/ssl/private/traviesoprint.key`
- Nginx queda configurado para:
  - Redirigir todo el tráfico HTTP (`:80`) a HTTPS (`:443`).
  - Aceptar solo TLS 1.2 y 1.3.
  - Ocultar la versión de Nginx (`server_tokens off`).

### ⚠️ Advertencia del navegador

La primera vez verás **"Conexión no privada"**. Es normal y esperado en
certificados autofirmados. Solo acepta la excepción y continúa:

- **Chrome/Edge:** clic en "Avanzado" → "Continuar a …"
- **Firefox:** clic en "Avanzado" → "Aceptar el riesgo y continuar"
- **Safari:** clic en "Mostrar detalles" → "Visitar este sitio web"

### Ver la fecha de expiración del certificado

```bash
openssl x509 -enddate -noout -in /etc/ssl/certs/traviesoprint.crt
```

### Regenerar el certificado manualmente

Útil si:

- Cambió el dominio o IP del servidor.
- El certificado expiró (después de 1 año).
- Añadiste un nuevo SAN.

```bash
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /etc/ssl/private/traviesoprint.key \
    -out    /etc/ssl/certs/traviesoprint.crt \
    -subj   "/C=XX/ST=XX/L=XX/O=TraviesoPrint/CN=tu-dominio.com" \
    -addext "subjectAltName=DNS:tu-dominio.com,DNS:localhost,IP:TU_IP,IP:127.0.0.1"

sudo chmod 600 /etc/ssl/private/traviesoprint.key
sudo chmod 644 /etc/ssl/certs/traviesoprint.crt

sudo systemctl reload nginx
```

### Desactivar HTTPS

Si por alguna razón necesitas volver a HTTP puro:

1. Abre `/etc/nginx/sites-available/traviesoprint`.
2. Elimina el bloque `server { listen 443 … }`.
3. Deja solo el bloque `server { listen 80 … }` sin el `return 301`.
4. Ejecuta `sudo nginx -t && sudo systemctl reload nginx`.

---

## 🛠️ Comandos útiles

```bash
# Estado del servicio
systemctl status traviesoprint

# Ver logs en vivo
journalctl -u traviesoprint -f

# Reiniciar la app
systemctl restart traviesoprint

# Recargar Nginx (tras cambios de config)
nginx -t && systemctl reload nginx

# Backup manual de la BD
cp /opt/traviesoprint/instance/traviesoprint.db \
   /opt/traviesoprint/instance/backups/manual_$(date +%Y%m%d_%H%M%S).db

# Ejecutar comandos Flask (ej. crear admin manualmente)
cd /opt/traviesoprint
sudo -u travieso bash -c 'source venv/bin/activate && flask shell'

# Ver la fecha de expiración del certificado SSL
openssl x509 -enddate -noout -in /etc/ssl/certs/traviesoprint.crt
```

---

## 🗂️ Estructura del proyecto

```text
traviesoprint/
├── app/
│   ├── __init__.py            # create_app() factory
│   ├── models.py              # Modelos SQLAlchemy
│   ├── modulos/               # Blueprints
│   │   ├── ordenes/
│   │   ├── inventario/
│   │   ├── etiquetas/
│   │   ├── workflow/
│   │   └── ...
│   └── templates/
├── migrations/                # Alembic
├── instance/                  # BD SQLite (NO se sube al repo)
│   ├── traviesoprint.db
│   └── backups/
├── logs/                      # Logs de Gunicorn
├── venv/                      # Virtualenv (NO se sube al repo)
├── .env                       # Secretos (NO se sube al repo)
├── .gitignore
├── requirements.txt
├── install.sh
├── deploy.sh
└── README.md
```

---

## ✅ Verificación post-instalación

Después de correr el `install.sh`, prueba:

```bash
# 1. Verificar que el certificado existe y es válido
openssl x509 -in /etc/ssl/certs/traviesoprint.crt -noout -text \
    | grep -E "Subject:|Not After|DNS:|IP:"

# 2. Verificar que Nginx escucha en 443
sudo ss -tlnp | grep :443

# 3. Verificar redirect HTTP → HTTPS
curl -I http://TU_IP
# Debe responder: 301 Moved Permanently → Location: https://...

# 4. Verificar HTTPS (ignorando el cert autofirmado)
curl -kI https://TU_IP
# Debe responder: 200 OK

# 5. Ver el certificado servido por Nginx
openssl s_client -connect TU_IP:443 -servername TU_IP \
    < /dev/null 2>/dev/null \
    | openssl x509 -noout -dates
```

---

## ⚠️ Troubleshooting

### El servicio no arranca

```bash
journalctl -u traviesoprint -n 100 --no-pager
```

Causas comunes:

- `.env` mal formado → revisar `/opt/traviesoprint/.env`.
- Permisos incorrectos sobre `instance/` o `logs/`.
- Puerto 80/443 ocupado por Apache (`systemctl stop apache2`).

### Error 502 Bad Gateway

Nginx no puede hablar con Gunicorn. Verifica:

```bash
ls -l /opt/traviesoprint/traviesoprint.sock
# Debe existir y ser propiedad de travieso:www-data
```

Si no existe, el servicio de la app no arrancó. Revisa
`journalctl -u traviesoprint -n 100`.

### Nginx falla al recargar tras configurar HTTPS

```bash
sudo nginx -t
```

Causas comunes:

- El certificado o la clave no existen en las rutas indicadas.
- La clave tiene permisos que Nginx no puede leer → debe ser `root:root`
  con modo `600`.
- El dominio del `server_name` no coincide con el `CN`/`SAN` del
  certificado (esto no rompe Nginx, pero el navegador se quejará más).

### WeasyPrint falla al generar PDF

Faltan librerías del sistema. Reinstala:

```bash
sudo apt install --reinstall \
    libpango-1.0-0 libpangocairo-1.0-0 libcairo2 \
    libgdk-pixbuf-2.0-0 libffi-dev
```

### El navegador muestra "Conexión no privada"

**Es normal con un certificado autofirmado.** Acepta la excepción y
continúa. Si te molesta, la única forma de evitar el warning es usar un
dominio real con un certificado de una CA pública reconocida.

### Reiniciar todo desde cero

```bash
sudo systemctl stop traviesoprint
sudo rm -rf /opt/traviesoprint
sudo rm -f /etc/systemd/system/traviesoprint.service
sudo rm -f /etc/nginx/sites-enabled/traviesoprint
sudo rm -f /etc/nginx/sites-available/traviesoprint
sudo rm -f /etc/ssl/certs/traviesoprint.crt
sudo rm -f /etc/ssl/private/traviesoprint.key
sudo systemctl daemon-reload
sudo nginx -t && sudo systemctl reload nginx
# Luego volver a ejecutar install.sh
```

---

## ⚠️ Nota sobre las migraciones con `ñ`

Los archivos de migración tienen nombres con `ñ`:

```text
migrations/versions/8979a82c7f6c_añadir_modelo_conteosemanal.py
migrations/versions/ab25abe17607_añadir_gap_panno_cm_a_producto.py
```

Funcionan en Linux, pero si en algún momento clonas el repo en Windows o
en un sistema de archivos con encoding raro, podría fallar. **Opcionalmente**,
puedes renombrarlos a `add_conteosemanal` y `add_gap_panno_cm`
respectivamente (solo el nombre del archivo; el `revision` interno no cambia).

---

## 📄 Licencia

Privado · © TraviesoPrint / CairoStudio

---

## 📞 Soporte

- **Repositorio:** https://github.com/ditotravieso-01/traviesoprint
- **Issues:** https://github.com/ditotravieso-01/traviesoprint/issues