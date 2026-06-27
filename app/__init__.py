from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from .config import Config

# Creamos el objeto SQLAlchemy a nivel global (para usarlo en models.py)
db = SQLAlchemy()

def create_app():
    # Creamos la instancia de Flask
    app = Flask(__name__)
    
    # Cargamos la configuración desde config.py
    app.config.from_object(Config)
    
    # Inicializamos la base de datos con la app
    db.init_app(app)
    
    # Por ahora, dejamos un mensaje en la raíz para probar que funciona
    @app.route('/')
    def index():
        return "¡La nueva estructura de Cairostudiokit está viva! Diseño en construcción..."
    
    # 🔥 AQUÍ REGISTRAREMOS LOS BLUEPRINTS/MÓDULOS MÁS ADELANTE
    # from .auth import auth_bp
    # app.register_blueprint(auth_bp, url_prefix='/auth')
    
    return app