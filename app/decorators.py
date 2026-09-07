from functools import wraps
from flask import flash, redirect, url_for
from flask_login import current_user
from app.models import Permiso

def permission_required(module, perm='view'):
    """Decorador para verificar permisos en rutas."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Debes iniciar sesión.', 'warning')
                return redirect(url_for('auth.login'))
            if current_user.role == 'admin':
                return f(*args, **kwargs)
            if not Permiso.has_permission(current_user.role, module, perm):
                flash('No tienes permiso para acceder a esta sección.', 'danger')
                return redirect(url_for('home.index'))
            return f(*args, **kwargs)
        return decorated
    return decorator