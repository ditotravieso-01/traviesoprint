import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app.models import Configuracion, db

admin_bp = Blueprint('admin', __name__, url_prefix='/admin', template_folder='templates')

def admin_required(func):
    from functools import wraps
    @wraps(func)
    def decorated_view(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('Acceso denegado. Se requieren permisos de administrador.', 'danger')
            return redirect(url_for('home.index'))
        return func(*args, **kwargs)
    return decorated_view

@admin_bp.route('/configuracion', methods=['GET', 'POST'])
@login_required
@admin_required
def configuracion():
    if request.method == 'POST':
        nombre = request.form.get('empresa_nombre', '').strip()
        subtitulo = request.form.get('empresa_subtitulo', '').strip()
        color_primario = request.form.get('color_primario', '').strip()
        color_secundario = request.form.get('color_secundario', '').strip()

        if nombre:
            Configuracion.set_config('empresa_nombre', nombre)
        if subtitulo:
            Configuracion.set_config('empresa_subtitulo', subtitulo)
        if color_primario:
            Configuracion.set_config('color_primario', color_primario)
        if color_secundario:
            Configuracion.set_config('color_secundario', color_secundario)

        # Logo
        if 'logo' in request.files:
            file = request.files['logo']
            if file and file.filename:
                logo_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'logo.png')
                file.save(logo_path)
                Configuracion.set_config('logo_url', 'uploads/logo.png')
                flash('Logo actualizado correctamente.', 'success')

        # Fondo login
        if 'login_bg' in request.files:
            file = request.files['login_bg']
            if file and file.filename:
                bg_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'login_bg.jpg')
                file.save(bg_path)
                Configuracion.set_config('login_bg_url', 'uploads/login_bg.jpg')
                flash('Fondo de login actualizado correctamente.', 'success')

        # Favicon
        if 'favicon' in request.files:
            file = request.files['favicon']
            if file and file.filename:
                ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'ico'
                favicon_path = os.path.join(current_app.config['UPLOAD_FOLDER'], f'favicon.{ext}')
                file.save(favicon_path)
                Configuracion.set_config('favicon_url', f'uploads/favicon.{ext}')
                flash('Favicon actualizado correctamente.', 'success')

        flash('Configuración actualizada correctamente.', 'success')
        return redirect(url_for('admin.configuracion'))

    # GET
    empresa_nombre = Configuracion.get_config('empresa_nombre', 'TraviesoPrint')
    empresa_subtitulo = Configuracion.get_config('empresa_subtitulo', 'Gestión para talleres de impresión')
    logo_url = Configuracion.get_config('logo_url', 'img/logo_default.png')
    login_bg_url = Configuracion.get_config('login_bg_url', 'img/login_bg_default.jpg')
    favicon_url = Configuracion.get_config('favicon_url', 'img/favicon_default.ico')
    color_primario = Configuracion.get_config('color_primario', '#1c1c1e')
    color_secundario = Configuracion.get_config('color_secundario', '#a8854f')

    return render_template('admin/configuracion.html',
                           empresa_nombre=empresa_nombre,
                           empresa_subtitulo=empresa_subtitulo,
                           logo_url=logo_url,
                           login_bg_url=login_bg_url,
                           favicon_url=favicon_url,
                           color_primario=color_primario,
                           color_secundario=color_secundario)