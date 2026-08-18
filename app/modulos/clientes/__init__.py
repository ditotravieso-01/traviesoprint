from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import login_required, current_user
from app.models import Client, User, Order, ArchivoAdjunto, Producto
from app import db
from datetime import datetime, timedelta
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
            flash('No tienes permiso para acceder a clientes.', 'danger')
            return redirect(url_for('home.home'))
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
# FUNCIONES AUXILIARES DE NIVELES
# ==========================================

def calcular_nivel_cliente(cliente, top_black_ids, top_golden_ids):
    if cliente.id in top_black_ids:
        return 'black'
    elif cliente.id in top_golden_ids:
        return 'golden'
    return 'standard'

def get_nivel_info(nivel):
    niveles = {
        'black': {
            'clase': 'nivel-black',
            'color': '#1a1a1a',
            'fondo': '#1a1a1a',
            'texto': '#d4a574',
            'borde': '#d4a574',
            'icono': 'fa-crown',
            'label': 'Black',
            'badge': '🔥'
        },
        'golden': {
            'clase': 'nivel-golden',
            'color': '#d4a574',
            'fondo': '#fef9e7',
            'texto': '#b8860b',
            'borde': '#d4a574',
            'icono': 'fa-star',
            'label': 'Golden',
            'badge': '⭐'
        },
        'standard': {
            'clase': 'nivel-standard',
            'color': '#8e8e93',
            'fondo': '#ffffff',
            'texto': '#1c1c1e',
            'borde': '#f0ece8',
            'icono': 'fa-user',
            'label': 'Standard',
            'badge': '👤'
        }
    }
    return niveles.get(nivel, niveles['standard'])

# ==========================================
# INSIGHTS DEL CLIENTE (aprendizaje automático)
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
    fechas = sorted(o.date for o in orders if o.date)
    if len(fechas) < 2:
        return 'eventual'
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
# LISTAR CLIENTES (con dashboard, niveles y KPIs)
# ==========================================

@clientes_bp.route('/')
@login_required
@comercial_or_admin_required
def listar_clientes():
    search = request.args.get('search', '').strip()
    sort = request.args.get('sort', 'nombre')
    order = request.args.get('order', 'asc')
    
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
    
    if sort == 'nombre':
        col = Client.nombre
    elif sort == 'referencia':
        col = Client.referencia
    elif sort == 'telefono':
        col = Client.telefono
    elif sort == 'email':
        col = Client.email
    elif sort == 'total_facturado':
        col = Client.total_facturado
    else:
        col = Client.nombre
    
    if order == 'desc':
        query = query.order_by(col.desc())
    else:
        query = query.order_by(col.asc())
    
    clients = query.all()
    
    # ==========================================
    # KPIs DEL DASHBOARD
    # ==========================================
    total_clientes = len(clients)
    total_ordenes = db.session.query(func.count(Order.id)).filter(Order.client_id.in_([c.id for c in clients])).scalar() or 0
    clientes_activos = db.session.query(func.count(func.distinct(Order.client_id))).filter(
        Order.date >= datetime.now() - timedelta(days=30)
    ).scalar() or 0
    total_facturado = sum(c.total_facturado or 0 for c in clients)
    top_cliente = max(clients, key=lambda c: c.total_facturado or 0) if clients else None
    top_cliente_nombre = top_cliente.nombre if top_cliente else '—'
    top_cliente_monto = top_cliente.total_facturado or 0 if top_cliente else 0
    
    # Clientes inactivos (60 días sin pedidos)
    fecha_limite = datetime.now() - timedelta(days=60)
    clientes_inactivos = 0
    for c in clients:
        ultimo_pedido = Order.query.filter_by(client_id=c.id).order_by(Order.date.desc()).first()
        if not ultimo_pedido or ultimo_pedido.date < fecha_limite.date():
            clientes_inactivos += 1
    
    # Clientes nuevos (últimos 30 días)
    fecha_inicio_mes = datetime.now().replace(day=1)
    clientes_nuevos = sum(1 for c in clients if c.created_at and c.created_at >= fecha_inicio_mes)
    
    # ==========================================
    # CÁLCULO DE NIVELES (Black, Golden, Standard)
    # ==========================================
    # Solo asignar niveles si hay al menos 5 clientes con actividad (pedidos o facturación)
    clientes_con_datos = [c for c in clients if len(c.orders) > 0 or (c.total_facturado or 0) > 0]
    
    if len(clientes_con_datos) >= 5:
        sorted_by_facturacion = sorted(clientes_con_datos, key=lambda c: c.total_facturado or 0, reverse=True)
        sorted_by_pedidos = sorted(clientes_con_datos, key=lambda c: len(c.orders) if c.orders else 0, reverse=True)
        n = len(clientes_con_datos)
        top_5 = max(1, int(n * 0.05))
        top_20 = max(1, int(n * 0.20))
        top_black_ids = set([c.id for c in sorted_by_facturacion[:top_5]] + [c.id for c in sorted_by_pedidos[:top_5]])
        top_golden_ids = set([c.id for c in sorted_by_facturacion[:top_20]] + [c.id for c in sorted_by_pedidos[:top_20]])
    else:
        top_black_ids = set()
        top_golden_ids = set()
    
    # Asignar nivel a cada cliente y calcular insights
    for c in clients:
        c.nivel = calcular_nivel_cliente(c, top_black_ids, top_golden_ids)
        c.nivel_info = get_nivel_info(c.nivel)
        insights = calcular_insights_cliente(c)
        c.top_materiales = insights['top_materiales'][:2]
        c.top_servicios = insights['top_servicios'][:2]
        c.total_pedidos = len(c.orders) if c.orders else 0
        c.frecuencia = insights['frecuencia']
        ultimo_pedido = Order.query.filter_by(client_id=c.id).order_by(Order.date.desc()).first()
        c.ultimo_pedido_fecha = ultimo_pedido.date if ultimo_pedido else None
    
    # ==========================================
    # EVOLUCIÓN DE CLIENTES NUEVOS (últimos 12 meses)
    # ==========================================
    ahora = datetime.now()
    meses = []
    valores = []
    for i in range(11, -1, -1):
        mes = ahora.replace(day=1) - timedelta(days=30*i)
        nombre_mes = mes.strftime('%b %Y')
        meses.append(nombre_mes)
        inicio = mes.replace(day=1)
        fin = (inicio + timedelta(days=32)).replace(day=1)
        count = sum(1 for c in clients if c.created_at and inicio <= c.created_at < fin)
        valores.append(count)
    
    evolucion_data = {
        'labels': meses,
        'values': valores
    }
    
    # ==========================================
    # CONTEXTO PARA EL TEMPLATE
    # ==========================================
    context = {
        'clients': clients,
        'search': search,
        'sort': sort,
        'order': order,
        # KPIs
        'total_clientes': total_clientes,
        'total_ordenes': total_ordenes,
        'clientes_activos': clientes_activos,
        'clientes_inactivos': clientes_inactivos,
        'clientes_nuevos': clientes_nuevos,
        'total_facturado': total_facturado,
        'top_cliente_nombre': top_cliente_nombre,
        'top_cliente_monto': top_cliente_monto,
        'evolucion_data': evolucion_data,
        # Conteos por nivel
        'black_count': sum(1 for c in clients if c.nivel == 'black'),
        'golden_count': sum(1 for c in clients if c.nivel == 'golden'),
        'standard_count': sum(1 for c in clients if c.nivel == 'standard'),
    }
    
    return render_template('clientes.html', **context)

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
        return redirect(url_for('clientes.listar_clientes'))
    
    return render_template('form_cliente.html')

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
        
        existente = Client.query.filter(
            Client.referencia == cliente.referencia,
            Client.id != cliente.id
        ).first()
        if existente:
            flash(f'Ya existe otro cliente con la referencia "{cliente.referencia}".', 'danger')
            return render_template('form_cliente.html', cliente=cliente)
        
        db.session.commit()
        flash(f'Cliente "{cliente.nombre}" actualizado.', 'success')
        return redirect(url_for('clientes.listar_clientes'))
    
    return render_template('form_cliente.html', cliente=cliente)

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
@comercial_or_admin_required
def detalle_cliente(cliente_id):
    cliente = Client.query.get_or_404(cliente_id)
    
    orders = Order.query.filter_by(client_id=cliente_id).all()
    orders_recientes = sorted(orders, key=lambda o: o.date if o.date else datetime.min, reverse=True)[:10]
    
    total_ordenes = len(orders)
    total_facturado = sum(o.total_facturado or 0 for o in orders)
    ordenes_pendientes = sum(1 for o in orders if o.column in ['pendiente', 'por-preparar', 'preparados'])
    ordenes_completadas = sum(1 for o in orders if o.column in ['entregados', 'listo'])
    
    insights = calcular_insights_cliente(cliente)
    
    # Calcular evolución del nivel en el tiempo (basado en pedidos)
    nivel_historial = []
    pedidos_acumulados = 0
    facturacion_acumulada = 0
    for o in sorted(orders, key=lambda x: x.date if x.date else datetime.min):
        pedidos_acumulados += 1
        facturacion_acumulada += o.total_facturado or 0
        if pedidos_acumulados >= 50 or facturacion_acumulada >= 10000:
            nivel = 'black'
        elif pedidos_acumulados >= 20 or facturacion_acumulada >= 5000:
            nivel = 'golden'
        else:
            nivel = 'standard'
        nivel_historial.append({
            'fecha': o.date.strftime('%Y-%m-%d') if o.date else '—',
            'nivel': nivel,
            'pedidos': pedidos_acumulados,
            'facturado': facturacion_acumulada
        })
    
    # Evolución mensual de pedidos
    ahora = datetime.now()
    meses = []
    valores = []
    for i in range(11, -1, -1):
        mes = ahora.replace(day=1) - timedelta(days=30*i)
        nombre_mes = mes.strftime('%b %Y')
        meses.append(nombre_mes)
        inicio = mes.replace(day=1)
        fin = (inicio + timedelta(days=32)).replace(day=1)
        count = sum(1 for o in orders if o.date and inicio <= o.date < fin)
        valores.append(count)
    
    context = {
        'cliente': cliente,
        'total_ordenes': total_ordenes,
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
        'Notas', 'Observaciones', 'Etiquetas', 'Pedidos', 'Total Facturado'
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
        ws.cell(row=row_idx, column=20, value=round(c.total_facturado, 2) if c.total_facturado else 0)
    
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