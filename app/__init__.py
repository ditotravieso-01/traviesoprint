import os
from flask import Flask, redirect, url_for, request, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
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
        # Inicializar configuración si está vacía
        from .models import init_configuracion, Configuracion
        if not Configuracion.query.first():
            init_configuracion()
            print('✅ Configuración inicial creada.')

        # Inicializar permisos por defecto si no existen
        from .models import Permiso
        if not Permiso.query.first():
            Permiso.init_default_permissions()
            print('✅ Permisos por defecto creados.')

        # Crear usuario admin solo si ya está instalado
        instalado = Configuracion.get_config('instalacion_completada', 'false') == 'true'
        if instalado:
            from .services.auth_service import AuthService
            admin = models.User.query.filter_by(username='admin').first()
            if not admin:
                AuthService.create_local_admin('admin', 'admin')
                print('✅ Usuario admin creado por defecto (admin/admin)')

    # Registrar blueprints
    from app.modulos.dashboard import dashboard_bp
    app.register_blueprint(dashboard_bp, url_prefix='/dashboard')
    
    from .auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from .home import home_bp
    app.register_blueprint(home_bp)

    from .modulos.clientes import clientes_bp
    app.register_blueprint(clientes_bp)

    from .modulos.ordenes import ordenes_bp
    app.register_blueprint(ordenes_bp)

    from .modulos.workflow import workflow_bp
    app.register_blueprint(workflow_bp)

    from .modulos.etiquetas import etiquetas_bp
    app.register_blueprint(etiquetas_bp)

    from .modulos.carteles import carteles_bp
    app.register_blueprint(carteles_bp)

    from .modulos.notificaciones import notificaciones_bp
    app.register_blueprint(notificaciones_bp)

    from .modulos.inventario import inventario_bp
    app.register_blueprint(inventario_bp)

    from app.modulos.empleados import empleados_bp
    app.register_blueprint(empleados_bp)

    # ===== Blueprint de administración =====
    from app.modulos.admin import admin_bp
    app.register_blueprint(admin_bp, url_prefix='/admin')

    # ===== Blueprint de setup =====
    from app.modulos.setup import setup_bp
    app.register_blueprint(setup_bp, url_prefix='/setup')

    # ===== Blueprint de calendario =====
    from app.modulos.calendario import calendario_bp
    app.register_blueprint(calendario_bp)

    # ===== CONTEXTO GLOBAL =====
    @app.context_processor
    def inject_config():
        from .models import Configuracion
        empresa_nombre = Configuracion.get_config('empresa_nombre', 'TraviesoPrint')
        empresa_subtitulo = Configuracion.get_config('empresa_subtitulo', 'Gestión para talleres de impresión')
        logo_url = Configuracion.get_config('logo_url', 'img/logo_default.png')
        login_bg_url = Configuracion.get_config('login_bg_url', 'img/login_bg_default.jpg')
        favicon_url = Configuracion.get_config('favicon_url', 'img/favicon_default.ico')
        color_primario = Configuracion.get_config('color_primario', '#1c1c1e')
        color_secundario = Configuracion.get_config('color_secundario', '#a8854f')
        version = app.config.get('VERSION', 'v1.0 - TraviesoPrint')
        
        # Función auxiliar para permisos
        def has_perm(module, perm='view'):
            if not current_user or not current_user.is_authenticated:
                return False
            if current_user.role == 'admin':
                return True
            from .models import Permiso
            return Permiso.has_permission(current_user.role, module, perm)
        
        return {
            'empresa_nombre': empresa_nombre,
            'empresa_subtitulo': empresa_subtitulo,
            'logo_url': logo_url,
            'login_bg_url': login_bg_url,
            'favicon_url': favicon_url,
            'version': version,
            'color_primario': color_primario,
            'color_secundario': color_secundario,
            'has_perm': has_perm,
        }

    # ===== DETECCIÓN DE INSTALACIÓN (CORREGIDO) =====
    @app.before_request
    def check_setup():
        # Excluir SOLO rutas de setup y archivos estáticos
        if request.endpoint and (
            request.endpoint.startswith('setup.') or
            request.endpoint == 'static'
        ):
            return
        
        # Para TODAS las demás rutas (incluyendo auth), verificar instalación
        from .models import Configuracion
        instalado = Configuracion.get_config('instalacion_completada', 'false') == 'true'
        if not instalado:
            return redirect(url_for('setup.paso1'))

    return app