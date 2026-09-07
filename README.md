# TraviesoPrint - Gestión para talleres de impresión

**TraviesoPrint** es una plataforma web para gestionar talleres de impresión y estudios creativos. Permite administrar órdenes, inventario híbrido (unidades y metros), workflow Kanban, clientes, empleados, calendario, generación de etiquetas y más.

**Versión actual:** v1.0

---

## Instalación en servidor (Ubuntu 24.04 LTS)

### Requisitos mínimos

- Ubuntu 24.04 LTS (o Debian 12+)
- 2 GB RAM (recomendado 4 GB)
- 20 GB de disco
- IP pública o dominio
- Conexión a Internet

### Instalación automática (recomendada)

Ejecuta estos comandos como **root**:

```bash
# 1. Descargar el script de instalación
wget -O install.sh https://raw.githubusercontent.com/ditotravieso-01/cairostudiokit/main/install.sh

# 2. Dar permisos y ejecutar
chmod +x install.sh
sudo ./install.sh