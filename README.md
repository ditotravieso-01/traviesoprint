# TraviesoPrint - Gestión para talleres de impresión

**TraviesoPrint** es una plataforma web desarrollada en Flask, diseñada para administrar la operativa diaria de talleres de impresión y estudios creativos. El sistema gestiona órdenes de trabajo, inventario híbrido (unidades y metros lineales), flujos de producción (Workflow Kanban), clientes, nóminas de empleados, generación de etiquetas y cálculos avanzados de mermas.

**Versión actual:** v1.2

---

## Características principales

- **Órdenes de trabajo** con cálculo dinámico de etiquetas (ancho × alto, m² o unidades).
- **Merma operativa** optimizada (aire sobrante reduce el gap).
- **Inventario híbrido** con soporte para rollos, metros lineales, m² y stock comprometido.
- **Conteos semanales** con cálculo de merma imprevista.
- **Módulo de etiquetas** con rotación automática (modo inteligente).
- **Workflow Kanban** con enrutamiento condicional según el tipo de proyecto (Gráfica, Producción, Mixto, Otro).
- **Integración con Odoo (XML-RPC)** para importación automática de clientes y pedidos de venta.
- **Generación de PDF** de órdenes de trabajo (mediante WeasyPrint).
- **Gestión de usuarios y roles** (admin, comercial, económico, diseñador, operario).
- **Despliegue seguro** con HTTPS (certificado autofirmado) y configuración de Nginx.

---

## Instalación en servidor

### Requisitos mínimos

| Requisito | Mínimo | Recomendado |
|-----------|--------|-------------|
| Sistema operativo | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS |
| RAM | 2 GB | 4 GB |
| Disco | 20 GB | 40 GB |
| CPU | 2 vCPU | 4 vCPU |
| Red | IP pública o dominio | Dominio + HTTPS |

> También funciona en Debian 12+, pero el soporte oficial está orientado a Ubuntu.

### Opción A — Instalación automática (Recomendada)

El script de instalación automatiza el despliegue completo: instala dependencias, configura Nginx, systemd, firewall, HTTPS y prepara la base de datos.

```bash
# Descargar y ejecutar el instalador
curl -fsSL https://raw.githubusercontent.com/ditotravieso-01/traviesoprint/main/install.sh -o install.sh
sudo bash install.sh

El asistente solicitará:

    Dominio o IP pública (autodetecta la IP si se presiona Enter).

    Usuario Linux para el servicio (por defecto travieso).

    Directorio de instalación (por defecto /opt/traviesoprint).

    Habilitar HTTPS (genera un certificado autofirmado).

Opción B — Instalación desde el repositorio

Útil si se necesita auditar el código antes de instalar o si se planea modificar el núcleo del sistema.
bash

git clone https://github.com/ditotravieso-01/traviesoprint.git
cd traviesoprint
sudo ./install.sh

Nota: Si el script detecta que se ejecuta desde dentro del repositorio clonado, omitirá el paso de descarga.
Actualizaciones
Vía deploy.sh (Recomendado)

Para actualizar una instalación existente en /opt/traviesoprint:
bash

sudo /opt/traviesoprint/deploy.sh

Este script realiza las siguientes acciones de forma secuencial:

    Genera un respaldo automático de la base de datos SQLite.

    Descarga los últimos cambios (git pull).

    Actualiza las dependencias de Python.

    Aplica las migraciones de Alembic.

    Reinicia el servicio de Gunicorn y recarga Nginx.

Vía install.sh (Reinstalación)

El script de instalación es idempotente. Si se vuelve a ejecutar, detectará la instalación existente, aplicará las configuraciones faltantes y reiniciará los servicios sin afectar la base de datos ni el archivo .env.
Configuración de HTTPS

Si durante la instalación se optó por generar el certificado autofirmado, el sistema quedará configurado automáticamente:

    Certificado válido por 1 año.

    Ubicación: /etc/ssl/certs/traviesoprint.crt y /etc/ssl/private/traviesoprint.key.

    Redirección forzada de HTTP a HTTPS.

    Soporte exclusivo para TLS 1.2 y 1.3.

Advertencia del navegador

Al ser un certificado autofirmado, los navegadores mostrarán una advertencia de "Conexión no privada" en el primer acceso. Es un comportamiento esperado; basta con aceptar la excepción para continuar.
Regenerar el certificado

Si cambia el dominio, la IP o expira el certificado, se puede regenerar manualmente:
bash

sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /etc/ssl/private/traviesoprint.key \
    -out    /etc/ssl/certs/traviesoprint.crt \
    -subj   "/C=XX/ST=XX/L=XX/O=TraviesoPrint/CN=tu-dominio.com" \
    -addext "subjectAltName=DNS:tu-dominio.com,DNS:localhost,IP:TU_IP,IP:127.0.0.1"

sudo chmod 600 /etc/ssl/private/traviesoprint.key
sudo chmod 644 /etc/ssl/certs/traviesoprint.crt
sudo systemctl reload nginx

Comandos de administración
Servicio y Logs
bash

# Estado del servicio principal
systemctl status traviesoprint

# Monitoreo de logs en tiempo real
journalctl -u traviesoprint -f

# Reinicio del servicio
systemctl restart traviesoprint

# Recarga de Nginx tras cambios
nginx -t && systemctl reload nginx

Mantenimiento y Scripts locales

El sistema incluye scripts para tareas de mantenimiento directo en la base de datos:
bash

# Respaldo manual de la base de datos
cp /opt/traviesoprint/instance/traviesoprint.db \
   /opt/traviesoprint/instance/backups/manual_$(date +%Y%m%d_%H%M%S).db

# Acceso a la consola interactiva de Flask (útil para depuración)
cd /opt/traviesoprint
sudo -u travieso bash -c 'source venv/bin/activate && flask shell'

# LIMPIEZA DE BASE DE DATOS PARA PRODUCCIÓN (Uso Crítico)
# Borra órdenes, clientes, movimientos y resetea stocks comprometidos,
# pero conserva el inventario, usuarios y configuraciones.
# IMPORTANTE: Hacer respaldo antes de ejecutar.
cd /opt/traviesoprint
source venv/bin/activate
python limpiar_db.py

Estructura del proyecto
text

traviesoprint/
├── app/
│   ├── __init__.py            # Fábrica de la aplicación (create_app)
│   ├── models.py              # Modelos SQLAlchemy (Base de datos)
│   ├── modulos/               # Blueprints (Módulos de la app)
│   │   ├── ordenes/           # Lógica de órdenes de trabajo
│   │   ├── inventario/        # Gestión de stock
│   │   ├── workflow/          # Tablero Kanban y lógica de estados
│   │   └── ...
│   ├── services/              # Servicios externos (ej. Odoo XML-RPC)
│   └── templates/             # Vistas HTML (Jinja2)
├── migrations/                # Historial de Alembic (Migraciones de BD)
├── instance/                  # Base de datos SQLite y respaldos
├── logs/                      # Archivos de log de Gunicorn
├── scripts/                   # Scripts de utilidades (reset_db.sh, etc.)
├── venv/                      # Entorno virtual de Python
├── .env                       # Variables de entorno (Secretos)
├── requirements.txt           # Dependencias de Python
├── install.sh                 # Instalador automatizado
├── deploy.sh                  # Script de actualización
└── README.md

Solución de problemas (Troubleshooting)
Error 502 Bad Gateway

Nginx no logra comunicarse con Gunicorn. Verificar la existencia del socket:
bash

ls -l /opt/traviesoprint/traviesoprint.sock

Si el socket no existe o los permisos son incorrectos (debe pertenecer a travieso:www-data), el servicio web no ha iniciado correctamente. Revisar journalctl -u traviesoprint.
WeasyPrint falla al generar PDF

La generación de PDF depende de librerías del sistema. Para reinstalarlas:
bash

sudo apt install --reinstall \
    libpango-1.0-0 libpangocairo-1.0-0 libcairo2 \
    libgdk-pixbuf-2.0-0 libffi-dev

Nota sobre migraciones con caracteres especiales (ñ)

Algunos archivos de migración antiguos contienen el carácter ñ en sus nombres (ej. añadir_modelo...). Si el repositorio se clona en sistemas de archivos con codificación no UTF-8 (como ciertas configuraciones en Windows), pueden surgir errores. Se recomienda mantener el despliegue en entornos Linux.
Licencia

Este proyecto está bajo la licencia GNU General Public License v3.0 (GPLv3).
Esto significa que el software es de código abierto: cualquier persona es libre de usarlo, modificarlo y redistribuirlo, siempre y cuando las versiones derivadas se distribuyan bajo la misma licencia.

Consulta el archivo LICENSE para obtener el texto legal completo.
Contacto y Soporte

    Desarrollador / Mantenedor: Eduardo (CairoStudio)

    Correo electrónico: eduardo@traviesoworks.com

    Repositorio oficial: https://github.com/ditotravieso-01/traviesoprint

    Reporte de errores: https://github.com/ditotravieso-01/traviesoprint/issues

text
