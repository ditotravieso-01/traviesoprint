from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import login_required, current_user
from app.models import Client, User, Order, ArchivoAdjunto, Producto, Configuracion
from app import db
from datetime import datetime, timedelta, date
import io
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill
import json
import re
from collections import Counter, defaultdict
from sqlalchemy import func

clientes_bp = Blueprint('clientes', __name__, url_prefix='/clientes', template_folder='templates')

# ==========================================
# DECORADORES DE PERMISOS
# ==========================================

def comercial_or_admin_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if current_user.role not in ['comercial', 'admin']:
            flash('No tienes permiso para realizar esta acción.', 'danger')
            return redirect(url_for('home.index'))
        return func(*args, **kwargs)
    return wrapper

def view_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if current_user.role not in ['comercial', 'admin', 'economico']:
            flash('No tienes permiso para ver clientes.', 'danger')
            return redirect(url_for('home.index'))
        return func(*args, **kwargs)
    return wrapper

def admin_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if current_user.role != 'admin':
            flash('Solo el administrador puede realizar esta acción.', 'danger')
            return redirect(url_for('clientes.listar_clientes'))
        return func(*args, **kwargs)
    return wrapper

# ==========================================
# FUNCIONES DE CONFIGURACIÓN
# ==========================================

def obtener_config(clave, default=None):
    config = Configuracion.query.filter_by(clave=clave).first()
    if config:
        return config.valor
    return default

def guardar_config(clave, valor, descripcion=''):
    config = Configuracion.query.filter_by(clave=clave).first()
    if config:
        config.valor = str(valor)
        config.descripcion = descripcion
    else:
        config = Configuracion(clave=clave, valor=str(valor), descripcion=descripcion)
        db.session.add(config)
    db.session.commit()

def get_dashboard_config():
    default = {
        'graficos': {
            'nuevos_clientes': True,
            'niveles': True,
            'tipo_nuevos': 'bar',
            'tipo_niveles': 'doughnut'
        },
        'widgets': {
            'nuevos_mes': True,
            'retencion': True,
            'top_clientes': True,
            'recientes': True
        },
        'colores': {
            'grafico_nuevos': '#a8854f',
            'grafico_niveles': ['#1a1a1a', '#d4a574', '#8e8e93']
        },
        'orden': ['kpis', 'graficos', 'widgets', 'recientes', 'niveles', 'acciones'],
        'estilo': {
            'altura_graficos': 80,
            'mostrar_leyenda_niveles': True,
            'mostrar_etiquetas': True
        }
    }
    try:
        config = json.loads(obtener_config('clientes_dashboard_config', '{}'))
        for key in default:
            if key not in config:
                config[key] = default[key]
            elif isinstance(default[key], dict):
                for subkey in default[key]:
                    if subkey not in config[key]:
                        config[key][subkey] = default[key][subkey]
        return config
    except:
        return default

def guardar_dashboard_config(config):
    guardar_config('clientes_dashboard_config', json.dumps(config), 'Configuración del dashboard de clientes')

# ==========================================
# FUNCIONES AUXILIARES DE NIVELES
# ==========================================

def calcular_nivel_cliente(cliente, top_black_ids, top_golden_ids):
    if cliente.id in top_black_ids:
        return 'black'
    elif cliente.id in top_golden_ids:
        return 'golden'
    return 'standard'

def get_nivel_info(nivel, config_colores=None, config_nombres=None):
    colores_default = {
        'black': '#1a1a1a',
        'golden': '#d4a574',
        'standard': '#8e8e93'
    }
    nombres_default = {
        'black': 'Black',
        'golden': 'Golden',
        'standard': 'Standard'
    }

    if config_colores is None:
        try:
            config_colores = json.loads(obtener_config('clientes_colores_niveles', '{}'))
        except:
            config_colores = {}
    if config_nombres is None:
        try:
            config_nombres = json.loads(obtener_config('clientes_nombres_niveles', '{}'))
        except:
            config_nombres = {}

    color = config_colores.get(nivel, colores_default.get(nivel, '#8e8e93'))
    nombre = config_nombres.get(nivel, nombres_default.get(nivel, nivel.capitalize()))

    return {
        'color': color,
        'nombre': nombre,
        'label': nombre,
        'clase': f'nivel-{nivel}',
        'badge': '🔥' if nivel == 'black' else '⭐' if nivel == 'golden' else '👤'
    }

def get_columnas_visibles():
    try:
        columnas = json.loads(obtener_config('clientes_columnas_visibles', '[]'))
        if not columnas:
            columnas = ['referencia', 'nombre', 'telefono', 'email', 'pedidos', 'metros', 'nivel', 'acciones']
    except:
        columnas = ['referencia', 'nombre', 'telefono', 'email', 'pedidos', 'metros', 'nivel', 'acciones']
    return columnas

def get_clasificacion_automatica():
    val = obtener_config('clientes_clasificacion_automatica', 'true')
    return val.lower() == 'true'

# ==========================================
# FUNCIONES AUXILIARES PARA DASHBOARD
# ==========================================

def get_clientes_nuevos_por_mes():
    ahora = datetime.now()
    meses = []
    valores = []
    for i in range(11, -1, -1):
        mes = ahora.replace(day=1) - timedelta(days=30*i)
        nombre_mes = mes.strftime('%b %Y')
        meses.append(nombre_mes)
        inicio = mes.replace(day=1).date()
        if mes.month == 12:
            fin = datetime(mes.year + 1, 1, 1).date()
        else:
            fin = datetime(mes.year, mes.month + 1, 1).date()
        count = Client.query.filter(Client.created_at >= inicio, Client.created_at < fin).count()
        valores.append(count)
    return meses, valores

def get_top_clientes_metros(limit=5):
    clientes = Client.query.all()
    for c in clientes:
        c.total_metros = calcular_metros_cliente(c)
    clientes.sort(key=lambda x: x.total_metros, reverse=True)
    top = clientes[:limit]
    return [c.nombre for c in top], [c.total_metros for c in top]

def get_tasa_retencion():
    total = Client.query.count()
    if total == 0:
        return 0
    repetidos = 0
    for c in Client.query.all():
        if len(c.orders) > 1:
            repetidos += 1
    return round((repetidos / total) * 100, 1)

def get_clientes_recientes(limit=5):
    return Client.query.order_by(Client.created_at.desc()).limit(limit).all()

# ==========================================
# INSIGHTS DEL CLIENTE
# ==========================================

def calcular_insights_cliente(cliente):
    orders = Order.query.filter_by(client_id=cliente.id).all()
    servicios_counter = Counter()
    materiales_counter = Counter()
    productos_counter = Counter()
    formatos_counter = Counter()
    
    for o in orders:
        for s in o.get_servicios():
            servicios_counter[s] += 1
        for a in o.archivos:
            if a.nombre_visible:
                materiales_counter[a.nombre_visible] += 1
            if a.material:
                materiales_counter[a.material] += 1
            if a.producto_id:
                prod = Producto.query.get(a.producto_id)
                if prod:
                    productos_counter[prod.nombre] += 1
        for a in o.archivos:
            if a.parametros_etiqueta:
                try:
                    params = json.loads(a.parametros_etiqueta)
                    if params.get('ancho') and params.get('alto'):
                        formato = f"{params.get('ancho')}x{params.get('alto')} cm"
                        formatos_counter[formato] += 1
                except:
                    pass
    
    top_servicios = servicios_counter.most_common(5)
    top_materiales = materiales_counter.most_common(5)
    top_productos = productos_counter.most_common(5)
    top_formatos = formatos_counter.most_common(5)
    
    gustos = []
    for servicio, count in top_servicios:
        gustos.append({'tipo': 'servicio', 'nombre': servicio, 'count': count})
    for material, count in top_materiales:
        gustos.append({'tipo': 'material', 'nombre': material, 'count': count})
    for producto, count in top_productos:
        gustos.append({'tipo': 'producto', 'nombre': producto, 'count': count})
    
    return {
        'top_servicios': top_servicios,
        'top_materiales': top_materiales,
        'top_productos': top_productos,
        'top_formatos': top_formatos,
        'gustos': gustos[:5],
        'total_ordenes': len(orders),
        'frecuencia': calcular_frecuencia(orders)
    }

def calcular_frecuencia(orders):
    if len(orders) < 2:
        return 'eventual'
    fechas = []
    for o in orders:
        if o.date:
            if isinstance(o.date, datetime):
                fechas.append(o.date.date())
            else:
                fechas.append(o.date)
    if len(fechas) < 2:
        return 'eventual'
    fechas.sort()
    diffs = [(fechas[i+1] - fechas[i]).days for i in range(len(fechas)-1)]
    avg_days = sum(diffs) / len(diffs)
    if avg_days <= 1:
        return 'diario'
    elif avg_days <= 7:
        return 'semanal'
    elif avg_days <= 14:
        return 'quincenal'
    elif avg_days <= 31:
        return 'mensual'
    elif avg_days <= 92:
        return 'trimestral'
    return 'eventual'

# ==========================================
# CÁLCULO DE METROS TOTALES PARA UN CLIENTE
# ==========================================

def calcular_metros_cliente(cliente):
    total_metros = 0.0
    for order in cliente.orders:
        for archivo in order.archivos:
            if archivo.parametros_etiqueta:
                try:
                    params = json.loads(archivo.parametros_etiqueta)
                    if params.get('consumo'):
                        total_metros += params.get('consumo', 0)
                        continue
                except:
                    pass
            if archivo.unidad in ['m', 'm2', 'm²'] and archivo.cantidad:
                total_metros += archivo.cantidad
    return round(total_metros, 2)

# ==========================================
# LISTAR CLIENTES
# ==========================================

@clientes_bp.route('/')
@login_required
@view_required
def listar_clientes():
    search = request.args.get('search', '').strip()
    sort = request.args.get('sort', 'metros')
    order = request.args.get('order', 'desc')
    page = request.args.get('page', 1, type=int)
    per_page = 20

    query = Client.query
    if search:
        query = query.filter(
            db.or_(
                Client.nombre.ilike(f'%{search}%'),
                Client.referencia.ilike(f'%{search}%'),
                Client.email.ilike(f'%{search}%'),
                Client.telefono.ilike(f'%{search}%')
            )
        )

    clientes_todos = query.all()
    
    for c in clientes_todos:
        c.total_metros = calcular_metros_cliente(c)
        c.total_pedidos = len(c.orders) if c.orders else 0
        insights = calcular_insights_cliente(c)
        c.top_materiales = insights['top_materiales'][:2]
        c.top_servicios = insights['top_servicios'][:2]
        c.frecuencia = insights['frecuencia']

    clasificacion_automatica = get_clasificacion_automatica()
    
    try:
        config_colores = json.loads(obtener_config('clientes_colores_niveles', '{}'))
    except:
        config_colores = {}
    try:
        config_nombres = json.loads(obtener_config('clientes_nombres_niveles', '{}'))
    except:
        config_nombres = {}

    if clasificacion_automatica and len(clientes_todos) >= 5:
        try:
            top_black_pct = float(obtener_config('clientes_top_black_pct', '5'))
            top_golden_pct = float(obtener_config('clientes_top_golden_pct', '20'))
        except:
            top_black_pct = 5
            top_golden_pct = 20

        sorted_by_metros = sorted(clientes_todos, key=lambda c: c.total_metros, reverse=True)
        n = len(sorted_by_metros)
        top_black = max(1, int(n * top_black_pct / 100))
        top_golden = max(1, int(n * top_golden_pct / 100))
        top_black_ids = set([c.id for c in sorted_by_metros[:top_black]])
        top_golden_ids = set([c.id for c in sorted_by_metros[:top_golden]])
    else:
        top_black_ids = set()
        top_golden_ids = set()
        for c in clientes_todos:
            c.nivel = 'standard'
            c.nivel_info = get_nivel_info('standard', config_colores, config_nombres)

    nivel_map = {}
    black_count = 0
    golden_count = 0
    standard_count = 0
    for c in clientes_todos:
        if clasificacion_automatica:
            nivel = calcular_nivel_cliente(c, top_black_ids, top_golden_ids)
        else:
            nivel = 'standard'
        nivel_map[c.id] = nivel
        if nivel == 'black':
            black_count += 1
        elif nivel == 'golden':
            golden_count += 1
        else:
            standard_count += 1
        c.nivel = nivel
        c.nivel_info = get_nivel_info(nivel, config_colores, config_nombres)

    if sort == 'referencia':
        key_func = lambda x: x.referencia
    elif sort == 'nombre':
        key_func = lambda x: x.nombre
    elif sort == 'telefono':
        key_func = lambda x: x.telefono or ''
    elif sort == 'email':
        key_func = lambda x: x.email or ''
    elif sort == 'pedidos':
        key_func = lambda x: x.total_pedidos
    elif sort == 'metros':
        key_func = lambda x: x.total_metros
    elif sort == 'nivel':
        nivel_order = {'black': 3, 'golden': 2, 'standard': 1}
        key_func = lambda x: nivel_order.get(x.nivel, 0)
    else:
        key_func = lambda x: x.total_metros

    reverse = (order == 'desc')
    clientes_todos.sort(key=key_func, reverse=reverse)

    total = len(clientes_todos)
    start = (page - 1) * per_page
    end = start + per_page
    clients = clientes_todos[start:end]
    total_pages = (total + per_page - 1) // per_page

    total_clientes = len(clientes_todos)
    total_ordenes = sum(c.total_pedidos for c in clientes_todos)

    fecha_limite = datetime.now().date() - timedelta(days=30)
    clientes_activos = 0
    for c in clientes_todos:
        for o in c.orders:
            if o.date and o.date >= fecha_limite:
                clientes_activos += 1
                break

    top_cliente = max(clientes_todos, key=lambda x: x.total_metros) if clientes_todos else None
    top_cliente_nombre = top_cliente.nombre if top_cliente else '—'
    top_cliente_metros = top_cliente.total_metros if top_cliente else 0
    top_cliente_pedidos = top_cliente.total_pedidos if top_cliente else 0

    columnas_visibles = get_columnas_visibles()

    meses_nuevos, valores_nuevos = get_clientes_nuevos_por_mes()
    top_nombres, top_metros = get_top_clientes_metros(5)
    top_clientes_data = list(zip(top_nombres, top_metros))
    tasa_retencion = get_tasa_retencion()
    clientes_recientes = get_clientes_recientes(5)

    nivel_labels = []
    nivel_data = []
    nivel_colors = []
    niveles_orden = ['black', 'golden', 'standard']
    for nivel in niveles_orden:
        count = sum(1 for c in clientes_todos if nivel_map.get(c.id) == nivel)
        nivel_labels.append(config_nombres.get(nivel, nivel.capitalize()))
        nivel_data.append(count)
        nivel_colors.append(config_colores.get(nivel, '#8e8e93'))

    dashboard_config = get_dashboard_config()

    context = {
        'clients': clients,
        'search': search,
        'sort': sort,
        'order': order,
        'page': page,
        'per_page': per_page,
        'total': total,
        'total_pages': total_pages,
        'total_clientes': total_clientes,
        'total_ordenes': total_ordenes,
        'clientes_activos': clientes_activos,
        'top_cliente_nombre': top_cliente_nombre,
        'top_cliente_pedidos': top_cliente_pedidos,
        'top_cliente_metros': top_cliente_metros,
        'black_count': black_count,
        'golden_count': golden_count,
        'standard_count': standard_count,
        'columnas_visibles': columnas_visibles,
        'clasificacion_automatica': clasificacion_automatica,
        'config_colores': config_colores,
        'config_nombres': config_nombres,
        'meses_nuevos': meses_nuevos,
        'valores_nuevos': valores_nuevos,
        'top_nombres': top_nombres,
        'top_metros': top_metros,
        'top_clientes_data': top_clientes_data,
        'tasa_retencion': tasa_retencion,
        'clientes_recientes': clientes_recientes,
        'nivel_labels': nivel_labels,
        'nivel_data': nivel_data,
        'nivel_colors': nivel_colors,
        'dashboard_config': dashboard_config,
    }

    return render_template('clientes.html', **context)


# ==========================================
# CONFIGURACIÓN DE NIVELES (SOLO ADMIN)
# ==========================================

@clientes_bp.route('/configuracion', methods=['GET'])
@login_required
@admin_required
def get_configuracion():
    top_black = obtener_config('clientes_top_black_pct', '5')
    top_golden = obtener_config('clientes_top_golden_pct', '20')
    try:
        columnas = json.loads(obtener_config('clientes_columnas_visibles', '[]'))
    except:
        columnas = ['referencia', 'nombre', 'telefono', 'email', 'pedidos', 'metros', 'nivel', 'acciones']
    try:
        colores = json.loads(obtener_config('clientes_colores_niveles', '{}'))
    except:
        colores = {}
    try:
        nombres = json.loads(obtener_config('clientes_nombres_niveles', '{}'))
    except:
        nombres = {}
    clasificacion_auto = obtener_config('clientes_clasificacion_automatica', 'true') == 'true'
    dashboard_config = get_dashboard_config()

    return jsonify({
        'top_black_pct': float(top_black),
        'top_golden_pct': float(top_golden),
        'columnas_visibles': columnas,
        'colores': colores,
        'nombres': nombres,
        'clasificacion_automatica': clasificacion_auto,
        'dashboard_config': dashboard_config
    })

@clientes_bp.route('/configuracion', methods=['POST'])
@login_required
@admin_required
def set_configuracion():
    data = request.get_json()
    
    if 'top_black_pct' in data and 'top_golden_pct' in data:
        top_black = data.get('top_black_pct')
        top_golden = data.get('top_golden_pct')
        try:
            top_black = float(top_black)
            top_golden = float(top_golden)
            if top_black <= 0 or top_golden <= 0 or top_black >= top_golden:
                return jsonify({'error': 'Los valores deben ser positivos y Black < Golden'}), 400
            guardar_config('clientes_top_black_pct', str(top_black))
            guardar_config('clientes_top_golden_pct', str(top_golden))
        except:
            return jsonify({'error': 'Valores inválidos'}), 400

    if 'columnas_visibles' in data:
        columnas = data['columnas_visibles']
        if not isinstance(columnas, list):
            return jsonify({'error': 'columnas_visibles debe ser una lista'}), 400
        guardar_config('clientes_columnas_visibles', json.dumps(columnas))

    if 'colores' in data:
        colores = data['colores']
        if not isinstance(colores, dict):
            return jsonify({'error': 'colores debe ser un diccionario'}), 400
        guardar_config('clientes_colores_niveles', json.dumps(colores))

    if 'nombres' in data:
        nombres = data['nombres']
        if not isinstance(nombres, dict):
            return jsonify({'error': 'nombres debe ser un diccionario'}), 400
        guardar_config('clientes_nombres_niveles', json.dumps(nombres))

    if 'clasificacion_automatica' in data:
        val = data['clasificacion_automatica']
        guardar_config('clientes_clasificacion_automatica', 'true' if val else 'false')

    if 'dashboard_config' in data:
        guardar_dashboard_config(data['dashboard_config'])

    return jsonify({'success': True, 'message': 'Configuración guardada'})

# ==========================================
# PANEL DE ADMINISTRACIÓN DE CLIENTES
# ==========================================

@clientes_bp.route('/admin')
@login_required
@admin_required
def admin_panel():
    top_black = obtener_config('clientes_top_black_pct', '5')
    top_golden = obtener_config('clientes_top_golden_pct', '20')
    
    total_clientes = Client.query.count()
    total_ordenes = Order.query.count()
    
    clientes_todos = Client.query.all()
    for c in clientes_todos:
        c.total_metros = calcular_metros_cliente(c)
    
    try:
        colores = json.loads(obtener_config('clientes_colores_niveles', '{}'))
    except:
        colores = {}
    try:
        nombres = json.loads(obtener_config('clientes_nombres_niveles', '{}'))
    except:
        nombres = {}
    try:
        columnas = json.loads(obtener_config('clientes_columnas_visibles', '[]'))
    except:
        columnas = ['referencia', 'nombre', 'telefono', 'email', 'pedidos', 'metros', 'nivel', 'acciones']
    clasificacion_auto = obtener_config('clientes_clasificacion_automatica', 'true') == 'true'
    dashboard_config = get_dashboard_config()

    if clasificacion_auto and len(clientes_todos) >= 5:
        sorted_by_metros = sorted(clientes_todos, key=lambda c: c.total_metros, reverse=True)
        n = len(sorted_by_metros)
        try:
            top_black_pct = float(top_black)
            top_golden_pct = float(top_golden)
        except:
            top_black_pct = 5
            top_golden_pct = 20
        top_black_count = max(1, int(n * top_black_pct / 100))
        top_golden_count = max(1, int(n * top_golden_pct / 100))
        black_ids = set([c.id for c in sorted_by_metros[:top_black_count]])
        golden_ids = set([c.id for c in sorted_by_metros[:top_golden_count]])
    else:
        black_ids = set()
        golden_ids = set()
    
    black_count = sum(1 for c in clientes_todos if c.id in black_ids)
    golden_count = sum(1 for c in clientes_todos if c.id in golden_ids)
    standard_count = total_clientes - black_count - golden_count

    columnas_disponibles = [
        {'id': 'referencia', 'label': 'Referencia'},
        {'id': 'nombre', 'label': 'Nombre'},
        {'id': 'telefono', 'label': 'Teléfono'},
        {'id': 'email', 'label': 'Email'},
        {'id': 'pedidos', 'label': 'Pedidos'},
        {'id': 'metros', 'label': 'Metros'},
        {'id': 'nivel', 'label': 'Nivel'},
        {'id': 'acciones', 'label': 'Acciones'},
    ]

    context = {
        'top_black_pct': top_black,
        'top_golden_pct': top_golden,
        'total_clientes': total_clientes,
        'total_ordenes': total_ordenes,
        'black_count': black_count,
        'golden_count': golden_count,
        'standard_count': standard_count,
        'colores': colores,
        'nombres': nombres,
        'columnas_visibles': columnas,
        'columnas_disponibles': columnas_disponibles,
        'clasificacion_automatica': clasificacion_auto,
        'dashboard_config': dashboard_config,
    }
    return render_template('admin_clientes.html', **context)


# ==========================================
# CREAR CLIENTE
# ==========================================

@clientes_bp.route('/crear', methods=['GET', 'POST'])
@login_required
@comercial_or_admin_required
def crear_cliente():
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        referencia = request.form.get('referencia', '').strip()
        telefono = request.form.get('telefono', '').strip()
        email = request.form.get('email', '').strip()
        direccion = request.form.get('direccion', '').strip()
        comercial = request.form.get('comercial', '').strip()
        carnet_identidad = request.form.get('carnet_identidad', '').strip()
        fecha_nacimiento = request.form.get('fecha_nacimiento', '')
        tipo_cliente = request.form.get('tipo_cliente', 'persona')
        sector = request.form.get('sector', '').strip()
        preferencias_diseno = request.form.get('preferencias_diseno', '').strip()
        metodo_pago_favorito = request.form.get('metodo_pago_favorito', '').strip()
        referido_por = request.form.get('referido_por', '').strip()
        frecuencia_pedido = request.form.get('frecuencia_pedido', '').strip()
        notas = request.form.get('notas', '').strip()
        observaciones_internas = request.form.get('observaciones_internas', '').strip()
        etiquetas = request.form.get('etiquetas', '').strip()
        
        if not nombre:
            flash('El nombre es obligatorio.', 'danger')
            return render_template('form_cliente.html')
        
        if not referencia:
            referencia = f"CLI-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        else:
            if Client.query.filter_by(referencia=referencia).first():
                flash(f'Ya existe un cliente con la referencia "{referencia}".', 'danger')
                return render_template('form_cliente.html')
        
        cliente = Client(
            referencia=referencia,
            nombre=nombre,
            telefono=telefono,
            email=email,
            direccion=direccion,
            comercial=comercial,
            carnet_identidad=carnet_identidad,
            tipo_cliente=tipo_cliente,
            sector=sector,
            preferencias_diseno=preferencias_diseno,
            metodo_pago_favorito=metodo_pago_favorito,
            referido_por=referido_por,
            frecuencia_pedido=frecuencia_pedido,
            notas=notas,
            observaciones_internas=observaciones_internas,
            etiquetas=etiquetas,
            created_by_id=current_user.id
        )
        
        if fecha_nacimiento:
            try:
                cliente.fecha_nacimiento = datetime.strptime(fecha_nacimiento, '%Y-%m-%d').date()
            except:
                pass
        
        db.session.add(cliente)
        db.session.commit()
        
        flash(f'Cliente "{nombre}" creado correctamente.', 'success')
        return redirect(url_for('clientes.detalle_cliente', cliente_id=cliente.id))
    
    context = {
        'cliente': None,
        'total_ordenes': 0,
        'total_metros': 0,
        'nivel_actual': 'standard',
        'color_nivel': '#8e8e93',
        'nombre_nivel': 'Standard',
    }
    return render_template('form_cliente.html', **context)


# ==========================================
# EDITAR CLIENTE
# ==========================================

@clientes_bp.route('/editar/<int:cliente_id>', methods=['GET', 'POST'])
@login_required
@comercial_or_admin_required
def editar_cliente(cliente_id):
    cliente = Client.query.get_or_404(cliente_id)
    
    if request.method == 'POST':
        cliente.nombre = request.form.get('nombre', '').strip()
        cliente.referencia = request.form.get('referencia', '').strip()
        cliente.telefono = request.form.get('telefono', '').strip()
        cliente.email = request.form.get('email', '').strip()
        cliente.direccion = request.form.get('direccion', '').strip()
        cliente.comercial = request.form.get('comercial', '').strip()
        cliente.carnet_identidad = request.form.get('carnet_identidad', '').strip()
        cliente.tipo_cliente = request.form.get('tipo_cliente', 'persona')
        cliente.sector = request.form.get('sector', '').strip()
        cliente.preferencias_diseno = request.form.get('preferencias_diseno', '').strip()
        cliente.metodo_pago_favorito = request.form.get('metodo_pago_favorito', '').strip()
        cliente.referido_por = request.form.get('referido_por', '').strip()
        cliente.frecuencia_pedido = request.form.get('frecuencia_pedido', '').strip()
        cliente.notas = request.form.get('notas', '').strip()
        cliente.observaciones_internas = request.form.get('observaciones_internas', '').strip()
        cliente.etiquetas = request.form.get('etiquetas', '').strip()
        
        fecha_nacimiento = request.form.get('fecha_nacimiento', '')
        if fecha_nacimiento:
            try:
                cliente.fecha_nacimiento = datetime.strptime(fecha_nacimiento, '%Y-%m-%d').date()
            except:
                cliente.fecha_nacimiento = None
        else:
            cliente.fecha_nacimiento = None
        
        if not cliente.nombre:
            flash('El nombre es obligatorio.', 'danger')
            return render_template('form_cliente.html', cliente=cliente)
        
        if not cliente.referencia:
            cliente.referencia = f"CLI-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        else:
            existente = Client.query.filter(
                Client.referencia == cliente.referencia,
                Client.id != cliente.id
            ).first()
            if existente:
                flash(f'Ya existe otro cliente con la referencia "{cliente.referencia}".', 'danger')
                return render_template('form_cliente.html', cliente=cliente)
        
        db.session.commit()
        flash(f'Cliente "{cliente.nombre}" actualizado.', 'success')
        return redirect(url_for('clientes.detalle_cliente', cliente_id=cliente.id))
    
    orders = Order.query.filter_by(client_id=cliente_id).all()
    total_ordenes = len(orders)
    
    total_metros = 0
    for order in orders:
        for archivo in order.archivos:
            if archivo.parametros_etiqueta:
                try:
                    params = json.loads(archivo.parametros_etiqueta)
                    if params.get('consumo'):
                        total_metros += params.get('consumo', 0)
                        continue
                except:
                    pass
            if archivo.unidad in ['m', 'm2', 'm²'] and archivo.cantidad:
                total_metros += archivo.cantidad
    total_metros = round(total_metros, 2)
    
    if total_ordenes >= 50 or total_metros >= 500:
        nivel_actual = 'black'
    elif total_ordenes >= 20 or total_metros >= 200:
        nivel_actual = 'golden'
    else:
        nivel_actual = 'standard'
    
    try:
        config_colores = json.loads(obtener_config('clientes_colores_niveles', '{}'))
    except:
        config_colores = {}
    try:
        config_nombres = json.loads(obtener_config('clientes_nombres_niveles', '{}'))
    except:
        config_nombres = {}
    
    color_nivel = config_colores.get(nivel_actual, '#8e8e93')
    nombre_nivel = config_nombres.get(nivel_actual, nivel_actual.capitalize())
    
    context = {
        'cliente': cliente,
        'total_ordenes': total_ordenes,
        'total_metros': total_metros,
        'nivel_actual': nivel_actual,
        'color_nivel': color_nivel,
        'nombre_nivel': nombre_nivel,
    }
    return render_template('form_cliente.html', **context)


# ==========================================
# ELIMINAR CLIENTE
# ==========================================

@clientes_bp.route('/eliminar/<int:cliente_id>', methods=['POST'])
@login_required
@admin_required
def eliminar_cliente(cliente_id):
    cliente = Client.query.get_or_404(cliente_id)
    if cliente.orders and len(cliente.orders) > 0:
        flash(f'No se puede eliminar el cliente "{cliente.nombre}" porque tiene órdenes asociadas.', 'danger')
        return redirect(url_for('clientes.listar_clientes'))
    
    nombre = cliente.nombre
    db.session.delete(cliente)
    db.session.commit()
    flash(f'Cliente "{nombre}" eliminado.', 'success')
    return redirect(url_for('clientes.listar_clientes'))


# ==========================================
# DETALLE DE CLIENTE
# ==========================================

@clientes_bp.route('/detalle/<int:cliente_id>')
@login_required
@view_required
def detalle_cliente(cliente_id):
    cliente = Client.query.get_or_404(cliente_id)
    
    orders = Order.query.filter_by(client_id=cliente_id).all()
    orders_recientes = sorted(orders, key=lambda o: o.date if o.date else datetime.min, reverse=True)[:10]
    
    total_ordenes = len(orders)
    total_facturado = 0
    ordenes_pendientes = sum(1 for o in orders if o.column in ['pendiente', 'por-preparar', 'preparados'])
    ordenes_completadas = sum(1 for o in orders if o.column in ['entregados', 'listo'])
    
    total_metros = 0
    for order in orders:
        for archivo in order.archivos:
            if archivo.parametros_etiqueta:
                try:
                    params = json.loads(archivo.parametros_etiqueta)
                    if params.get('consumo'):
                        total_metros += params.get('consumo', 0)
                        continue
                except:
                    pass
            if archivo.unidad in ['m', 'm2', 'm²'] and archivo.cantidad:
                total_metros += archivo.cantidad
    total_metros = round(total_metros, 2)

    try:
        config_colores = json.loads(obtener_config('clientes_colores_niveles', '{}'))
    except:
        config_colores = {}
    try:
        config_nombres = json.loads(obtener_config('clientes_nombres_niveles', '{}'))
    except:
        config_nombres = {}

    if total_ordenes >= 50 or total_metros >= 500:
        nivel_actual = 'black'
    elif total_ordenes >= 20 or total_metros >= 200:
        nivel_actual = 'golden'
    else:
        nivel_actual = 'standard'
    
    color_nivel = config_colores.get(nivel_actual, '#8e8e93')
    nombre_nivel = config_nombres.get(nivel_actual, nivel_actual.capitalize())

    insights = calcular_insights_cliente(cliente)
    
    nivel_historial = []
    pedidos_acumulados = 0
    for o in sorted(orders, key=lambda x: x.date if x.date else datetime.min):
        pedidos_acumulados += 1
        if pedidos_acumulados >= 50:
            nivel = 'black'
        elif pedidos_acumulados >= 20:
            nivel = 'golden'
        else:
            nivel = 'standard'
        nivel_historial.append({
            'fecha': o.date.strftime('%Y-%m-%d') if o.date else '—',
            'nivel': nivel,
            'pedidos': pedidos_acumulados
        })
    
    ahora = datetime.now()
    meses = []
    valores = []
    for i in range(11, -1, -1):
        mes = ahora.replace(day=1) - timedelta(days=30*i)
        nombre_mes = mes.strftime('%b %Y')
        meses.append(nombre_mes)
        inicio = mes.replace(day=1).date()
        if mes.month == 12:
            fin = datetime(mes.year + 1, 1, 1).date()
        else:
            fin = datetime(mes.year, mes.month + 1, 1).date()
        count = sum(1 for o in orders if o.date and inicio <= o.date < fin)
        valores.append(count)
    
    context = {
        'cliente': cliente,
        'total_ordenes': total_ordenes,
        'total_metros': total_metros,
        'total_facturado': total_facturado,
        'ordenes_pendientes': ordenes_pendientes,
        'ordenes_completadas': ordenes_completadas,
        'frecuencia_pedido': calcular_frecuencia(orders),
        'top_servicios': insights['top_servicios'],
        'top_materiales': insights['top_materiales'],
        'top_productos': insights['top_productos'],
        'top_formatos': insights['top_formatos'],
        'evolucion_labels': meses,
        'evolucion_values': valores,
        'orders_recientes': orders_recientes,
        'nivel_historial': nivel_historial,
        'ultimo_pedido': orders[0].date if orders else None,
        'nivel_actual': nivel_actual,
        'color_nivel': color_nivel,
        'nombre_nivel': nombre_nivel,
    }
    
    return render_template('detalle_cliente.html', **context)


# ==========================================
# EXPORTAR CLIENTES
# ==========================================

@clientes_bp.route('/exportar')
@login_required
@comercial_or_admin_required
def exportar_clientes():
    clientes = Client.query.order_by(Client.nombre).all()
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Clientes'
    
    headers = [
        'ID', 'Referencia', 'Nombre', 'Teléfono', 'Email', 'Dirección',
        'Comercial', 'Carnet Identidad', 'Fecha Nacimiento',
        'Tipo Cliente', 'Sector', 'Preferencias Diseño',
        'Método Pago', 'Referido Por', 'Frecuencia Pedido',
        'Notas', 'Observaciones', 'Etiquetas', 'Pedidos'
    ]
    
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal='center')
        cell.fill = PatternFill(start_color='D3D3D3', end_color='D3D3D3', fill_type='solid')
    
    for row_idx, c in enumerate(clientes, 2):
        ws.cell(row=row_idx, column=1, value=c.id)
        ws.cell(row=row_idx, column=2, value=c.referencia)
        ws.cell(row=row_idx, column=3, value=c.nombre)
        ws.cell(row=row_idx, column=4, value=c.telefono or '')
        ws.cell(row=row_idx, column=5, value=c.email or '')
        ws.cell(row=row_idx, column=6, value=c.direccion or '')
        ws.cell(row=row_idx, column=7, value=c.comercial or '')
        ws.cell(row=row_idx, column=8, value=c.carnet_identidad or '')
        ws.cell(row=row_idx, column=9, value=c.fecha_nacimiento.strftime('%Y-%m-%d') if c.fecha_nacimiento else '')
        ws.cell(row=row_idx, column=10, value=c.tipo_cliente or '')
        ws.cell(row=row_idx, column=11, value=c.sector or '')
        ws.cell(row=row_idx, column=12, value=c.preferencias_diseno or '')
        ws.cell(row=row_idx, column=13, value=c.metodo_pago_favorito or '')
        ws.cell(row=row_idx, column=14, value=c.referido_por or '')
        ws.cell(row=row_idx, column=15, value=c.frecuencia_pedido or '')
        ws.cell(row=row_idx, column=16, value=c.notas or '')
        ws.cell(row=row_idx, column=17, value=c.observaciones_internas or '')
        ws.cell(row=row_idx, column=18, value=c.etiquetas or '')
        ws.cell(row=row_idx, column=19, value=len(c.orders) if c.orders else 0)
    
    for col in range(1, len(headers)+1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 18
    
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    
    return send_file(
        output,
        as_attachment=True,
        download_name=f'clientes_{datetime.now().strftime("%Y%m%d")}.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


# ==========================================
# IMPORTAR CLIENTES
# ==========================================

@clientes_bp.route('/importar', methods=['GET', 'POST'])
@login_required
@admin_required
def importar_clientes():
    if request.method == 'POST':
        if 'archivo' not in request.files:
            flash('No se seleccionó ningún archivo.', 'danger')
            return redirect(url_for('clientes.importar_clientes'))
        
        archivo = request.files['archivo']
        if archivo.filename == '':
            flash('No se seleccionó ningún archivo.', 'danger')
            return redirect(url_for('clientes.importar_clientes'))
        
        if not archivo.filename.endswith(('.xlsx', '.xls')):
            flash('Formato no soportado. Use .xlsx o .xls', 'danger')
            return redirect(url_for('clientes.importar_clientes'))
        
        try:
            wb = openpyxl.load_workbook(archivo)
            ws = wb.active
            
            headers = [cell.value.strip() if cell.value else '' for cell in ws[1]]
            col_map = {}
            for idx, h in enumerate(headers):
                h_clean = h.lower().replace(' ', '_').replace('(', '').replace(')', '').replace('ñ', 'n')
                if 'nombre' in h_clean:
                    col_map['nombre'] = idx
                elif 'referencia' in h_clean:
                    col_map['referencia'] = idx
                elif 'telefono' in h_clean:
                    col_map['telefono'] = idx
                elif 'email' in h_clean:
                    col_map['email'] = idx
                elif 'direccion' in h_clean:
                    col_map['direccion'] = idx
                elif 'comercial' in h_clean:
                    col_map['comercial'] = idx
                elif 'carnet' in h_clean or 'identidad' in h_clean:
                    col_map['carnet_identidad'] = idx
                elif 'fecha_nacimiento' in h_clean or 'fecha nacimiento' in h_clean:
                    col_map['fecha_nacimiento'] = idx
                elif 'tipo_cliente' in h_clean or 'tipo cliente' in h_clean:
                    col_map['tipo_cliente'] = idx
                elif 'sector' in h_clean:
                    col_map['sector'] = idx
                elif 'preferencias' in h_clean:
                    col_map['preferencias_diseno'] = idx
                elif 'metodo_pago' in h_clean or 'método pago' in h_clean:
                    col_map['metodo_pago_favorito'] = idx
                elif 'referido_por' in h_clean or 'referido' in h_clean:
                    col_map['referido_por'] = idx
                elif 'frecuencia_pedido' in h_clean or 'frecuencia' in h_clean:
                    col_map['frecuencia_pedido'] = idx
                elif 'notas' in h_clean:
                    col_map['notas'] = idx
                elif 'observaciones' in h_clean:
                    col_map['observaciones_internas'] = idx
                elif 'etiquetas' in h_clean:
                    col_map['etiquetas'] = idx
            
            if 'nombre' not in col_map:
                flash('El archivo debe contener una columna "Nombre".', 'danger')
                return redirect(url_for('clientes.importar_clientes'))
            
            contador = 0
            actualizados = 0
            
            for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                if not row or not any(row):
                    continue
                
                nombre = str(row[col_map['nombre']]).strip() if col_map.get('nombre') is not None and row[col_map['nombre']] else ''
                if not nombre:
                    continue
                
                referencia = None
                if col_map.get('referencia') is not None and row[col_map['referencia']]:
                    referencia = str(row[col_map['referencia']]).strip()
                
                cliente = None
                if referencia:
                    cliente = Client.query.filter_by(referencia=referencia).first()
                if not cliente:
                    cliente = Client.query.filter_by(nombre=nombre).first()
                
                if cliente:
                    if col_map.get('telefono') is not None and row[col_map['telefono']]:
                        cliente.telefono = str(row[col_map['telefono']]).strip()
                    if col_map.get('email') is not None and row[col_map['email']]:
                        cliente.email = str(row[col_map['email']]).strip()
                    if col_map.get('direccion') is not None and row[col_map['direccion']]:
                        cliente.direccion = str(row[col_map['direccion']]).strip()
                    if col_map.get('comercial') is not None and row[col_map['comercial']]:
                        cliente.comercial = str(row[col_map['comercial']]).strip()
                    if col_map.get('carnet_identidad') is not None and row[col_map['carnet_identidad']]:
                        cliente.carnet_identidad = str(row[col_map['carnet_identidad']]).strip()
                    if col_map.get('tipo_cliente') is not None and row[col_map['tipo_cliente']]:
                        cliente.tipo_cliente = str(row[col_map['tipo_cliente']]).strip()
                    if col_map.get('sector') is not None and row[col_map['sector']]:
                        cliente.sector = str(row[col_map['sector']]).strip()
                    if col_map.get('preferencias_diseno') is not None and row[col_map['preferencias_diseno']]:
                        cliente.preferencias_diseno = str(row[col_map['preferencias_diseno']]).strip()
                    if col_map.get('metodo_pago_favorito') is not None and row[col_map['metodo_pago_favorito']]:
                        cliente.metodo_pago_favorito = str(row[col_map['metodo_pago_favorito']]).strip()
                    if col_map.get('referido_por') is not None and row[col_map['referido_por']]:
                        cliente.referido_por = str(row[col_map['referido_por']]).strip()
                    if col_map.get('frecuencia_pedido') is not None and row[col_map['frecuencia_pedido']]:
                        cliente.frecuencia_pedido = str(row[col_map['frecuencia_pedido']]).strip()
                    if col_map.get('notas') is not None and row[col_map['notas']]:
                        cliente.notas = str(row[col_map['notas']]).strip()
                    if col_map.get('observaciones_internas') is not None and row[col_map['observaciones_internas']]:
                        cliente.observaciones_internas = str(row[col_map['observaciones_internas']]).strip()
                    if col_map.get('etiquetas') is not None and row[col_map['etiquetas']]:
                        cliente.etiquetas = str(row[col_map['etiquetas']]).strip()
                    
                    if col_map.get('fecha_nacimiento') is not None and row[col_map['fecha_nacimiento']]:
                        try:
                            val = row[col_map['fecha_nacimiento']]
                            if isinstance(val, datetime):
                                cliente.fecha_nacimiento = val.date()
                            elif isinstance(val, (int, float)):
                                from datetime import date
                                cliente.fecha_nacimiento = date(1899, 12, 30) + timedelta(days=int(val))
                            else:
                                cliente.fecha_nacimiento = datetime.strptime(str(val), '%Y-%m-%d').date()
                        except:
                            pass
                    
                    cliente.updated_at = datetime.now()
                    actualizados += 1
                else:
                    nuevo = Client(nombre=nombre)
                    if referencia:
                        nuevo.referencia = referencia
                    else:
                        nuevo.referencia = f"CLI-{datetime.now().strftime('%Y%m%d%H%M%S')}-{row_idx}"
                    
                    if col_map.get('telefono') is not None and row[col_map['telefono']]:
                        nuevo.telefono = str(row[col_map['telefono']]).strip()
                    if col_map.get('email') is not None and row[col_map['email']]:
                        nuevo.email = str(row[col_map['email']]).strip()
                    if col_map.get('direccion') is not None and row[col_map['direccion']]:
                        nuevo.direccion = str(row[col_map['direccion']]).strip()
                    if col_map.get('comercial') is not None and row[col_map['comercial']]:
                        nuevo.comercial = str(row[col_map['comercial']]).strip()
                    if col_map.get('carnet_identidad') is not None and row[col_map['carnet_identidad']]:
                        nuevo.carnet_identidad = str(row[col_map['carnet_identidad']]).strip()
                    if col_map.get('tipo_cliente') is not None and row[col_map['tipo_cliente']]:
                        nuevo.tipo_cliente = str(row[col_map['tipo_cliente']]).strip()
                    if col_map.get('sector') is not None and row[col_map['sector']]:
                        nuevo.sector = str(row[col_map['sector']]).strip()
                    if col_map.get('preferencias_diseno') is not None and row[col_map['preferencias_diseno']]:
                        nuevo.preferencias_diseno = str(row[col_map['preferencias_diseno']]).strip()
                    if col_map.get('metodo_pago_favorito') is not None and row[col_map['metodo_pago_favorito']]:
                        nuevo.metodo_pago_favorito = str(row[col_map['metodo_pago_favorito']]).strip()
                    if col_map.get('referido_por') is not None and row[col_map['referido_por']]:
                        nuevo.referido_por = str(row[col_map['referido_por']]).strip()
                    if col_map.get('frecuencia_pedido') is not None and row[col_map['frecuencia_pedido']]:
                        nuevo.frecuencia_pedido = str(row[col_map['frecuencia_pedido']]).strip()
                    if col_map.get('notas') is not None and row[col_map['notas']]:
                        nuevo.notas = str(row[col_map['notas']]).strip()
                    if col_map.get('observaciones_internas') is not None and row[col_map['observaciones_internas']]:
                        nuevo.observaciones_internas = str(row[col_map['observaciones_internas']]).strip()
                    if col_map.get('etiquetas') is not None and row[col_map['etiquetas']]:
                        nuevo.etiquetas = str(row[col_map['etiquetas']]).strip()
                    
                    if col_map.get('fecha_nacimiento') is not None and row[col_map['fecha_nacimiento']]:
                        try:
                            val = row[col_map['fecha_nacimiento']]
                            if isinstance(val, datetime):
                                nuevo.fecha_nacimiento = val.date()
                            elif isinstance(val, (int, float)):
                                from datetime import date
                                nuevo.fecha_nacimiento = date(1899, 12, 30) + timedelta(days=int(val))
                            else:
                                nuevo.fecha_nacimiento = datetime.strptime(str(val), '%Y-%m-%d').date()
                        except:
                            pass
                    
                    nuevo.created_by_id = current_user.id
                    db.session.add(nuevo)
                    contador += 1
            
            db.session.commit()
            flash(f'Importación completada: {contador} nuevos, {actualizados} actualizados.', 'success')
            return redirect(url_for('clientes.listar_clientes'))
        
        except Exception as e:
            db.session.rollback()
            flash(f'Error al importar: {str(e)}', 'danger')
            return redirect(url_for('clientes.importar_clientes'))
    
    return render_template('importar_clientes.html')


# ==========================================
# DESCARGAR PLANTILLA
# ==========================================

@clientes_bp.route('/descargar-plantilla')
@login_required
@admin_required
def descargar_plantilla():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Clientes'
    
    headers = [
        'Nombre', 'Referencia', 'Teléfono', 'Email', 'Dirección',
        'Comercial', 'Carnet de Identidad', 'Fecha Nacimiento',
        'Tipo Cliente', 'Sector', 'Preferencias de Diseño',
        'Método Pago Favorito', 'Referido Por', 'Frecuencia Pedido',
        'Notas', 'Observaciones Internas', 'Etiquetas'
    ]
    
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal='center')
        cell.fill = PatternFill(start_color='E8E0D8', end_color='E8E0D8', fill_type='solid')
    
    for col in range(1, len(headers)+1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 22
    
    ejemplo = [
        'Cliente Ejemplo', 'CLI-001', '555-1234', 'cliente@ejemplo.com', 'Calle Principal 123',
        'Comercial 1', '12345678', '1990-01-15', 'persona', 'Retail',
        'Moderno, minimalista', 'Transferencia', 'Juan Pérez', 'Mensual',
        'Cliente frecuente', 'Prefiere atención personalizada', 'VIP, Premium'
    ]
    
    for col, value in enumerate(ejemplo, 1):
        ws.cell(row=2, column=col, value=value)
        ws.cell(row=2, column=col).alignment = Alignment(horizontal='left')
    
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    
    return send_file(
        output,
        as_attachment=True,
        download_name='plantilla_clientes.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )