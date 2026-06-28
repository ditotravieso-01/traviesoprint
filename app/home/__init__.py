from flask import Blueprint, render_template, session, redirect, url_for

home_bp = Blueprint('home', __name__, template_folder='templates')

@home_bp.route('/')
def home():
    # Si no hay sesión activa, redirigir al login
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    # Pasamos el nombre de usuario a la plantilla para mostrarlo
    return render_template('home.html', username=session.get('username'))