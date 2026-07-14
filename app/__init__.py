import os  # <--- AGREGAR ESTA LÍNEA
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from .config import Config

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Por favor, inicia sesión para acceder.'
login_manager.login_message_category = 'warning'

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Configuración de carpeta de subida
    app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    # Importar modelos
    from . import models

    with app.app_context():
        db.create_all()
        from .services.auth_service import AuthService
        admin = models.User.query.filter_by(username='admin').first()
        if not admin:
            AuthService.create_local_admin('admin', 'admin')
            print('✅ Usuario admin creado por defecto (admin/admin)')

    # Registrar blueprints
    from .auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from .home import home_bp
    app.register_blueprint(home_bp)

    from .modulos.clientes import clientes_bp
    app.register_blueprint(clientes_bp)

    from .modulos.etiquetas import etiquetas_bp
    app.register_blueprint(etiquetas_bp)

    from .modulos.carteles import carteles_bp
    app.register_blueprint(carteles_bp)

    from .modulos.ordenes import ordenes_bp
    app.register_blueprint(ordenes_bp)

    return app