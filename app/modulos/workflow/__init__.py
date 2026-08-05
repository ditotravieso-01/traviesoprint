from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from app.models import Order, User, Client
from app import db
from datetime import datetime, timedelta
from app.services.notification_service import notificar_usuarios

workflow_bp = Blueprint('workflow', __name__, url_prefix='/workflow', template_folder='templates')

COLUMNAS = [
    {'id': 'pendiente', 'icono': '📋', 'nombre': 'Pendiente'},
    {'id': 'por-preparar', 'icono': '🔧', 'nombre': 'Por preparar'},
    {'id': 'preparados', 'icono': '✅', 'nombre': 'Preparados'},
    {'id': 'imprimir-hoy', 'icono': '🖨️', 'nombre': 'Imprimir hoy'},
    {'id': 'impreso-corte', 'icono': '✂️', 'nombre': 'Impreso y corte'},
    {'id': 'listo', 'icono': '📦', 'nombre': 'Listo'},
    {'id': 'entregados', 'icono': '🚚', 'nombre': 'Entregados'}
]

PERMISOS_MOVER = {
    'comercial': ['pendiente', 'preparados', 'listo'],
    'disennador': ['por-preparar'],
    'diseñador': ['por-preparar'],
    'disenador': ['por-preparar'],
    'operario': ['preparados', 'imprimir-hoy', 'impreso-corte'],
    'odalys': ['pendiente', 'por-preparar', 'preparados', 'imprimir-hoy', 'impreso-corte', 'listo'],
    'admin': ['pendiente', 'por-preparar', 'preparados', 'imprimir-hoy', 'impreso-corte', 'listo', 'entregados']
}

def obtener_permisos_mover(rol):
    if rol in PERMISOS_MOVER:
        return PERMISOS_MOVER[rol]
    rol_lower = rol.lower().replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u')
    if 'disen' in rol_lower:
        return PERMISOS_MOVER.get('disennador', [])
    return []

def _order_to_dict(order):
    return {
        'id': order.id,
        'order_num': order.order_num,
        'client': {
            'id': order.client.id if order.client else None,
            'nombre': order.client.nombre if order.client else 'Sin cliente'
        } if order.client else None,
        'priority': order.priority,
        'column': order.column,
        'entrada_ok': order.entrada_ok,
        'fecha_entregado': order.fecha_entregado.isoformat() if order.fecha_entregado else None,
        'created_at': order.created_at.isoformat() if order.created_at else None,
        'proyecto': order.proyecto,
        'descripcion': order.descripcion,
        'servicios': order.get_servicios() if hasattr(order, 'get_servicios') else []
    }

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

    print(f"🔍 Usuario: {current_user.username} (rol: {current_user.role})")
    print(f"   Columnas permitidas para mover: {columnas_permitidas}")
    for col_id, tarjetas in columnas.items():
        print(f"   {col_id}: {[o['order_num'] for o in tarjetas]}")

    return render_template('board.html',
                           columnas=columnas,
                           columnas_info=COLUMNAS,
                           usuarios=usuarios,
                           ahora=ahora,
                           puede_cambiar_prioridad=puede_cambiar_prioridad,
                           columnas_permitidas=columnas_permitidas,
                           puede_eliminar=puede_eliminar)

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

    # 1. Verificar permiso de columna
    if order.column not in columnas_permitidas:
        return jsonify({
            'error': f'No tienes permiso para mover desde "{order.column}". Solo puedes mover desde: {", ".join(columnas_permitidas)}'
        }), 403

    # ============================================
    # NUEVA VALIDACIÓN: SOLO ÓRDENES CON ENTRADA AL SISTEMA PUEDEN MOVERSE
    # ============================================
    # Permitir mover a "pendiente" incluso si no tiene entrada (para que se pueda corregir)
    if not order.entrada_ok and nueva_columna != 'pendiente':
        return jsonify({
            'error': '⚠️ Esta orden no tiene entrada al sistema. Debes marcarla como "Entrada" primero.\n\n'
                     'Por favor, ve a la lista de órdenes y asígnale el número de Odoo para poder avanzarla en el flujo de trabajo.'
        }), 400

    # (Resto del código: actualizar columna, guardar historial, notificaciones...)
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

    # Notificaciones...
    usuarios = User.query.filter(User.is_active == True, User.id != current_user.id).all()
    if usuarios:
        mensaje = f"Orden {order.order_num} movida a '{nueva_columna}' por {current_user.username}"
        enlace = url_for('workflow.board', _external=True)
        notificar_usuarios([u.id for u in usuarios], mensaje, 'orden_movida', order.id, enlace)

    return jsonify({'success': True, 'mensaje': f'Movida a {nueva_columna}'})

@workflow_bp.route('/prioridad/<int:order_id>', methods=['POST'])
@login_required
def cambiar_prioridad(order_id):
    if current_user.role not in ['admin', 'comercial', 'odalys']:
        return jsonify({'error': 'No tienes permiso'}), 403

    data = request.get_json()
    nueva_prioridad = data.get('prioridad')
    if nueva_prioridad not in ['urgente', 'normal', 'critica']:
        return jsonify({'error': 'Prioridad inválida'}), 400

    order = Order.query.get_or_404(order_id)
    order.priority = nueva_prioridad
    order.add_history(f'Prioridad cambiada a {nueva_prioridad} por {current_user.username}')
    db.session.commit()

    usuarios = User.query.filter(User.is_active == True, User.id != current_user.id).all()
    if usuarios:
        mensaje = f"Prioridad de {order.order_num} cambiada a '{nueva_prioridad}' por {current_user.username}"
        enlace = url_for('workflow.board', _external=True)
        notificar_usuarios([u.id for u in usuarios], mensaje, 'prioridad_cambiada', order.id, enlace)

    return jsonify({'success': True})

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

@workflow_bp.route('/columna/<columna_id>')
@login_required
def obtener_columna(columna_id):
    if columna_id not in [c['id'] for c in COLUMNAS]:
        return jsonify({'error': 'Columna inválida'}), 400

    query = Order.query.filter_by(column=columna_id)
    orders = query.all()
    if columna_id == 'entregados':
        limite = datetime.now() - timedelta(hours=24)
        orders = [o for o in orders if o.fecha_entregado and o.fecha_entregado >= limite]

    data = [{
        'id': o.id,
        'num': o.order_num,
        'cliente': o.client.nombre if o.client else 'Sin cliente',
        'prioridad': o.priority,
        'fecha_entregado': o.fecha_entregado.strftime('%d/%m/%Y %H:%M') if o.fecha_entregado else None
    } for o in orders]

    return jsonify(data)