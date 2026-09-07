import os

# Ruta absoluta donde está este archivo (app/)
basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    # Clave secreta para sesiones y cookies (cámbiala en producción)
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-super-secret-key-traviesoprint'
    
    # Base de datos SQLite dentro de la carpeta app/
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(basedir, 'traviesoprint.db')
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ===== CONFIGURACIÓN LDAP =====
    LDAP_ENABLED = os.environ.get('LDAP_ENABLED', 'False') == 'True'
    LDAP_SERVER = os.environ.get('LDAP_SERVER', 'dc.traviesoprint.cu')
    LDAP_BASE_DN = os.environ.get('LDAP_BASE_DN', 'dc=traviesoprint,dc=cu')
    LDAP_DOMAIN = os.environ.get('LDAP_DOMAIN', 'traviesoprint.cu')

    # ===== VERSIÓN DE LA APLICACIÓN (FIJA) =====
    VERSION = 'v1.0 - TraviesoPrint'