from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from .config import Config

# Instancia global de SQLAlchemy
db = SQLAlchemy()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Inicializar SQLAlchemy con la app
    db.init_app(app)

    # Importar los modelos para que SQLAlchemy los conozca
    from . import models

    # Crear las tablas en la base de datos (si no existen)
    with app.app_context():
        db.create_all()
        # Crear un usuario administrador por defecto si no existe
        admin_user = models.User.query.filter_by(username='admin').first()
        if not admin_user:
            admin = models.User(username='admin')
            admin.set_password('admin')  # Contraseña: admin
            db.session.add(admin)
            db.session.commit()
            print("✅ Usuario 'admin' creado con contraseña 'admin'")

    # Registrar los blueprints
    from .auth import auth_bp
    from .home import home_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(home_bp)  # La raíz '/' la maneja home_bp

    return app