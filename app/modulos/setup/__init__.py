from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
from app.models import Configuracion, User, db
import os

setup_bp = Blueprint('setup', __name__, url_prefix='/setup', template_folder='templates')

def is_installed():
    return Configuracion.get_config('instalacion_completada', 'false') == 'true'

@setup_bp.before_request
def check_setup():
    if is_installed():
        return redirect(url_for('auth.login'))


# ==========================================
# PASO 1: Datos de la empresa
# ==========================================
@setup_bp.route('/')
@setup_bp.route('/paso1', methods=['GET', 'POST'])
def paso1():
    if is_installed():
        return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        # Guardar en session
        session['setup_empresa'] = {
            'nombre': request.form.get('empresa_nombre', '').strip(),
            'subtitulo': request.form.get('empresa_subtitulo', 'Gestión para talleres de impresión').strip(),
            'color_primario': request.form.get('color_primario', '#1c1c1e').strip(),
            'color_secundario': request.form.get('color_secundario', '#a8854f').strip(),
        }
        
        # Logo
        if 'logo' in request.files:
            file = request.files['logo']
            if file and file.filename:
                filename = secure_filename(file.filename)
                logo_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'logo.png')
                file.save(logo_path)
                session['setup_empresa']['logo_url'] = 'uploads/logo.png'
            else:
                session['setup_empresa']['logo_url'] = 'img/logo_default.png'
        else:
            session['setup_empresa']['logo_url'] = 'img/logo_default.png'
        
        # Fondo de login
        if 'login_bg' in request.files:
            file = request.files['login_bg']
            if file and file.filename:
                bg_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'login_bg.jpg')
                file.save(bg_path)
                session['setup_empresa']['login_bg_url'] = 'uploads/login_bg.jpg'
            else:
                session['setup_empresa']['login_bg_url'] = 'img/login_bg_default.jpg'
        else:
            session['setup_empresa']['login_bg_url'] = 'img/login_bg_default.jpg'
        
        return redirect(url_for('setup.paso2'))
    
    # GET
    return render_template('setup_paso1.html', step=1)


# ==========================================
# PASO 2: Usuario administrador
# ==========================================
@setup_bp.route('/paso2', methods=['GET', 'POST'])
def paso2():
    if is_installed():
        return redirect(url_for('auth.login'))
    
    if 'setup_empresa' not in session:
        return redirect(url_for('setup.paso1'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        
        errors = []
        if len(username) < 3:
            errors.append('El nombre de usuario debe tener al menos 3 caracteres.')
        if User.query.filter_by(username=username).first():
            errors.append('El nombre de usuario ya existe.')
        if email and User.query.filter_by(email=email).first():
            errors.append('El email ya está registrado.')
        if len(password) < 6:
            errors.append('La contraseña debe tener al menos 6 caracteres.')
        if password != confirm:
            errors.append('Las contraseñas no coinciden.')
        
        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('setup_paso2.html', step=2, username=username, email=email)
        
        session['setup_admin'] = {
            'username': username,
            'email': email,
            'password': password
        }
        return redirect(url_for('setup.paso3'))
    
    return render_template('setup_paso2.html', step=2)


# ==========================================
# PASO 3: Resumen y finalización
# ==========================================
@setup_bp.route('/paso3', methods=['GET', 'POST'])
def paso3():
    if is_installed():
        return redirect(url_for('auth.login'))
    
    if 'setup_empresa' not in session or 'setup_admin' not in session:
        return redirect(url_for('setup.paso1'))
    
    if request.method == 'POST':
        empresa = session['setup_empresa']
        admin = session['setup_admin']
        
        # Guardar configuración
        Configuracion.set_config('empresa_nombre', empresa['nombre'])
        Configuracion.set_config('empresa_subtitulo', empresa['subtitulo'])
        Configuracion.set_config('color_primario', empresa['color_primario'])
        Configuracion.set_config('color_secundario', empresa['color_secundario'])
        Configuracion.set_config('logo_url', empresa['logo_url'])
        Configuracion.set_config('login_bg_url', empresa['login_bg_url'])
        
        # Crear usuario admin
        existing = User.query.filter_by(username=admin['username']).first()
        if existing:
            existing.set_password(admin['password'])
            existing.role = 'admin'
            existing.email = admin['email']
        else:
            new_admin = User(
                username=admin['username'],
                email=admin['email'],
                role='admin',
                is_active=True
            )
            new_admin.set_password(admin['password'])
            db.session.add(new_admin)
        db.session.commit()
        
        # Marcar instalación completada
        Configuracion.set_config('instalacion_completada', 'true')
        
        # Limpiar session
        session.pop('setup_empresa', None)
        session.pop('setup_admin', None)
        
        flash('✅ Instalación completada con éxito. Ahora puedes iniciar sesión.', 'success')
        return redirect(url_for('auth.login'))
    
    empresa = session['setup_empresa']
    admin = session['setup_admin']
    return render_template('setup_paso3.html', step=3, empresa=empresa, admin=admin)