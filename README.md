# Cairostudiokit

Herramientas internas de **CairoStudio**, desarrolladas por TraviesoWorks.

## 🧰 Calculadoras incluidas

- **Calculadora de Etiquetas** – distribución en rollo de 1.30 m, marcas de corte, margen de mesa.
- **Calculadora de Lona / Merma** – cálculo de impresión y desperdicio lateral para vinilo, lona, lienzo, etc.
- **Portal** – punto de entrada común con acceso a ambas herramientas.

## 🚀 Despliegue rápido (LXC Ubuntu)

1. Clonar el repositorio:  
   `git clone https://github.com/ditotravieso-01/cairostudiokit.git /opt/cairostudiokit`
2. Ejecutar el script de instalación:  
   `cd /opt/cairostudiokit && sudo bash setup.sh`
3. Acceder al portal: `http://<IP-DEL-LXC>/`

Las actualizaciones se aplican automáticamente cada minuto mediante `cron` + `deploy.sh`.

## 📁 Estructura
