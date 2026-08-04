from flask import Blueprint, render_template
from flask_login import login_required, current_user
from app.models import Producto

inventario_bp = Blueprint('inventario', __name__, url_prefix='/inventario', template_folder='templates')

# Decorador para roles permitidos
def economico_or_admin_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if current_user.role not in ['admin', 'economico']:
            flash('No tienes permiso para acceder al inventario.', 'danger')
            return redirect(url_for('home.home'))
        return func(*args, **kwargs)
    return wrapper

@inventario_bp.route('/')
@login_required
@economico_or_admin_required
def index():
    # Vista básica: listar productos (si existen) o un mensaje de "en construcción"
    productos = Producto.query.all()
    return render_template('inventario.html', productos=productos)