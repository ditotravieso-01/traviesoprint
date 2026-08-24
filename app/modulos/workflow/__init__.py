from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from app.models import Order, User, Client
from app import db
from datetime import datetime, timedelta
from app.services.notification_service import notificar_usuarios

workflow_bp = Blueprint('workflow', __name__, url_prefix='/workflow', template_folder='templates')

# ============================================================
# COLUMNAS Y PERMISOS (actualizados con 'produccion')
# ============================================================
COLUMNAS = [
    {'id': 'pendiente', 'icono': 'fa-clock', 'nombre': 'Pendiente'},
    {'id': 'por-preparar', 'icono': 'fa-tools', 'nombre': 'Por preparar'},
    {'id': 'preparados', 'icono': 'fa-check-circle', 'nombre': 'Preparados'},
    {'id': 'imprimir-hoy', 'icono': 'fa-print', 'nombre': 'Imprimir hoy'},
    {'id': 'impreso-corte', 'icono': 'fa-cut', 'nombre': 'Impreso y corte'},
    {'id': 'produccion', 'icono': 'fa-industry', 'nombre': 'Producción'},
    {'id': 'listo', 'icono': 'fa-box', 'nombre': 'Listo'},
    {'id': 'entregados', 'icono': 'fa-truck', 'nombre': 'Entregados'}
]

# Definición de rutas (para validación)
RUTAS = {
    'impresion': ['pendiente', 'por-preparar', 'preparados', 'imprimir-hoy', 'impreso-corte', 'produccion', 'listo', 'entregados'],
    'produccion': ['pendiente', 'por-preparar', 'preparados', 'produccion', 'listo', 'entregados']
}

# Permisos para mover (incluyendo 'produccion')
PERMISOS_MOVER = {
    'comercial': ['pendiente', 'preparados', 'listo'],
    'disennador': ['por-preparar'],
    'diseñador': ['por-preparar'],
    'disenador': ['por-preparar'],
    'operario': ['preparados', 'imprimir-hoy', 'impreso-corte', 'produccion'],
    'odalys': ['pendiente', 'por-preparar', 'preparados', 'imprimir-hoy', 'impreso-corte', 'produccion', 'listo'],
    'admin': ['pendiente', 'por-preparar', 'preparados', 'imprimir-hoy', 'impreso-corte', 'produccion', 'listo', 'entregados']
}

def obtener_permisos_mover(rol):
    if rol in PERMISOS_MOVER:
        return PERMISOS_MOVER[rol]
    rol_lower = rol.lower().replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u')
    if 'disen' in rol_lower:
        return PERMISOS_MOVER.get('disennador', [])
    return []

def _order_to_dict(order):
    """Convierte una orden a diccionario para el frontend, incluyendo 'ruta'."""
    return {
        'id': order.id,
        'order_num': order.order_num,
        'client': {
            'id': order.client.id if order.client else None,
            'nombre': order.client.nombre if order.client else 'Sin cliente'
        } if order.client else None,
        'priority': order.priority,
        'column': order.column,
        'ruta': getattr(order, 'ruta', 'impresion'),
        'entrada_ok': order.entrada_ok,
        'fecha_entregado': order.fecha_entregado.isoformat() if order.fecha_entregado else None,
        'created_at': order.created_at.isoformat() if order.created_at else None,
        'proyecto': order.proyecto,
        'descripcion': order.descripcion,
        'servicios': order.get_servicios() if hasattr(order, 'get_servicios') else [],
        'historial': order.get_history() if hasattr(order, 'get_history') else []
    }

# ============================================================
# RUTA PRINCIPAL (tablero)
# ============================================================
@workflow_bp.route('/')
@login_required
def board():
    orders = Order.query.all()
    orders_dict = [_order_to_dict(o) for o in orders]

    columnas = {col['id']: [] for col in COLUMNAS}
    for o in orders_dict:
        col = o['column'] if o['column'] in columnas else 'pendiente'
        columnas[col].append(o)

    ahora = datetime.now()
    usuarios = User.query.filter_by(is_active=True).order_by(User.username).all()
    puede_cambiar_prioridad = current_user.role in ['admin', 'comercial', 'odalys']
    columnas_permitidas = obtener_permisos_mover(current_user.role)
    puede_eliminar = current_user.role in ['comercial', 'admin']

    total_activas = sum(1 for o in orders_dict if o['column'] != 'entregados')
    total_entregadas = sum(1 for o in orders_dict if o['column'] == 'entregados')
    pendientes = sum(1 for o in orders_dict if o['column'] in ['pendiente', 'por-preparar'])
    en_proceso = sum(1 for o in orders_dict if o['column'] in ['preparados', 'imprimir-hoy', 'impreso-corte', 'produccion'])
    listas = sum(1 for o in orders_dict if o['column'] == 'listo')

    chart_labels = [col['nombre'] for col in COLUMNAS]
    chart_data = [len(columnas[col['id']]) for col in COLUMNAS]

    return render_template('board.html',
                           columnas=columnas,
                           columnas_info=COLUMNAS,
                           usuarios=usuarios,
                           ahora=ahora,
                           puede_cambiar_prioridad=puede_cambiar_prioridad,
                           columnas_permitidas=columnas_permitidas,
                           puede_eliminar=puede_eliminar,
                           total_activas=total_activas,
                           total_entregadas=total_entregadas,
                           pendientes=pendientes,
                           en_proceso=en_proceso,
                           listas=listas,
                           chart_labels=chart_labels,
                           chart_data=chart_data)

# ============================================================
# MOVER ORDEN (con validación de ruta)
# ============================================================
@workflow_bp.route('/mover/<int:order_id>', methods=['POST'])
@login_required
def mover_ajax(order_id):
    try:
        data = request.get_json(force=True)
        print(f"📦 [AJAX] Datos recibidos: {data}")
    except Exception as e:
        print(f"❌ Error parsing JSON: {e}")
        return jsonify({'error': 'Formato JSON inválido'}), 400

    nueva_columna = data.get('columna') if data else None
    if not nueva_columna:
        return jsonify({'error': 'Falta el campo "columna"'}), 400

    order = Order.query.get_or_404(order_id)
    columnas_validas = [c['id'] for c in COLUMNAS]
    if nueva_columna not in columnas_validas:
        return jsonify({'error': 'Columna inválida'}), 400

    columnas_permitidas = obtener_permisos_mover(current_user.role)
    print(f"🔍 Orden {order.order_num} (ID: {order_id}) está en columna: '{order.column}'")
    print(f"   Permisos del usuario: {columnas_permitidas}")

    if order.column not in columnas_permitidas:
        return jsonify({
            'error': f'No tienes permiso para mover desde "{order.column}". Solo puedes mover desde: {", ".join(columnas_permitidas)}'
        }), 403

    ruta_orden = getattr(order, 'ruta', 'impresion')
    if ruta_orden not in RUTAS:
        ruta_orden = 'impresion'
    if nueva_columna not in RUTAS[ruta_orden]:
        return jsonify({
            'error': f'❌ La orden tiene ruta "{ruta_orden}" y no permite mover a "{nueva_columna}".\n'
                     f'Ruta permitida: {" → ".join(RUTAS[ruta_orden])}'
        }), 400

    if not order.entrada_ok and nueva_columna != 'pendiente':
        return jsonify({
            'error': '⚠️ Esta orden no tiene entrada al sistema. Debes marcarla como "Entrada" primero.\n\n'
                     'Por favor, ve a la lista de órdenes y asígnale el número de Odoo para poder avanzarla en el flujo de trabajo.'
        }), 400

    if nueva_columna == 'impreso-corte' and order.entrada_ok:
        from app.modulos.ordenes import consumir_materiales
        success, msg = consumir_materiales(order.id)
        if not success:
            return jsonify({'error': f'Error al consumir materiales: {msg}'}), 400

    order.column = nueva_columna
    if nueva_columna == 'entregados':
        order.fecha_entregado = datetime.now()
    else:
        order.fecha_entregado = None

    order.add_history({
        'mensaje': f'Movida a {nueva_columna}',
        'columna': nueva_columna,
        'usuario': current_user.username,
        'fecha': datetime.now().isoformat()
    })
    db.session.commit()

    usuarios = User.query.filter(User.is_active == True, User.id != current_user.id).all()
    if usuarios:
        mensaje = f"Orden {order.order_num} movida a '{nueva_columna}' por {current_user.username}"
        enlace = url_for('workflow.board', _external=True)
        notificar_usuarios([u.id for u in usuarios], mensaje, 'orden_movida', order.id, enlace)

    return jsonify({'success': True, 'mensaje': f'Movida a {nueva_columna}'})

# ============================================================
# CAMBIAR RUTA
# ============================================================
@workflow_bp.route('/cambiar-ruta/<int:order_id>', methods=['POST'])
@login_required
def cambiar_ruta(order_id):
    if current_user.role not in ['admin', 'comercial', 'odalys']:
        return jsonify({'error': 'No tienes permiso'}), 403

    data = request.get_json()
    nueva_ruta = data.get('ruta')
    if nueva_ruta not in RUTAS:
        return jsonify({'error': 'Ruta inválida'}), 400

    order = Order.query.get_or_404(order_id)
    order.ruta = nueva_ruta
    if order.column not in RUTAS[nueva_ruta]:
        order.column = RUTAS[nueva_ruta][0]
    order.add_history(f'Ruta cambiada a {nueva_ruta} por {current_user.username}')
    db.session.commit()
    return jsonify({'success': True, 'mensaje': f'Ruta cambiada a {nueva_ruta}'})

# ============================================================
# ELIMINAR ORDEN
# ============================================================
@workflow_bp.route('/eliminar/<int:order_id>', methods=['POST'])
@login_required
def eliminar_orden(order_id):
    order = Order.query.get_or_404(order_id)

    if current_user.role not in ['comercial', 'admin']:
        return jsonify({'error': 'No autorizado'}), 403

    if order.column == 'entregados' and current_user.role != 'admin':
        return jsonify({'error': 'Solo administradores pueden eliminar órdenes entregadas'}), 403

    db.session.delete(order)
    db.session.commit()
    return jsonify({'success': True})

# ============================================================
# OBTENER COLUMNA
# ============================================================
@workflow_bp.route('/columna/<columna_id>')
@login_required
def obtener_columna(columna_id):
    if columna_id not in [c['id'] for c in COLUMNAS]:
        return jsonify({'error': 'Columna inválida'}), 400

    query = Order.query.filter_by(column=columna_id)
    orders = query.all()
    data = [{
        'id': o.id,
        'num': o.order_num,
        'cliente': o.client.nombre if o.client else 'Sin cliente',
        'prioridad': o.priority,
        'fecha_entregado': o.fecha_entregado.strftime('%d/%m/%Y %H:%M') if o.fecha_entregado else None
    } for o in orders]

    return jsonify(data)

# ============================================================
# DATOS PARA DASHBOARD (POLLING)
# ============================================================
@workflow_bp.route('/dashboard-data')
@login_required
def dashboard_data():
    """Devuelve datos en JSON para actualizar el dashboard en tiempo real."""
    orders = Order.query.all()
    orders_dict = [_order_to_dict(o) for o in orders]

    column_counts = {col['id']: 0 for col in COLUMNAS}
    for o in orders_dict:
        col = o['column'] if o['column'] in column_counts else 'pendiente'
        column_counts[col] += 1

    total_activas = sum(1 for o in orders_dict if o['column'] != 'entregados')
    total_entregadas = sum(1 for o in orders_dict if o['column'] == 'entregados')
    pendientes = sum(1 for o in orders_dict if o['column'] in ['pendiente', 'por-preparar'])
    en_proceso = sum(1 for o in orders_dict if o['column'] in ['preparados', 'imprimir-hoy', 'impreso-corte', 'produccion'])
    listas = sum(1 for o in orders_dict if o['column'] == 'listo')

    chart_labels = [col['nombre'] for col in COLUMNAS]
    chart_data = [column_counts[col['id']] for col in COLUMNAS]

    return jsonify({
        'column_counts': column_counts,
        'total_activas': total_activas,
        'total_entregadas': total_entregadas,
        'pendientes': pendientes,
        'en_proceso': en_proceso,
        'listas': listas,
        'chart_labels': chart_labels,
        'chart_data': chart_data
    })