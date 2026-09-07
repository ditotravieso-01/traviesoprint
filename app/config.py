import os

class Config:
    # Clave secreta (leer de entorno o usar valor por defecto)
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    
    # Base de datos
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///' + os.path.join(
        os.path.abspath(os.path.dirname(__file__)), '..', 'instance', 'traviesoprint.db'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Directorio de subidas
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
    
    # Modo debug (forzar False en producción)
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() in ('false', '0', 'f')
    
    # Versión de la aplicación (se muestra en el pie de página)
    VERSION = 'v1.0 - TraviesoPrint'