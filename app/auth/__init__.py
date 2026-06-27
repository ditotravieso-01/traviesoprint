from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from ..models import User
from .. import db

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Si el usuario ya está logueado, lo enviamos al home
    if 'user_id' in session:
        return redirect(url_for('home.home'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        # Buscar el usuario en la base de datos
        user = User.query.filter_by(username=username).first()

        # Verificar credenciales
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            return redirect(url_for('home.home'))
        else:
            flash('Usuario o contraseña incorrectos. Prueba con admin/admin.')

    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))