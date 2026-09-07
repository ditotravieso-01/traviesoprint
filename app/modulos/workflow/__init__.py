from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from app.models import Order, User, Client, Configuracion
from app import db
from datetime import datetime, timedelta
from app.services.notification_service import notificar_usuarios
import json
import traceback

workflow_bp = Blueprint('workflow', __name__, url_prefix='/workflow', template_folder='templates')

# ============================================================
# DECORADOR ADMIN
# ============================================================
def admin_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if current_user.role != 'admin':
            flash('Solo el administrador puede acceder.', 'danger')
            return redirect(url_for('workflow.board'))
        return func(*args, **kwargs)
    return wrapper

# ============================================================
# CONFIGURACIÓN POR DEFECTO (sin odalys)
# ============================================================
DEFAULT_COLUMNAS = [
    {'id': 'pendiente', 'icono': 'fa-clock', 'nombre': 'Pendiente'},
    {'id': 'por-preparar', 'icono': 'fa-tools', 'nombre': 'Por preparar'},
    {'id': 'preparados', 'icono': 'fa-check-circle', 'nombre': 'Preparados'},
    {'id': 'imprimir-hoy', 'icono': 'fa-print', 'nombre': 'Imprimir hoy'},
    {'id': 'impreso-corte', 'icono': 'fa-cut', 'nombre': 'Impreso y corte'},
    {'id': 'produccion', 'icono': 'fa-industry', 'nombre': 'Producción'},
    {'id': 'listo', 'icono': 'fa-box', 'nombre': 'Listo'},
    {'id': 'entregados', 'icono': 'fa-truck', 'nombre': 'Entregados'}
]

DEFAULT_RUTAS = {
    'impresion': ['pendiente', 'por-preparar', 'preparados', 'imprimir-hoy', 'impreso-corte', 'produccion', 'listo', 'entregados'],
    'produccion': ['pendiente', 'por-preparar', 'preparados', 'produccion', 'listo', 'entregados']
}

DEFAULT_PERMISOS_MOVER = {
    'comercial': ['pendiente', 'preparados', 'listo'],
    'disennador': ['por-preparar'],
    'diseñador': ['por-preparar'],
    'disenador': ['por-preparar'],
    'operario': ['preparados', 'imprimir-hoy', 'impreso-corte', 'produccion'],
    'admin': ['pendiente', 'por-preparar', 'preparados', 'imprimir-hoy', 'impreso-corte', 'produccion', 'listo', 'entregados']
}

DEFAULT_MOVIMIENTO_NOTIFICACIONES = {
    ('pendiente', 'por-preparar'): ['disennador', 'diseñador', 'disenador'],
    ('por-preparar', 'preparados'): ['operario', 'comercial'],
    ('preparados', 'imprimir-hoy'): ['operario', 'comercial'],
    ('imprimir-hoy', 'impreso-corte'): ['operario', 'comercial'],
    ('impreso-corte', 'produccion'): ['operario', 'comercial'],
    ('impreso-corte', 'listo'): ['operario', 'comercial', 'economico'],
    ('produccion', 'listo'): ['operario', 'comercial', 'economico'],
}

# ============================================================
# FUNCIONES DE CONFIGURACIÓN (CORREGIDAS)
# ============================================================
def get_workflow_config():
    """Obtiene la configuración completa, siempre con todas las claves por defecto."""
    config_entry = Configuracion.query.filter_by(clave='workflow_config').first()
    if config_entry:
        try:
            data = json.loads(config_entry.valor)
            # Asegurar que todas las claves existan
            if not isinstance(data, dict):
                data = {}
            data.setdefault('columnas', DEFAULT_COLUMNAS)
            data.setdefault('rutas', DEFAULT_RUTAS)
            data.setdefault('permisos_mover', DEFAULT_PERMISOS_MOVER)
            data.setdefault('movimiento_notificaciones', DEFAULT_MOVIMIENTO_NOTIFICACIONES)
            return data
        except Exception as e:
            print(f"❌ Error al cargar configuración: {e}")
            # Si falla, devolver defaults
            pass
    return {
        'columnas': DEFAULT_COLUMNAS,
        'rutas': DEFAULT_RUTAS,
        'permisos_mover': DEFAULT_PERMISOS_MOVER,
        'movimiento_notificaciones': DEFAULT_MOVIMIENTO_NOTIFICACIONES
    }

def save_workflow_config(config):
    config_entry = Configuracion.query.filter_by(clave='workflow_config').first()
    if config_entry:
        config_entry.valor = json.dumps(config)
    else:
        config_entry = Configuracion(clave='workflow_config', valor=json.dumps(config))
        db.session.add(config_entry)
    db.session.commit()

def get_columnas():
    return get_workflow_config().get('columnas', DEFAULT_COLUMNAS)

def get_rutas():
    config = get_workflow_config()
    return config.get('rutas', DEFAULT_RUTAS)

def get_permisos_mover():
    return get_workflow_config().get('permisos_mover', DEFAULT_PERMISOS_MOVER)

def get_movimiento_notificaciones():
    raw = get_workflow_config().get('movimiento_notificaciones', DEFAULT_MOVIMIENTO_NOTIFICACIONES)
    result = {}
    for key, value in raw.items():
        if isinstance(key, str):
            from_key, to_key = key.split('->')
            result[(from_key, to_key)] = value
        else:
            result[key] = value
    return result

def obtener_permisos_mover(rol):
    permisos = get_permisos_mover()
    if rol in permisos:
        return permisos[rol]
    rol_lower = rol.lower().replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u')
    if 'disen' in rol_lower:
        return permisos.get('disennador', [])
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
# RUTA PRINCIPAL
# ============================================================
@workflow_bp.route('/')
@login_required
def board():
    orders = Order.query.all()
    orders_dict = [_order_to_dict(o) for o in orders]
    columnas_info = get_columnas()
    columnas = {col['id']: [] for col in columnas_info}
    for o in orders_dict:
        col = o['column'] if o['column'] in columnas else 'pendiente'
        columnas[col].append(o)

    ahora = datetime.now()
    usuarios = User.query.filter_by(is_active=True).order_by(User.username).all()
    puede_cambiar_prioridad = current_user.role in ['admin', 'comercial']
    columnas_permitidas = obtener_permisos_mover(current_user.role)
    puede_eliminar = current_user.role in ['comercial', 'admin']

    total_activas = sum(1 for o in orders_dict if o['column'] != 'entregados')
    total_entregadas = sum(1 for o in orders_dict if o['column'] == 'entregados')
    pendientes = sum(1 for o in orders_dict if o['column'] in ['pendiente', 'por-preparar'])
    en_proceso = sum(1 for o in orders_dict if o['column'] in ['preparados', 'imprimir-hoy', 'impreso-corte', 'produccion'])
    listas = sum(1 for o in orders_dict if o['column'] == 'listo')

    chart_labels = [col['nombre'] for col in columnas_info]
    chart_data = [len(columnas[col['id']]) for col in columnas_info]

    return render_template('board.html',
                           columnas=columnas,
                           columnas_info=columnas_info,
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
# MOVER ORDEN (CON FALLBACK PARA RUTAS)
# ============================================================
@workflow_bp.route('/mover/<int:order_id>', methods=['POST'])
@login_required
def mover_ajax(order_id):
    try:
        # 1. Obtener datos de la petición
        try:
            data = request.get_json(force=True)
        except Exception as e:
            return jsonify({'error': f'Formato JSON inválido: {str(e)}'}), 400

        nueva_columna = data.get('columna') if data else None
        if not nueva_columna:
            return jsonify({'error': 'Falta el campo "columna"'}), 400

        # 2. Obtener orden y validar
        order = Order.query.get_or_404(order_id)
        columnas_info = get_columnas()
        columnas_validas = [c['id'] for c in columnas_info]
        if nueva_columna not in columnas_validas:
            return jsonify({'error': 'Columna inválida'}), 400

        # 3. Validar permisos del usuario
        columnas_permitidas = obtener_permisos_mover(current_user.role)
        if order.column not in columnas_permitidas:
            return jsonify({
                'error': f'No tienes permiso para mover desde "{order.column}". Solo puedes mover desde: {", ".join(columnas_permitidas)}'
            }), 403

        # 4. Validar ruta de la orden (con fallback)
        ruta_orden = getattr(order, 'ruta', 'impresion')
        rutas = get_rutas()
        # Si por alguna razón las rutas no tienen la clave, usar DEFAULT_RUTAS
        if not rutas or ruta_orden not in rutas:
            print(f"⚠️ Ruta '{ruta_orden}' no encontrada en configuración. Usando DEFAULT_RUTAS.")
            rutas = DEFAULT_RUTAS
            ruta_orden = 'impresion'  # Forzar a impresion por defecto
        if nueva_columna not in rutas[ruta_orden]:
            return jsonify({
                'error': f'❌ La orden tiene ruta "{ruta_orden}" y no permite mover a "{nueva_columna}".\n'
                         f'Ruta permitida: {" → ".join(rutas[ruta_orden])}'
            }), 400

        # 5. Validar entrada al sistema
        if not order.entrada_ok and nueva_columna != 'pendiente':
            return jsonify({
                'error': '⚠️ Esta orden no tiene entrada al sistema. Debes marcarla como "Entrada" primero.\n\n'
                         'Por favor, ve a la lista de órdenes y asígnale el número de Odoo para poder avanzarla en el flujo de trabajo.'
            }), 400

        # 6. Guardar columna anterior
        columna_anterior = order.column

        # 7. Consumir materiales (si aplica)
        if nueva_columna == 'impreso-corte' and order.entrada_ok:
            from app.modulos.ordenes import consumir_materiales
            success, msg = consumir_materiales(order.id)
            if not success:
                return jsonify({'error': f'Error al consumir materiales: {msg}'}), 400

        # 8. Actualizar columna
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

        # 9. Notificaciones
        mov_notif = get_movimiento_notificaciones()
        roles_a_notificar = []
        if nueva_columna == 'entregados':
            roles_a_notificar = ['comercial', 'economico']
        else:
            roles_a_notificar = mov_notif.get((columna_anterior, nueva_columna), [])

        if roles_a_notificar:
            usuarios = User.query.filter(
                User.is_active == True,
                User.role.in_(roles_a_notificar)
            ).all()
            usuario_ids = [u.id for u in usuarios if u.id != current_user.id]
            if usuario_ids:
                mensaje = f"Orden {order.order_num} movida de '{columna_anterior}' a '{nueva_columna}' por {current_user.username}"
                enlace = url_for('workflow.board', _external=True)
                notificar_usuarios(
                    usuario_ids=usuario_ids,
                    mensaje=mensaje,
                    tipo='orden_movida',
                    order_id=order.id,
                    enlace=enlace
                )

        return jsonify({'success': True, 'mensaje': f'Movida a {nueva_columna}'})

    except Exception as e:
        db.session.rollback()
        error_full = traceback.format_exc()
        print(f"❌ Error en mover_ajax: {error_full}")
        return jsonify({'error': f'Error interno: {str(e)}. Ver logs del servidor.'}), 500

# ============================================================
# CAMBIAR RUTA
# ============================================================
@workflow_bp.route('/cambiar-ruta/<int:order_id>', methods=['POST'])
@login_required
def cambiar_ruta(order_id):
    if current_user.role not in ['admin', 'comercial']:
        return jsonify({'error': 'No tienes permiso'}), 403

    data = request.get_json()
    nueva_ruta = data.get('ruta')
    rutas = get_rutas()
    if not rutas or nueva_ruta not in rutas:
        return jsonify({'error': 'Ruta inválida'}), 400

    order = Order.query.get_or_404(order_id)
    order.ruta = nueva_ruta
    if order.column not in rutas[nueva_ruta]:
        order.column = rutas[nueva_ruta][0]
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
    columnas_validas = [c['id'] for c in get_columnas()]
    if columna_id not in columnas_validas:
        return jsonify({'error': 'Columna inválida'}), 400
    orders = Order.query.filter_by(column=columna_id).all()
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
    orders = Order.query.all()
    orders_dict = [_order_to_dict(o) for o in orders]
    columnas_info = get_columnas()

    column_counts = {col['id']: 0 for col in columnas_info}
    for o in orders_dict:
        col = o['column'] if o['column'] in column_counts else 'pendiente'
        column_counts[col] += 1

    total_activas = sum(1 for o in orders_dict if o['column'] != 'entregados')
    total_entregadas = sum(1 for o in orders_dict if o['column'] == 'entregados')
    pendientes = sum(1 for o in orders_dict if o['column'] in ['pendiente', 'por-preparar'])
    en_proceso = sum(1 for o in orders_dict if o['column'] in ['preparados', 'imprimir-hoy', 'impreso-corte', 'produccion'])
    listas = sum(1 for o in orders_dict if o['column'] == 'listo')

    chart_labels = [col['nombre'] for col in columnas_info]
    chart_data = [column_counts[col['id']] for col in columnas_info]

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

# ============================================================
# ADMINISTRACIÓN DEL WORKFLOW
# ============================================================
@workflow_bp.route('/admin')
@login_required
@admin_required
def admin_panel():
    config = get_workflow_config()
    columnas = config.get('columnas', DEFAULT_COLUMNAS)
    permisos = config.get('permisos_mover', DEFAULT_PERMISOS_MOVER)
    notificaciones_raw = config.get('movimiento_notificaciones', DEFAULT_MOVIMIENTO_NOTIFICACIONES)
    notif_list = []
    for k, v in notificaciones_raw.items():
        if isinstance(k, tuple):
            origen, destino = k
        else:
            origen, destino = k.split('->')
        notif_list.append({'origen': origen, 'destino': destino, 'roles': v})
    todos_roles = ['admin', 'comercial', 'disennador', 'diseñador', 'disenador', 'operario', 'economico']
    roles_list = sorted(set(todos_roles + list(permisos.keys())))
    columnas_ids = [c['id'] for c in columnas]
    return render_template('workflow_admin.html',
                           columnas=columnas,
                           permisos=permisos,
                           notificaciones=notif_list,
                           todos_roles=todos_roles,
                           roles_list=roles_list,
                           columnas_ids=columnas_ids)

@workflow_bp.route('/admin/guardar', methods=['POST'])
@login_required
@admin_required
def admin_guardar():
    data = request.get_json()
    if not data or 'columnas' not in data or 'permisos_mover' not in data or 'movimiento_notificaciones' not in data:
        return jsonify({'error': 'Faltan campos requeridos'}), 400
    notif_dict = {}
    for item in data['movimiento_notificaciones']:
        key = f"{item['origen']}->{item['destino']}"
        notif_dict[key] = item['roles']
    data['movimiento_notificaciones'] = notif_dict
    if 'rutas' not in data:
        data['rutas'] = DEFAULT_RUTAS
    save_workflow_config(data)
    return jsonify({'success': True})