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
# COLUMNAS POR DEFECTO
# ============================================================
DEFAULT_COLUMNAS = [
    {'id': 'pendiente',      'icono': 'fa-clock',        'nombre': 'Pendiente'},
    {'id': 'por-preparar',   'icono': 'fa-tools',        'nombre': 'Por preparar'},
    {'id': 'preparados',     'icono': 'fa-check-circle', 'nombre': 'Preparados'},
    {'id': 'imprimir-hoy',   'icono': 'fa-print',        'nombre': 'Imprimir hoy'},
    {'id': 'impreso-corte',  'icono': 'fa-cut',          'nombre': 'Impreso y corte'},
    {'id': 'produccion',     'icono': 'fa-industry',     'nombre': 'Producción'},
    {'id': 'listo',          'icono': 'fa-box',          'nombre': 'Listo'},
    {'id': 'entregados',     'icono': 'fa-truck',        'nombre': 'Entregados'}
]

# ============================================================
# RUTAS POR TIPO DE PROYECTO — fuente de verdad del workflow
# ============================================================
RUTAS_POR_TIPO = {
    'grafica':    ['pendiente', 'por-preparar', 'preparados', 'imprimir-hoy', 'impreso-corte', 'listo', 'entregados'],
    'produccion': ['pendiente', 'por-preparar', 'preparados', 'produccion', 'listo', 'entregados'],
    'mixto':      ['pendiente', 'por-preparar', 'preparados', 'imprimir-hoy', 'impreso-corte', 'produccion', 'listo', 'entregados'],
    'otro':       ['pendiente', 'entregados'],
}

TIPO_PROYECTO_DEFAULT = 'grafica'

TIPO_PROYECTO_LABELS = {
    'grafica':    'Gráfica',
    'produccion': 'Producción',
    'mixto':      'Mixto',
    'otro':       'Otro',
}

# Alias legacy — no usar en código nuevo.
DEFAULT_RUTAS = RUTAS_POR_TIPO


def _normalizar_tipo_proyecto(valor):
    """Devuelve un tipo válido o el default 'grafica'."""
    if valor in RUTAS_POR_TIPO:
        return valor
    return TIPO_PROYECTO_DEFAULT


def _ruta_para_tipo(tipo_proyecto):
    """Devuelve la lista de columnas para un tipo de proyecto."""
    return RUTAS_POR_TIPO.get(
        _normalizar_tipo_proyecto(tipo_proyecto),
        RUTAS_POR_TIPO[TIPO_PROYECTO_DEFAULT]
    )


def _calcular_columna_segura(columna_actual, tipo_viejo, tipo_nuevo):
    """
    Si la columna actual NO existe en la ruta nueva, devuelve la columna
    más avanzada en la ruta vieja (<= posición actual) que también exista
    en la ruta nueva. Es el "punto de bifurcación" (p.ej. `preparados`).

    Si la columna actual YA existe en la nueva ruta, devuelve None (no mover).
    """
    ruta_vieja = _ruta_para_tipo(tipo_viejo)
    ruta_nueva = _ruta_para_tipo(tipo_nuevo)

    if columna_actual in ruta_nueva:
        return None  # nada que hacer

    if columna_actual in ruta_vieja:
        pos_actual = ruta_vieja.index(columna_actual)
    else:
        pos_actual = len(ruta_vieja) - 1

    candidatas = [c for c in ruta_vieja[:pos_actual + 1] if c in ruta_nueva]

    if not candidatas:
        return ruta_nueva[0] if ruta_nueva else 'pendiente'

    return candidatas[-1]


# ============================================================
# PERMISOS POR DEFECTO
# ============================================================
DEFAULT_PERMISOS_MOVER = {
    'comercial':  ['pendiente', 'preparados', 'listo'],
    'disennador': ['por-preparar'],
    'diseñador':  ['por-preparar'],
    'disenador':  ['por-preparar'],
    'operario':   ['preparados', 'imprimir-hoy', 'impreso-corte', 'produccion'],
    'admin':      ['pendiente', 'por-preparar', 'preparados', 'imprimir-hoy',
                   'impreso-corte', 'produccion', 'listo', 'entregados']
}

DEFAULT_MOVIMIENTO_NOTIFICACIONES = {
    ('pendiente', 'por-preparar'):      ['disennador', 'diseñador', 'disenador'],
    ('por-preparar', 'preparados'):     ['operario', 'comercial'],
    ('preparados', 'imprimir-hoy'):     ['operario', 'comercial'],
    ('imprimir-hoy', 'impreso-corte'):  ['operario', 'comercial'],
    ('impreso-corte', 'produccion'):    ['operario', 'comercial'],
    ('impreso-corte', 'listo'):         ['operario', 'comercial', 'economico'],
    ('produccion', 'listo'):            ['operario', 'comercial', 'economico'],
    ('preparados', 'produccion'):       ['operario', 'comercial'],
}


# ============================================================
# CONFIG (SIN `rutas` — se elimina del JSON guardado)
# ============================================================
def get_workflow_config():
    config_entry = Configuracion.query.filter_by(clave='workflow_config').first()
    if config_entry:
        try:
            data = json.loads(config_entry.valor)
            if not isinstance(data, dict):
                data = {}
            data.setdefault('columnas', DEFAULT_COLUMNAS)
            data.setdefault('permisos_mover', DEFAULT_PERMISOS_MOVER)
            data.setdefault('movimiento_notificaciones', DEFAULT_MOVIMIENTO_NOTIFICACIONES)
            # Compatibilidad: si quedó un `rutas` de versiones viejas, lo ignoramos
            data.pop('rutas', None)
            return data
        except Exception as e:
            print(f"❌ Error al cargar configuración: {e}")
    return {
        'columnas': DEFAULT_COLUMNAS,
        'permisos_mover': DEFAULT_PERMISOS_MOVER,
        'movimiento_notificaciones': DEFAULT_MOVIMIENTO_NOTIFICACIONES,
    }


def save_workflow_config(config):
    # Limpieza: nunca guardamos `rutas` en el config (hardcodeada ahora)
    if isinstance(config, dict):
        config.pop('rutas', None)
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
    """Legacy — devuelve el mapa fijo. Ya no se lee de config."""
    return RUTAS_POR_TIPO


def get_permisos_mover():
    return get_workflow_config().get('permisos_mover', DEFAULT_PERMISOS_MOVER)


def get_movimiento_notificaciones():
    raw = get_workflow_config().get('movimiento_notificaciones', DEFAULT_MOVIMIENTO_NOTIFICACIONES)
    result = {}
    for key, value in raw.items():
        if isinstance(key, str):
            if '->' not in key:
                continue
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
    tipo = _normalizar_tipo_proyecto(getattr(order, 'tipo_proyecto', None))
    return {
        'id': order.id,
        'order_num': order.order_num,
        'client': {
            'id': order.client.id if order.client else None,
            'nombre': order.client.nombre if order.client else 'Sin cliente'
        } if order.client else None,
        'priority': order.priority,
        'column': order.column,
        'tipo_proyecto': tipo,
        'ruta': tipo,  # legacy: sincronizada con tipo_proyecto
        'entrada_ok': order.entrada_ok,
        'requiere_revision': getattr(order, 'requiere_revision', False),
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

    total_activas    = sum(1 for o in orders_dict if o['column'] != 'entregados')
    total_entregadas = sum(1 for o in orders_dict if o['column'] == 'entregados')
    pendientes       = sum(1 for o in orders_dict if o['column'] in ['pendiente', 'por-preparar'])
    en_proceso       = sum(1 for o in orders_dict if o['column'] in ['preparados', 'imprimir-hoy', 'impreso-corte', 'produccion'])
    listas           = sum(1 for o in orders_dict if o['column'] == 'listo')

    chart_labels = [col['nombre'] for col in columnas_info]
    chart_data   = [len(columnas[col['id']]) for col in columnas_info]

    return render_template(
        'board.html',
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
        chart_data=chart_data,
        rutas_por_tipo=RUTAS_POR_TIPO,
        tipo_labels=TIPO_PROYECTO_LABELS,
    )


# ============================================================
# MOVER ORDEN — usa tipo_proyecto como fuente de verdad
# ============================================================
@workflow_bp.route('/mover/<int:order_id>', methods=['POST'])
@login_required
def mover_ajax(order_id):
    try:
        try:
            data = request.get_json(force=True)
        except Exception as e:
            return jsonify({'error': f'Formato JSON inválido: {str(e)}'}), 400

        nueva_columna = data.get('columna') if data else None
        if not nueva_columna:
            return jsonify({'error': 'Falta el campo "columna"'}), 400

        order = Order.query.get_or_404(order_id)
        columnas_info = get_columnas()
        columnas_validas = [c['id'] for c in columnas_info]
        if nueva_columna not in columnas_validas:
            return jsonify({'error': 'Columna inválida'}), 400

        columnas_permitidas = obtener_permisos_mover(current_user.role)
        if order.column not in columnas_permitidas:
            return jsonify({
                'error': f'No tienes permiso para mover desde "{order.column}". '
                         f'Solo puedes mover desde: {", ".join(columnas_permitidas)}'
            }), 403

        tipo_proyecto = _normalizar_tipo_proyecto(getattr(order, 'tipo_proyecto', None))
        ruta_orden = _ruta_para_tipo(tipo_proyecto)

        if nueva_columna not in ruta_orden:
            return jsonify({
                'error': f'❌ Esta orden es de tipo "{TIPO_PROYECTO_LABELS[tipo_proyecto]}" '
                         f'y no permite mover a "{nueva_columna}".\n\n'
                         f'Ruta permitida: {" → ".join(ruta_orden)}'
            }), 400

        if not order.entrada_ok and nueva_columna != 'pendiente':
            return jsonify({
                'error': '⚠️ Esta orden no tiene entrada al sistema. Debes marcarla como "Entrada" primero.\n\n'
                         'Por favor, ve a la lista de órdenes y asígnale el número de Odoo para poder avanzarla.'
            }), 400

        if order.requiere_revision and nueva_columna != order.column:
            return jsonify({
                'error': '⚠️ Esta orden fue importada desde Odoo y todavía no ha sido revisada.\n\n'
                         'Debes abrirla, añadir al menos una línea de trabajo y guardar, '
                         'o pulsar "Marcar como revisada" en el detalle.'
            }), 403

        columna_anterior = order.column

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

        mov_notif = get_movimiento_notificaciones()
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
        print(f"❌ Error en mover_ajax: {traceback.format_exc()}")
        return jsonify({'error': f'Error interno: {str(e)}. Ver logs del servidor.'}), 500


# ============================================================
# CAMBIAR TIPO DE PROYECTO (reemplaza cambiar_ruta)
# Si la columna actual no existe en la nueva ruta → auto-mover
# a la columna segura (punto de bifurcación) + historial.
# ============================================================
@workflow_bp.route('/cambiar-ruta/<int:order_id>', methods=['POST'])
@workflow_bp.route('/cambiar-tipo/<int:order_id>', methods=['POST'])
@login_required
def cambiar_tipo_proyecto(order_id):
    if current_user.role not in ['admin', 'comercial']:
        return jsonify({'error': 'No tienes permiso'}), 403

    data = request.get_json(silent=True) or {}
    # Aceptamos payload nuevo (tipo_proyecto) y viejo (ruta) por compatibilidad
    nuevo_tipo = data.get('tipo_proyecto') or data.get('ruta')
    if not nuevo_tipo:
        return jsonify({'error': 'Falta tipo_proyecto'}), 400
    nuevo_tipo = _normalizar_tipo_proyecto(nuevo_tipo)

    order = Order.query.get_or_404(order_id)
    tipo_viejo = _normalizar_tipo_proyecto(getattr(order, 'tipo_proyecto', None))

    columna_anterior = order.column
    columna_segura = _calcular_columna_segura(columna_anterior, tipo_viejo, nuevo_tipo)
    columna_movida = False

    order.tipo_proyecto = nuevo_tipo
    order.ruta = nuevo_tipo  # legacy sync

    if columna_segura and columna_segura != columna_anterior:
        order.column = columna_segura
        columna_movida = True
        order.add_history(
            f'Tipo de proyecto cambiado a "{TIPO_PROYECTO_LABELS[nuevo_tipo]}". '
            f'Columna "{columna_anterior}" no existe en la nueva ruta → '
            f'movida a "{columna_segura}".'
        )
    else:
        order.add_history(
            f'Tipo de proyecto cambiado a "{TIPO_PROYECTO_LABELS[nuevo_tipo]}".'
        )

    db.session.commit()
    return jsonify({
        'success': True,
        'tipo_proyecto': nuevo_tipo,
        'tipo_label': TIPO_PROYECTO_LABELS[nuevo_tipo],
        'columna': order.column,
        'columna_anterior': columna_anterior,
        'columna_movida': columna_movida,
        'mensaje': (
            f'Tipo cambiado a {TIPO_PROYECTO_LABELS[nuevo_tipo]}. '
            + (f'Columna movida a {columna_segura}.' if columna_movida else '')
        ).strip()
    })


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

    total_activas    = sum(1 for o in orders_dict if o['column'] != 'entregados')
    total_entregadas = sum(1 for o in orders_dict if o['column'] == 'entregados')
    pendientes       = sum(1 for o in orders_dict if o['column'] in ['pendiente', 'por-preparar'])
    en_proceso       = sum(1 for o in orders_dict if o['column'] in ['preparados', 'imprimir-hoy', 'impreso-corte', 'produccion'])
    listas           = sum(1 for o in orders_dict if o['column'] == 'listo')

    chart_labels = [col['nombre'] for col in columnas_info]
    chart_data   = [column_counts[col['id']] for col in columnas_info]

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
            if '->' not in k:
                continue
            origen, destino = k.split('->')
        notif_list.append({'origen': origen, 'destino': destino, 'roles': v})

    todos_roles = ['admin', 'comercial', 'disennador', 'diseñador', 'disenador', 'operario', 'economico']
    roles_list = sorted(set(todos_roles + list(permisos.keys())))
    columnas_ids = [c['id'] for c in columnas]

    return render_template(
        'workflow_admin.html',
        columnas=columnas,
        permisos=permisos,
        notificaciones=notif_list,
        todos_roles=todos_roles,
        roles_list=roles_list,
        columnas_ids=columnas_ids,
    )


@workflow_bp.route('/admin/guardar', methods=['POST'])
@login_required
@admin_required
def admin_guardar():
    data = request.get_json()
    if not data or 'columnas' not in data or 'permisos_mover' not in data \
       or 'movimiento_notificaciones' not in data:
        return jsonify({'error': 'Faltan campos requeridos'}), 400

    notif_dict = {}
    for item in data['movimiento_notificaciones']:
        key = f"{item['origen']}->{item['destino']}"
        notif_dict[key] = item['roles']

    config_final = {
        'columnas': data['columnas'],
        'permisos_mover': data['permisos_mover'],
        'movimiento_notificaciones': notif_dict,
    }
    save_workflow_config(config_final)
    return jsonify({'success': True})