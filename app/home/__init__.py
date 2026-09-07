from flask import Blueprint, redirect, url_for
from flask_login import login_required

home_bp = Blueprint('home', __name__, url_prefix='')

@home_bp.route('/')
@login_required
def index():
    """Redirige a la raíz del dashboard."""
    return redirect(url_for('dashboard.index'))