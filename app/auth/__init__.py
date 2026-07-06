from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from app.services.auth_service import AuthService
from app.models import User
from app import db

auth_bp = Blueprint('auth', __name__, url_prefix='/auth', template_folder='templates')

# ==========================================
# LOGIN / LOGOUT
# ==========================================
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        print("DEBUG: usuario ya autenticado -> redirigiendo a home")
        return redirect(url_for('home.home'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = request.form.get('remember') == 'on'

        print(f"DEBUG: intentando login con {username}")
        user = AuthService.authenticate(username, password)
        print(f"DEBUG: usuario obtenido -> {user}")

        if user and user.is_active:
            login_user(user, remember=remember)
            next_page = request.args.get('next')
            flash(f'Bienvenido {user.username}', 'success')
            print(f"DEBUG: login exitoso, redirigiendo a {next_page or url_for('home.home')}")
            return redirect(next_page or url_for('home.home'))
        else:
            flash('Usuario o contraseña incorrectos, o cuenta desactivada.', 'danger')
            print("DEBUG: login fallido")

    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    username = current_user.username
    logout_user()
    flash(f'Sesión cerrada correctamente. Hasta luego, {username}.', 'success')
    return redirect(url_for('auth.login'))

# ==========================================
# ADMINISTRACIÓN DE USUARIOS (solo admin)
# ==========================================
@auth_bp.route('/admin/users')
@login_required
def admin_users():
    if current_user.role != 'admin':
        flash('No tienes permiso para acceder a esta página.', 'danger')
        return redirect(url_for('home.home'))
    users = User.query.order_by(User.username).all()
    return render_template('admin/users.html', users=users)

@auth_bp.route('/admin/user/<int:user_id>/role', methods=['POST'])
@login_required
def admin_change_role(user_id):
    if current_user.role != 'admin':
        flash('No tienes permiso.', 'danger')
        return redirect(url_for('home.home'))
    user = User.query.get_or_404(user_id)
    new_role = request.form.get('role')
    if new_role in ['admin', 'operario', 'disenador', 'comercial']:
        user.role = new_role
        db.session.commit()
        flash(f'Rol de {user.username} actualizado a {new_role}.', 'success')
    else:
        flash('Rol no válido.', 'danger')
    return redirect(url_for('auth.admin_users'))

@auth_bp.route('/admin/user/<int:user_id>/toggle', methods=['POST'])
@login_required
def admin_toggle_user(user_id):
    if current_user.role != 'admin':
        flash('No tienes permiso.', 'danger')
        return redirect(url_for('home.home'))
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('No puedes desactivarte a ti mismo.', 'warning')
    else:
        user.is_active = not user.is_active
        db.session.commit()
        flash(f'Usuario {user.username} {"activado" if user.is_active else "desactivado"}.', 'success')
    return redirect(url_for('auth.admin_users'))

# ==========================================
# PERFIL DE USUARIO
# ==========================================
@auth_bp.route('/profile')
@login_required
def profile():
    return render_template('profile.html')

# ==========================================
# CAMBIAR CONTRASEÑA (solo usuarios locales)
# ==========================================
@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if current_user.is_ldap_user():
        flash('Tu cuenta está gestionada por Active Directory. No puedes cambiar la contraseña aquí.', 'info')
        return redirect(url_for('auth.profile'))

    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if not current_user.check_password(current_password):
            flash('Contraseña actual incorrecta.', 'danger')
            return render_template('change_password.html')

        if new_password != confirm_password:
            flash('Las contraseñas no coinciden.', 'danger')
            return render_template('change_password.html')

        if len(new_password) < 6:
            flash('La contraseña debe tener al menos 6 caracteres.', 'danger')
            return render_template('change_password.html')

        current_user.set_password(new_password)
        db.session.commit()
        flash('Contraseña actualizada correctamente.', 'success')
        return redirect(url_for('auth.profile'))

    return render_template('change_password.html')

# ==========================================
# RESETEAR CONTRASEÑA DE OTRO USUARIO (solo admin)
# ==========================================
@auth_bp.route('/admin/user/<int:user_id>/reset-password', methods=['GET', 'POST'])
@login_required
def admin_reset_password(user_id):
    if current_user.role != 'admin':
        flash('No tienes permiso.', 'danger')
        return redirect(url_for('home.home'))

    user = User.query.get_or_404(user_id)
    if user.is_ldap_user():
        flash('No se puede resetear la contraseña de un usuario LDAP.', 'warning')
        return redirect(url_for('auth.admin_users'))

    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if new_password != confirm_password:
            flash('Las contraseñas no coinciden.', 'danger')
            return render_template('admin/reset_password.html', user=user)

        if len(new_password) < 6:
            flash('La contraseña debe tener al menos 6 caracteres.', 'danger')
            return render_template('admin/reset_password.html', user=user)

        user.set_password(new_password)
        db.session.commit()
        flash(f'Contraseña de {user.username} reseteada correctamente.', 'success')
        return redirect(url_for('auth.admin_users'))

    return render_template('admin/reset_password.html', user=user)

# ==========================================
# CREAR USUARIO LOCAL (solo admin)
# ==========================================
@auth_bp.route('/admin/create-user', methods=['POST'])
@login_required
def admin_create_user():
    if current_user.role != 'admin':
        flash('No tienes permiso.', 'danger')
        return redirect(url_for('home.home'))

    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    role = request.form.get('role', 'operario')

    if not username or not password:
        flash('Usuario y contraseña son obligatorios.', 'danger')
        return redirect(url_for('auth.admin_users'))

    if len(password) < 6:
        flash('La contraseña debe tener al menos 6 caracteres.', 'danger')
        return redirect(url_for('auth.admin_users'))

    if User.query.filter_by(username=username).first():
        flash('El usuario ya existe.', 'danger')
        return redirect(url_for('auth.admin_users'))

    # Crear usuario local
    user = User(username=username, email=email or None, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    flash(f'Usuario local {username} creado correctamente.', 'success')
    return redirect(url_for('auth.admin_users'))

# ==========================================
# ELIMINAR USUARIO LOCAL (solo admin)
# ==========================================
@auth_bp.route('/admin/user/<int:user_id>/delete', methods=['POST'])
@login_required
def admin_delete_user(user_id):
    if current_user.role != 'admin':
        flash('No tienes permiso.', 'danger')
        return redirect(url_for('home.home'))

    user = User.query.get_or_404(user_id)

    # No permitir eliminar usuarios LDAP
    if user.is_ldap_user():
        flash('No se puede eliminar un usuario LDAP.', 'warning')
        return redirect(url_for('auth.admin_users'))

    # No permitir eliminar al propio admin
    if user.id == current_user.id:
        flash('No puedes eliminarte a ti mismo.', 'warning')
        return redirect(url_for('auth.admin_users'))

    # Eliminar usuario
    db.session.delete(user)
    db.session.commit()
    flash(f'Usuario {user.username} eliminado correctamente.', 'success')
    return redirect(url_for('auth.admin_users'))

@auth_bp.route('/update-profile', methods=['POST'])
@login_required
def update_profile():
    if current_user.is_ldap_user():
        flash('No puedes modificar el email de un usuario LDAP.', 'warning')
        return redirect(url_for('auth.profile'))

    email = request.form.get('email')
    if email:
        # Verificar que el email no esté en uso por otro usuario
        existing = User.query.filter(User.email == email, User.id != current_user.id).first()
        if existing:
            flash('El email ya está en uso por otro usuario.', 'danger')
            return redirect(url_for('auth.profile'))
        current_user.email = email
        db.session.commit()
        flash('Email actualizado correctamente.', 'success')
    else:
        flash('El email no puede estar vacío.', 'danger')
    return redirect(url_for('auth.profile'))

@auth_bp.route('/admin/user/<int:user_id>/update-email', methods=['POST'])
@login_required
def admin_update_email(user_id):
    if current_user.role != 'admin':
        flash('No tienes permiso.', 'danger')
        return redirect(url_for('auth.admin_users'))

    user = User.query.get_or_404(user_id)
    if user.is_ldap_user():
        flash('No se puede modificar el email de un usuario LDAP.', 'warning')
        return redirect(url_for('auth.admin_users'))

    email = request.form.get('email')
    if email:
        # Verificar que no esté en uso
        existing = User.query.filter(User.email == email, User.id != user.id).first()
        if existing:
            flash('El email ya está en uso por otro usuario.', 'danger')
            return redirect(url_for('auth.admin_users'))
        user.email = email
        db.session.commit()
        flash(f'Email de {user.username} actualizado.', 'success')
    else:
        flash('El email no puede estar vacío.', 'danger')
    return redirect(url_for('auth.admin_users'))