import os


class Config:
    # ===== Básico =====
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'

    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///' + os.path.join(
        os.path.abspath(os.path.dirname(__file__)), '..', 'instance', 'traviesoprint.db'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')

    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() in ('false', '0', 'f')

    VERSION = 'v1.0 - TraviesoPrint'

    # ===== LDAP / Active Directory =====
    LDAP_ENABLED = os.environ.get('LDAP_ENABLED', 'False').lower() in ('true', '1', 't', 'yes')
    LDAP_SERVER = os.environ.get('LDAP_SERVER', 'dc1.cairostudio.cu')
    LDAP_PORT = int(os.environ.get('LDAP_PORT', '636'))
    LDAP_USE_SSL = os.environ.get('LDAP_USE_SSL', 'True').lower() in ('true', '1', 't', 'yes')
    LDAP_BASE_DN = os.environ.get('LDAP_BASE_DN', 'DC=cairostudio,DC=cu')
    LDAP_DOMAIN = os.environ.get('LDAP_DOMAIN', 'cairostudio.cu')
    LDAP_SERVICE_USER = os.environ.get('LDAP_SERVICE_USER', '')
    LDAP_SERVICE_PASSWORD = os.environ.get('LDAP_SERVICE_PASSWORD', '')
    LDAP_TIMEOUT = int(os.environ.get('LDAP_TIMEOUT', '5'))
    LDAP_CA_CERTS = os.environ.get('LDAP_CA_CERTS', '/etc/ssl/certs/ca-certificates.crt')