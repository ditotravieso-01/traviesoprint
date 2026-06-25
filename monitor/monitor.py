#!/usr/bin/env python3
import subprocess
import time
import requests
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/opt/cairokit/monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

SERVICES = {
    'calculadora': {'port': 5000, 'service': 'calculadora.service'},
    'lona': {'port': 5001, 'service': 'lona-calculadora.service'},
}

CHECK_INTERVAL = 60
TIMEOUT = 5
MAX_RETRIES = 2

def check_service(name, config):
    url = f"http://127.0.0.1:{config['port']}/"
    retries = 0
    while retries <= MAX_RETRIES:
        try:
            response = requests.get(url, timeout=TIMEOUT)
            if response.status_code == 200:
                return True
            logger.warning(f"{name}: status {response.status_code}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"{name}: intento {retries+1} - {e}")
        retries += 1
        if retries <= MAX_RETRIES:
            time.sleep(2)
    logger.error(f"{name}: no responde tras {MAX_RETRIES+1} intentos")
    return False

def restart_service(service_name):
    try:
        logger.info(f"Reiniciando {service_name}...")
        subprocess.run(['sudo', 'systemctl', 'restart', service_name], check=True)
        logger.info(f"{service_name} reiniciado con éxito")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Error al reiniciar {service_name}: {e}")
        return False

def main():
    logger.info("Monitor de calculadoras iniciado")
    while True:
        for name, config in SERVICES.items():
            if not check_service(name, config):
                restart_service(config['service'])
        time.sleep(CHECK_INTERVAL)

if __name__ == '__main__':
    main()