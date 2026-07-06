from flask import Blueprint

clientes_bp = Blueprint('clientes', __name__, url_prefix='/clientes', template_folder='templates')

@clientes_bp.route('/')
def index():
    return "<h1>Módulo Clientes - Funciona</h1>"
