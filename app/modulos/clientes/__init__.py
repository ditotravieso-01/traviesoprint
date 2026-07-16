from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, jsonify, current_app
from flask_login import login_required, current_user
from app.models import Client, Order, ArchivoAdjunto
from app import db
from datetime import datetime, timedelta
import json
import io
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill
from werkzeug.utils import secure_filename
import os
import tempfile

clientes_bp = Blueprint('clientes', __name__, url_prefix='/clientes', template_folder='templates')

# ==========================================
# DECORADOR DE PERMISOS
# ==========================================
def comercial_or_admin_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if current_user.role not in ['comercial', 'admin']:
            flash('No tienes permiso.', 'danger')
            return redirect(url_for('home.home'))
        return func(*args, **kwargs)
    return wrapper

# ==========================================
# LISTAR CLIENTES (CON PAGINACIÓN Y BÚSQUEDA)
# ==========================================
@clientes_bp.route('/')
@login_required
@comercial_or_admin_required
def list_clientes():
    page = request.args.get('page', 1, type=int)
    per_page = 40
    search = request.args.get('search', '').strip()
    tipo = request.args.get('tipo', '').strip()
    sort_by = request.args.get('sort_by', 'nombre')  # columna por defecto
    order = request.args.get('order', 'asc')  # asc o desc

    # Validar sort_by permitidos
    allowed_sort = ['referencia', 'nombre', 'telefono', 'tipo_cliente', 'comercial', 'pedidos']
    if sort_by not in allowed_sort:
        sort_by = 'nombre'
    if order not in ['asc', 'desc']:
        order = 'asc'

    query = Client.query
    if search:
        query = query.filter(
            db.or_(
                Client.nombre.ilike(f'%{search}%'),
                Client.referencia.ilike(f'%{search}%'),
                Client.telefono.ilike(f'%{search}%'),
                Client.comercial.ilike(f'%{search}%')
            )
        )
    if tipo:
        query = query.filter_by(tipo_cliente=tipo)

    # Ordenamiento
    if sort_by == 'pedidos':
        # Subconsulta para contar órdenes
        from sqlalchemy import func
        subq = db.session.query(Order.client_id, func.count(Order.id).label('num_orders')).group_by(Order.client_id).subquery()
        query = query.outerjoin(subq, Client.id == subq.c.client_id)
        if order == 'asc':
            query = query.order_by(db.func.coalesce(subq.c.num_orders, 0).asc())
        else:
            query = query.order_by(db.func.coalesce(subq.c.num_orders, 0).desc())
    else:
        # Orden directo por columna
        column = getattr(Client, sort_by)
        if order == 'asc':
            query = query.order_by(column.asc())
        else:
            query = query.order_by(column.desc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    clientes = pagination.items

    tipos = db.session.query(Client.tipo_cliente).distinct().all()
    tipos = [t[0] for t in tipos if t[0]]

    return render_template('list_clientes.html',
                           clientes=clientes,
                           pagination=pagination,
                           search=search,
                           tipo=tipo,
                           tipos=tipos,
                           sort_by=sort_by,
                           order=order)

# ==========================================
# DETALLE DEL CLIENTE (CON ÓRDENES ASOCIADAS)
# ==========================================
@clientes_bp.route('/detalle/<int:cliente_id>')
@login_required
@comercial_or_admin_required
def detalle_cliente(cliente_id):
    cliente = Client.query.get_or_404(cliente_id)
    orders = Order.query.filter_by(client_id=cliente.id).order_by(Order.date.desc()).all()

    # Estadísticas
    total_pedidos = len(orders)
    total_facturado = sum(float(o.total_facturado) if hasattr(o, 'total_facturado') and o.total_facturado else 0 for o in orders) or 0
    ultimo_pedido = orders[0].date if orders else None

    # Datos para el gráfico: agrupar pedidos por mes
    from collections import defaultdict
    from datetime import datetime
    meses = defaultdict(int)
    for order in orders:
        if order.date:
            mes_key = order.date.strftime('%Y-%m')
            meses[mes_key] += 1

    # Ordenar por fecha
    chart_labels = sorted(meses.keys())
    chart_data = [meses[m] for m in chart_labels]

    return render_template('detalle_cliente.html',
                           cliente=cliente,
                           orders=orders,
                           total_pedidos=total_pedidos,
                           total_facturado=total_facturado,
                           ultimo_pedido=ultimo_pedido,
                           chart_labels=chart_labels,
                           chart_data=chart_data)

# ==========================================
# CREAR / EDITAR CLIENTE (formulario)
# ==========================================
@clientes_bp.route('/crear', methods=['GET', 'POST'])
@login_required
@comercial_or_admin_required
def crear_cliente():
    return _form_cliente()

@clientes_bp.route('/editar/<int:cliente_id>', methods=['GET', 'POST'])
@login_required
@comercial_or_admin_required
def editar_cliente(cliente_id):
    cliente = Client.query.get_or_404(cliente_id)
    return _form_cliente(cliente)

@clientes_bp.route('/duplicar/<int:cliente_id>')
@login_required
@comercial_or_admin_required
def duplicar_cliente(cliente_id):
    cliente = Client.query.get_or_404(cliente_id)
    # Crear una copia en memoria (sin ID)
    nuevo_cliente = Client()
    # Copiar todos los campos excepto id, referencia, created_at, updated_at
    for column in cliente.__table__.columns:
        if column.name not in ['id', 'referencia', 'created_at', 'updated_at', 'created_by_id']:
            setattr(nuevo_cliente, column.name, getattr(cliente, column.name))
    # Generar nueva referencia
    nuevo_cliente.referencia = f"CLI-{datetime.now().strftime('%Y%m%d%H%M%S')}{Client.query.count()+1}"
    # Limpiar el nombre para evitar duplicados exactos
    nuevo_cliente.nombre = f"{cliente.nombre} (copia)"

    # Guardar en la sesión para pre-llenar el formulario
    # Usamos un formulario GET con parámetros
    return redirect(url_for('clientes.crear_cliente', **{
        'nombre': nuevo_cliente.nombre,
        'telefono': nuevo_cliente.telefono or '',
        'email': nuevo_cliente.email or '',
        'direccion': nuevo_cliente.direccion or '',
        'tipo_cliente': nuevo_cliente.tipo_cliente or 'persona',
        'carnet_identidad': nuevo_cliente.carnet_identidad or '',
        'sector': nuevo_cliente.sector or '',
        'comercial': nuevo_cliente.comercial or '',
        'metodo_pago_favorito': nuevo_cliente.metodo_pago_favorito or '',
        'frecuencia_pedido': nuevo_cliente.frecuencia_pedido or '',
        'referido_por': nuevo_cliente.referido_por or '',
        'gustos': nuevo_cliente.gustos or '',
        'preferencias_diseno': nuevo_cliente.preferencias_diseno or '',
        'observaciones_internas': nuevo_cliente.observaciones_internas or '',
        'notas': nuevo_cliente.notas or '',
    }))

def _form_cliente(cliente=None):
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        if not nombre:
            flash('El nombre es obligatorio.', 'danger')
            return render_template('form_cliente.html', cliente=cliente)

        # Si es nuevo, generar referencia automática
        if not cliente:
            referencia = request.form.get('referencia', '').strip()
            if not referencia:
                referencia = f"CLI-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            # Verificar que la referencia no exista
            if Client.query.filter_by(referencia=referencia).first():
                flash(f'La referencia {referencia} ya existe. Generando una nueva...', 'warning')
                referencia = f"CLI-{datetime.now().strftime('%Y%m%d%H%M%S')}{Client.query.count()+1}"
        else:
            referencia = cliente.referencia

        # Recolectar datos
        data = {
            'referencia': referencia,
            'nombre': nombre,
            'telefono': request.form.get('telefono', '').strip(),
            'email': request.form.get('email', '').strip(),
            'direccion': request.form.get('direccion', '').strip(),
            'etiquetas': request.form.get('etiquetas', '').strip(),
            'pedidos_venta': int(request.form.get('pedidos_venta', 0)),
            'total_facturado': float(request.form.get('total_facturado', 0) or 0),
            'gustos': request.form.get('gustos', '').strip(),
            'notas': request.form.get('notas', '').strip(),
            'carnet_identidad': request.form.get('carnet_identidad', '').strip(),
            'tipo_cliente': request.form.get('tipo_cliente', 'persona'),
            'sector': request.form.get('sector', '').strip(),
            'preferencias_diseno': request.form.get('preferencias_diseno', '').strip(),
            'metodo_pago_favorito': request.form.get('metodo_pago_favorito', '').strip(),
            'referido_por': request.form.get('referido_por', '').strip(),
            'frecuencia_pedido': request.form.get('frecuencia_pedido', '').strip(),
            'observaciones_internas': request.form.get('observaciones_internas', '').strip(),
            'comercial': request.form.get('comercial', '').strip(),
        }
        # Fecha de nacimiento (si se proporciona)
        fecha_nac = request.form.get('fecha_nacimiento')
        if fecha_nac:
            try:
                data['fecha_nacimiento'] = datetime.strptime(fecha_nac, '%Y-%m-%d').date()
            except:
                pass

        if cliente:
            # Actualizar
            for key, value in data.items():
                setattr(cliente, key, value)
            cliente.updated_at = datetime.now()
            flash('Cliente actualizado correctamente.', 'success')
        else:
            nuevo = Client(**data)
            nuevo.created_by_id = current_user.id
            db.session.add(nuevo)
            flash('Cliente creado correctamente.', 'success')

        db.session.commit()
        return redirect(url_for('clientes.detalle_cliente', cliente_id=(cliente.id if cliente else nuevo.id)))

    # ==========================================
    # GET: si hay parámetros en la URL y es modo creación (cliente None)
    # ==========================================
    if not cliente and request.args:
        # Crear un objeto cliente temporal para pre-llenar el formulario
        temp_cliente = Client()
        for key, value in request.args.items():
            if hasattr(temp_cliente, key):
                # Manejar fecha de nacimiento
                if key == 'fecha_nacimiento' and value:
                    try:
                        setattr(temp_cliente, key, datetime.strptime(value, '%Y-%m-%d').date())
                    except:
                        pass
                else:
                    setattr(temp_cliente, key, value)
        # Asegurar que 'nombre' se asigne correctamente (ya viene en args)
        return render_template('form_cliente.html', cliente=temp_cliente)

    # GET normal (sin parámetros o modo edición)
    return render_template('form_cliente.html', cliente=cliente)

# ==========================================
# ELIMINAR CLIENTE (individual)
# ==========================================
@clientes_bp.route('/eliminar/<int:cliente_id>', methods=['POST'])
@login_required
def eliminar_cliente(cliente_id):
    if current_user.role not in ['admin']:
        flash('Solo administradores pueden eliminar clientes.', 'danger')
        return redirect(url_for('clientes.list_clientes'))
    cliente = Client.query.get_or_404(cliente_id)
    # Verificar si tiene órdenes
    if cliente.orders:
        flash('No se puede eliminar un cliente con órdenes asociadas.', 'danger')
        return redirect(url_for('clientes.detalle_cliente', cliente_id=cliente.id))
    db.session.delete(cliente)
    db.session.commit()
    flash('Cliente eliminado correctamente.', 'success')
    return redirect(url_for('clientes.list_clientes'))

# ==========================================
# ACCIONES MASIVAS (selección múltiple)
# ==========================================
@clientes_bp.route('/accion-masiva', methods=['POST'])
@login_required
@comercial_or_admin_required
def accion_masiva():
    accion = request.form.get('accion')
    ids = request.form.getlist('ids[]')
    if not ids:
        flash('No se seleccionó ningún cliente.', 'warning')
        return redirect(url_for('clientes.list_clientes'))

    ids = [int(id) for id in ids if id.isdigit()]

    if accion == 'eliminar':
        if current_user.role not in ['admin']:
            flash('Solo administradores pueden eliminar clientes.', 'danger')
            return redirect(url_for('clientes.list_clientes'))
        # Verificar que ninguno tenga órdenes
        clientes = Client.query.filter(Client.id.in_(ids)).all()
        for c in clientes:
            if c.orders:
                flash(f'El cliente "{c.nombre}" tiene órdenes y no puede eliminarse.', 'danger')
                return redirect(url_for('clientes.list_clientes'))
        # Eliminar
        Client.query.filter(Client.id.in_(ids)).delete(synchronize_session=False)
        db.session.commit()
        flash(f'{len(ids)} clientes eliminados.', 'success')
        return redirect(url_for('clientes.list_clientes'))

    elif accion == 'exportar':
        return exportar_seleccionados(ids)

    flash('Acción no válida.', 'danger')
    return redirect(url_for('clientes.list_clientes'))

# ==========================================
# EXPORTAR SELECCIONADOS A EXCEL
# ==========================================
def exportar_seleccionados(ids):
    clientes = Client.query.filter(Client.id.in_(ids)).all()
    if not clientes:
        flash('No hay clientes para exportar.', 'warning')
        return redirect(url_for('clientes.list_clientes'))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Clientes'

    # Encabezados
    headers = ['Referencia', 'Nombre', 'Teléfono', 'Email', 'Dirección', 'Etiquetas',
               'Pedidos Venta', 'Total Facturado', 'Gustos', 'Notas', 'Carnet Identidad',
               'Fecha Nacimiento', 'Tipo Cliente', 'Sector', 'Preferencias Diseño',
               'Método Pago', 'Referido Por', 'Frecuencia Pedido', 'Último Pedido',
               'Observaciones Internas', 'Comercial']  # NUEVO
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.fill = PatternFill(start_color='D3D3D3', end_color='D3D3D3', fill_type='solid')

    # Datos
    for row, cliente in enumerate(clientes, 2):
        ws.cell(row=row, column=1, value=cliente.referencia)
        ws.cell(row=row, column=2, value=cliente.nombre)
        ws.cell(row=row, column=3, value=cliente.telefono or '')
        ws.cell(row=row, column=4, value=cliente.email or '')
        ws.cell(row=row, column=5, value=cliente.direccion or '')
        ws.cell(row=row, column=6, value=cliente.etiquetas or '')
        ws.cell(row=row, column=7, value=cliente.pedidos_venta or 0)
        ws.cell(row=row, column=8, value=cliente.total_facturado or 0.0)
        ws.cell(row=row, column=9, value=cliente.gustos or '')
        ws.cell(row=row, column=10, value=cliente.notas or '')
        ws.cell(row=row, column=11, value=cliente.carnet_identidad or '')
        ws.cell(row=row, column=12, value=cliente.fecha_nacimiento.strftime('%Y-%m-%d') if cliente.fecha_nacimiento else '')
        ws.cell(row=row, column=13, value=cliente.tipo_cliente or '')
        ws.cell(row=row, column=14, value=cliente.sector or '')
        ws.cell(row=row, column=15, value=cliente.preferencias_diseno or '')
        ws.cell(row=row, column=16, value=cliente.metodo_pago_favorito or '')
        ws.cell(row=row, column=17, value=cliente.referido_por or '')
        ws.cell(row=row, column=18, value=cliente.frecuencia_pedido or '')
        ws.cell(row=row, column=19, value=cliente.ultimo_pedido.strftime('%Y-%m-%d') if cliente.ultimo_pedido else '')
        ws.cell(row=row, column=20, value=cliente.observaciones_internas or '')
        ws.cell(row=row, column=21, value=cliente.comercial or '')  # NUEVO

    # Ajustar anchos
    for col in range(1, len(headers)+1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 20

    # Guardar en BytesIO
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(output,
                     as_attachment=True,
                     download_name=f'clientes_seleccionados_{datetime.now().strftime("%Y%m%d")}.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

# ==========================================
# IMPORTAR CLIENTES DESDE EXCEL
# ==========================================
@clientes_bp.route('/importar', methods=['GET', 'POST'])
@login_required
@comercial_or_admin_required
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

            # Leer encabezados (primera fila)
            headers = []
            for cell in ws[1]:
                headers.append(cell.value.strip() if cell.value else '')

            # Mapear columnas esperadas (versión mejorada con más variantes)
            col_map = {}
            for idx, h in enumerate(headers):
                h_clean = h.lower().replace(' ', '_').replace('(', '').replace(')', '').replace('ñ', 'n')
                
                # Referencia
                if h_clean in ['referencia', 'ref', 'código', 'codigo', 'id']:
                    col_map['referencia'] = idx
                # Nombre (clave principal)
                elif h_clean in ['nombre', 'cliente', 'razón_social', 'razon_social', 'nombre_completo', 'nombre completo']:
                    col_map['nombre'] = idx
                # Teléfono
                elif h_clean in ['teléfono', 'telefono', 'celular', 'cel', 'móvil', 'movil']:
                    col_map['telefono'] = idx
                # Email
                elif h_clean in ['email', 'correo', 'e-mail']:
                    col_map['email'] = idx
                # Dirección
                elif h_clean in ['dirección', 'direccion', 'domicilio']:
                    col_map['direccion'] = idx
                # Etiquetas
                elif h_clean in ['etiquetas', 'categoría', 'categoria', 'tags']:
                    col_map['etiquetas'] = idx
                # Pedidos venta
                elif h_clean in ['pedidos_venta', 'pedidos', 'número_de_pedidos_de_venta', 'numero_de_pedidos_de_venta']:
                    col_map['pedidos_venta'] = idx
                # Total facturado
                elif h_clean in ['total_facturado', 'facturado', 'total_factura', 'total']:
                    col_map['total_facturado'] = idx
                # Gustos
                elif h_clean in ['gustos', 'preferencias']:
                    col_map['gustos'] = idx
                # Notas
                elif h_clean in ['notas', 'observaciones']:
                    col_map['notas'] = idx
                # Carnet identidad
                elif h_clean in ['carnet_identidad', 'carnet', 'dni', 'ci']:
                    col_map['carnet_identidad'] = idx
                # Fecha nacimiento
                elif h_clean in ['fecha_nacimiento', 'f_nac', 'nacimiento']:
                    col_map['fecha_nacimiento'] = idx
                # Tipo cliente
                elif h_clean in ['tipo_cliente', 'tipo']:
                    col_map['tipo_cliente'] = idx
                # Sector
                elif h_clean in ['sector', 'rubro']:
                    col_map['sector'] = idx
                # Preferencias diseño
                elif h_clean in ['preferencias_diseno', 'pref_diseno']:
                    col_map['preferencias_diseno'] = idx
                # Método pago
                elif h_clean in ['metodo_pago', 'pago', 'metodo_pago_favorito']:
                    col_map['metodo_pago_favorito'] = idx
                # Referido por
                elif h_clean in ['referido_por', 'referido']:
                    col_map['referido_por'] = idx
                # Frecuencia pedido
                elif h_clean in ['frecuencia_pedido', 'frecuencia']:
                    col_map['frecuencia_pedido'] = idx
                # Último pedido
                elif h_clean in ['ultimo_pedido', 'ult_pedido']:
                    col_map['ultimo_pedido'] = idx
                # Observaciones internas
                elif h_clean in ['observaciones_internas', 'obs_internas']:
                    col_map['observaciones_internas'] = idx
                # Comercial (NUEVO)
                elif h_clean in ['comercial', 'vendedor', 'ejecutivo']:
                    col_map['comercial'] = idx

            if 'nombre' not in col_map:
                flash('El archivo no contiene una columna "Nombre", "Cliente" o "Nombre completo".', 'danger')
                return redirect(url_for('clientes.importar_clientes'))

            # Procesar filas (desde la 2)
            contador = 0
            actualizados = 0
            errores = []
            
            for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                if not row or not any(row):
                    continue

                nombre = ''
                if col_map.get('nombre') is not None and row[col_map['nombre']]:
                    nombre = str(row[col_map['nombre']]).strip()
                if not nombre:
                    continue

                # Obtener referencia (si existe)
                referencia = ''
                if col_map.get('referencia') is not None and row[col_map['referencia']]:
                    referencia = str(row[col_map['referencia']]).strip()

                # Buscar duplicado: primero por referencia, luego por nombre exacto
                cliente = None
                if referencia:
                    cliente = Client.query.filter_by(referencia=referencia).first()
                if not cliente:
                    # Buscar por nombre exacto (ignorando mayúsculas)
                    cliente = Client.query.filter(db.func.lower(Client.nombre) == db.func.lower(nombre)).first()

                if cliente:
                    # Sobreescribir
                    cliente.nombre = nombre
                    if col_map.get('telefono') is not None and row[col_map['telefono']]:
                        cliente.telefono = str(row[col_map['telefono']]).strip()
                    if col_map.get('email') is not None and row[col_map['email']]:
                        cliente.email = str(row[col_map['email']]).strip()
                    if col_map.get('direccion') is not None and row[col_map['direccion']]:
                        cliente.direccion = str(row[col_map['direccion']]).strip()
                    if col_map.get('etiquetas') is not None and row[col_map['etiquetas']]:
                        cliente.etiquetas = str(row[col_map['etiquetas']]).strip()
                    if col_map.get('pedidos_venta') is not None and row[col_map['pedidos_venta']]:
                        try:
                            cliente.pedidos_venta = int(float(str(row[col_map['pedidos_venta']]).replace(',', '')))
                        except:
                            pass
                    if col_map.get('total_facturado') is not None and row[col_map['total_facturado']]:
                        try:
                            cliente.total_facturado = float(str(row[col_map['total_facturado']]).replace(',', ''))
                        except:
                            pass
                    if col_map.get('gustos') is not None and row[col_map['gustos']]:
                        cliente.gustos = str(row[col_map['gustos']]).strip()
                    if col_map.get('notas') is not None and row[col_map['notas']]:
                        cliente.notas = str(row[col_map['notas']]).strip()
                    if col_map.get('carnet_identidad') is not None and row[col_map['carnet_identidad']]:
                        cliente.carnet_identidad = str(row[col_map['carnet_identidad']]).strip()
                    if col_map.get('fecha_nacimiento') is not None and row[col_map['fecha_nacimiento']]:
                        try:
                            val = row[col_map['fecha_nacimiento']]
                            if isinstance(val, datetime):
                                cliente.fecha_nacimiento = val.date()
                            elif isinstance(val, (int, float)):
                                # Puede ser timestamp de Excel
                                from datetime import date
                                cliente.fecha_nacimiento = date(1899, 12, 30) + timedelta(days=int(val))
                            else:
                                cliente.fecha_nacimiento = datetime.strptime(str(val), '%Y-%m-%d').date()
                        except:
                            pass
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
                    if col_map.get('ultimo_pedido') is not None and row[col_map['ultimo_pedido']]:
                        try:
                            val = row[col_map['ultimo_pedido']]
                            if isinstance(val, datetime):
                                cliente.ultimo_pedido = val.date()
                            elif isinstance(val, (int, float)):
                                from datetime import date
                                cliente.ultimo_pedido = date(1899, 12, 30) + timedelta(days=int(val))
                            else:
                                cliente.ultimo_pedido = datetime.strptime(str(val), '%Y-%m-%d').date()
                        except:
                            pass
                    if col_map.get('observaciones_internas') is not None and row[col_map['observaciones_internas']]:
                        cliente.observaciones_internas = str(row[col_map['observaciones_internas']]).strip()
                    if col_map.get('comercial') is not None and row[col_map['comercial']]:
                        cliente.comercial = str(row[col_map['comercial']]).strip()
                    cliente.updated_at = datetime.now()
                    actualizados += 1
                else:
                    # Crear nuevo
                    if not referencia:
                        referencia = f"CLI-{datetime.now().strftime('%Y%m%d%H%M%S')}{Client.query.count()+1}"
                    nuevo = Client(
                        referencia=referencia,
                        nombre=nombre,
                        telefono=str(row[col_map['telefono']]).strip() if col_map.get('telefono') is not None and row[col_map['telefono']] else '',
                        email=str(row[col_map['email']]).strip() if col_map.get('email') is not None and row[col_map['email']] else '',
                        direccion=str(row[col_map['direccion']]).strip() if col_map.get('direccion') is not None and row[col_map['direccion']] else '',
                        etiquetas=str(row[col_map['etiquetas']]).strip() if col_map.get('etiquetas') is not None and row[col_map['etiquetas']] else '',
                        pedidos_venta=int(float(str(row[col_map['pedidos_venta']]).replace(',', ''))) if col_map.get('pedidos_venta') is not None and row[col_map['pedidos_venta']] and str(row[col_map['pedidos_venta']]).replace('.','',1).replace(',','',1).isdigit() else 0,
                        total_facturado=float(str(row[col_map['total_facturado']]).replace(',', '')) if col_map.get('total_facturado') is not None and row[col_map['total_facturado']] and str(row[col_map['total_facturado']]).replace('.','',1).replace(',','',1).isdigit() else 0.0,
                        gustos=str(row[col_map['gustos']]).strip() if col_map.get('gustos') is not None and row[col_map['gustos']] else '',
                        notas=str(row[col_map['notas']]).strip() if col_map.get('notas') is not None and row[col_map['notas']] else '',
                        carnet_identidad=str(row[col_map['carnet_identidad']]).strip() if col_map.get('carnet_identidad') is not None and row[col_map['carnet_identidad']] else '',
                        tipo_cliente=str(row[col_map['tipo_cliente']]).strip() if col_map.get('tipo_cliente') is not None and row[col_map['tipo_cliente']] else 'persona',
                        sector=str(row[col_map['sector']]).strip() if col_map.get('sector') is not None and row[col_map['sector']] else '',
                        preferencias_diseno=str(row[col_map['preferencias_diseno']]).strip() if col_map.get('preferencias_diseno') is not None and row[col_map['preferencias_diseno']] else '',
                        metodo_pago_favorito=str(row[col_map['metodo_pago_favorito']]).strip() if col_map.get('metodo_pago_favorito') is not None and row[col_map['metodo_pago_favorito']] else '',
                        referido_por=str(row[col_map['referido_por']]).strip() if col_map.get('referido_por') is not None and row[col_map['referido_por']] else '',
                        frecuencia_pedido=str(row[col_map['frecuencia_pedido']]).strip() if col_map.get('frecuencia_pedido') is not None and row[col_map['frecuencia_pedido']] else '',
                        observaciones_internas=str(row[col_map['observaciones_internas']]).strip() if col_map.get('observaciones_internas') is not None and row[col_map['observaciones_internas']] else '',
                        comercial=str(row[col_map['comercial']]).strip() if col_map.get('comercial') is not None and row[col_map['comercial']] else '',
                        created_by_id=current_user.id
                    )
                    db.session.add(nuevo)
                    contador += 1

            db.session.commit()
            flash(f'Importación completada: {contador} nuevos, {actualizados} actualizados.', 'success')
            return redirect(url_for('clientes.list_clientes'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error al importar: {str(e)}', 'danger')
            return redirect(url_for('clientes.importar_clientes'))

    return render_template('importar_clientes.html')

# ==========================================
# EXPORTAR TODOS LOS CLIENTES
# ==========================================
@clientes_bp.route('/exportar-todos')
@login_required
@comercial_or_admin_required
def exportar_todos():
    clientes = Client.query.order_by(Client.nombre).all()
    ids = [c.id for c in clientes]
    return exportar_seleccionados(ids)