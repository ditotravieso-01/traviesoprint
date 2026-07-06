from flask import Blueprint, render_template

clientes_bp = Blueprint('clientes', __name__, url_prefix='/clientes', template_folder='templates')

@clientes_bp.route('/')
def list_clients():
    return render_template('list_clientes.html')  # Cambiamos el nombre de la plantilla