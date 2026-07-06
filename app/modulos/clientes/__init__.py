from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import login_required, current_user
from app.models import Client
from app import db
import openpyxl
from datetime import datetime
import io
import tempfile
import os

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
# LISTAR CLIENTES (con búsqueda, filtros, ordenación)
# ==========================================
@clientes_bp.route('/')
@login_required
@comercial_or_admin_required
def list_clients():
    search = request.args.get('search', '')
    order_by = request.args.get('order_by', 'nombre')
    order_dir = request.args.get('order_dir', 'asc')
    tipo_cliente = request.args.get('tipo_cliente', '')
    sector = request.args.get('sector', '')
    frecuencia = request.args.get('frecuencia', '')

    # Mapeo de campos permitidos
    allowed_fields = {
        'referencia': Client.referencia,
        'nombre': Client.nombre,
        'telefono': Client.telefono,
        'pedidos_venta': Client.pedidos_venta,
        'total_facturado': Client.total_facturado,
        'created_at': Client.created_at,
        'fecha_nacimiento': Client.fecha_nacimiento,
        'tipo_cliente': Client.tipo_cliente,
        'frecuencia_pedido': Client.frecuencia_pedido
    }
    order_column = allowed_fields.get(order_by, Client.nombre)
    if order_dir == 'desc':
        order_column = order_column.desc()
    else:
        order_column = order_column.asc()

    query = Client.query
    if search:
        query = query.filter(
            db.or_(
                Client.nombre.ilike(f'%{search}%'),
                Client.referencia.ilike(f'%{search}%'),
                Client.telefono.ilike(f'%{search}%'),
                Client.etiquetas.ilike(f'%{search}%')
            )
        )
    if tipo_cliente:
        query = query.filter(Client.tipo_cliente == tipo_cliente)
    if sector:
        query = query.filter(Client.sector == sector)
    if frecuencia:
        query = query.filter(Client.frecuencia_pedido == frecuencia)

    clients = query.order_by(order_column).all()

    # Obtener valores únicos para filtros
    tipos = db.session.query(Client.tipo_cliente).distinct().filter(Client.tipo_cliente.isnot(None)).all()
    sectores = db.session.query(Client.sector).distinct().filter(Client.sector.isnot(None)).all()
    frecuencias = db.session.query(Client.frecuencia_pedido).distinct().filter(Client.frecuencia_pedido.isnot(None)).all()

    return render_template(
        'list_clientes.html',
        clients=clients,
        search=search,
        order_by=order_by,
        order_dir=order_dir,
        tipo_cliente=tipo_cliente,
        sector=sector,
        frecuencia=frecuencia,
        tipos=[t[0] for t in tipos if t[0]],
        sectores=[s[0] for s in sectores if s[0]],
        frecuencias=[f[0] for f in frecuencias if f[0]]
    )

# ==========================================
# VISTA DE DETALLE DEL CLIENTE
# ==========================================
@clientes_bp.route('/detalle/<int:client_id>')
@login_required
@comercial_or_admin_required
def detail_client(client_id):
    client = Client.query.get_or_404(client_id)
    return render_template('detalle_cliente.html', client=client)

# ==========================================
# CREAR CLIENTE
# ==========================================
@clientes_bp.route('/crear', methods=['GET', 'POST'])
@login_required
@comercial_or_admin_required
def create_client():
    if request.method == 'POST':
        # Recoger todos los campos
        referencia = request.form.get('referencia')
        nombre = request.form.get('nombre')
        telefono = request.form.get('telefono')
        email = request.form.get('email')
        direccion = request.form.get('direccion')
        etiquetas = request.form.get('etiquetas')
        gustos = request.form.get('gustos')
        notas = request.form.get('notas')
        pedidos_venta = int(request.form.get('pedidos_venta', 0))
        total_facturado = float(request.form.get('total_facturado', 0.0))
        carnet_identidad = request.form.get('carnet_identidad')
        fecha_nacimiento_str = request.form.get('fecha_nacimiento')
        tipo_cliente = request.form.get('tipo_cliente')
        sector = request.form.get('sector')
        preferencias_diseno = request.form.get('preferencias_diseno')
        metodo_pago_favorito = request.form.get('metodo_pago_favorito')
        referido_por = request.form.get('referido_por')
        frecuencia_pedido = request.form.get('frecuencia_pedido')
        ultimo_pedido_str = request.form.get('ultimo_pedido')
        observaciones_internas = request.form.get('observaciones_internas')

        if not referencia or not nombre:
            flash('Referencia y nombre son obligatorios.', 'danger')
            return render_template('form_cliente.html', client_data=request.form)

        if Client.query.filter_by(referencia=referencia).first():
            flash(f'Ya existe un cliente con la referencia {referencia}.', 'danger')
            return render_template('form_cliente.html', client_data=request.form)

        # Convertir fechas
        fecha_nacimiento = datetime.strptime(fecha_nacimiento_str, '%Y-%m-%d').date() if fecha_nacimiento_str else None
        ultimo_pedido = datetime.strptime(ultimo_pedido_str, '%Y-%m-%d').date() if ultimo_pedido_str else None

        client = Client(
            referencia=referencia,
            nombre=nombre,
            telefono=telefono,
            email=email,
            direccion=direccion,
            etiquetas=etiquetas,
            gustos=gustos,
            notas=notas,
            pedidos_venta=pedidos_venta,
            total_facturado=total_facturado,
            carnet_identidad=carnet_identidad,
            fecha_nacimiento=fecha_nacimiento,
            tipo_cliente=tipo_cliente,
            sector=sector,
            preferencias_diseno=preferencias_diseno,
            metodo_pago_favorito=metodo_pago_favorito,
            referido_por=referido_por,
            frecuencia_pedido=frecuencia_pedido,
            ultimo_pedido=ultimo_pedido,
            observaciones_internas=observaciones_internas,
            created_by_id=current_user.id
        )
        db.session.add(client)
        db.session.commit()
        flash(f'Cliente {nombre} creado correctamente.', 'success')
        return redirect(url_for('clientes.list_clients'))

    return render_template('form_cliente.html', client_data=None)

# ==========================================
# EDITAR CLIENTE
# ==========================================
@clientes_bp.route('/editar/<int:client_id>', methods=['GET', 'POST'])
@login_required
@comercial_or_admin_required
def edit_client(client_id):
    client = Client.query.get_or_404(client_id)

    if request.method == 'POST':
        client.referencia = request.form.get('referencia')
        client.nombre = request.form.get('nombre')
        client.telefono = request.form.get('telefono')
        client.email = request.form.get('email')
        client.direccion = request.form.get('direccion')
        client.etiquetas = request.form.get('etiquetas')
        client.gustos = request.form.get('gustos')
        client.notas = request.form.get('notas')
        client.pedidos_venta = int(request.form.get('pedidos_venta', 0))
        client.total_facturado = float(request.form.get('total_facturado', 0.0))
        client.carnet_identidad = request.form.get('carnet_identidad')
        fecha_nacimiento_str = request.form.get('fecha_nacimiento')
        client.fecha_nacimiento = datetime.strptime(fecha_nacimiento_str, '%Y-%m-%d').date() if fecha_nacimiento_str else None
        client.tipo_cliente = request.form.get('tipo_cliente')
        client.sector = request.form.get('sector')
        client.preferencias_diseno = request.form.get('preferencias_diseno')
        client.metodo_pago_favorito = request.form.get('metodo_pago_favorito')
        client.referido_por = request.form.get('referido_por')
        client.frecuencia_pedido = request.form.get('frecuencia_pedido')
        ultimo_pedido_str = request.form.get('ultimo_pedido')
        client.ultimo_pedido = datetime.strptime(ultimo_pedido_str, '%Y-%m-%d').date() if ultimo_pedido_str else None
        client.observaciones_internas = request.form.get('observaciones_internas')

        db.session.commit()
        flash('Cliente actualizado correctamente.', 'success')
        return redirect(url_for('clientes.list_clients'))

    # Preparar datos para el formulario
    form_data = {
        'referencia': client.referencia,
        'nombre': client.nombre,
        'telefono': client.telefono,
        'email': client.email,
        'direccion': client.direccion,
        'etiquetas': client.etiquetas,
        'gustos': client.gustos,
        'notas': client.notas,
        'pedidos_venta': client.pedidos_venta,
        'total_facturado': client.total_facturado,
        'carnet_identidad': client.carnet_identidad,
        'fecha_nacimiento': client.fecha_nacimiento.strftime('%Y-%m-%d') if client.fecha_nacimiento else '',
        'tipo_cliente': client.tipo_cliente,
        'sector': client.sector,
        'preferencias_diseno': client.preferencias_diseno,
        'metodo_pago_favorito': client.metodo_pago_favorito,
        'referido_por': client.referido_por,
        'frecuencia_pedido': client.frecuencia_pedido,
        'ultimo_pedido': client.ultimo_pedido.strftime('%Y-%m-%d') if client.ultimo_pedido else '',
        'observaciones_internas': client.observaciones_internas
    }
    return render_template('form_cliente.html', client_data=form_data, edit=True, client=client)

# ==========================================
# ELIMINAR CLIENTE (solo admin)
# ==========================================
@clientes_bp.route('/eliminar/<int:client_id>', methods=['POST'])
@login_required
def delete_client(client_id):
    if current_user.role != 'admin':
        flash('Solo administradores pueden eliminar clientes.', 'danger')
        return redirect(url_for('clientes.list_clients'))
    client = Client.query.get_or_404(client_id)
    db.session.delete(client)
    db.session.commit()
    flash('Cliente eliminado permanentemente.', 'success')
    return redirect(url_for('clientes.list_clients'))

# ==========================================
# IMPORTAR DESDE EXCEL (con nuevos campos opcionales)
# ==========================================
@clientes_bp.route('/importar', methods=['GET', 'POST'])
@login_required
@comercial_or_admin_required
def import_clients():
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename.endswith(('.xlsx', '.xls')):
            flash('Debes subir un archivo Excel (.xlsx o .xls).', 'danger')
            return render_template('import_clientes.html')

        try:
            wb = openpyxl.load_workbook(file)
            ws = wb.active
            headers = [cell.value for cell in ws[1]]
            col_idx = {}
            for idx, header in enumerate(headers):
                if header:
                    header_str = str(header).strip()
                    if 'Referencia' in header_str:
                        col_idx['referencia'] = idx
                    elif 'Nombre completo' in header_str or 'Nombre' in header_str:
                        col_idx['nombre'] = idx
                    elif 'Móvil' in header_str or 'Teléfono' in header_str:
                        col_idx['telefono'] = idx
                    elif 'Etiquetas' in header_str:
                        col_idx['etiquetas'] = idx
                    elif 'Pedidos' in header_str or 'Número de pedidos' in header_str:
                        col_idx['pedidos_venta'] = idx
                    elif 'Total facturado' in header_str:
                        col_idx['total_facturado'] = idx
                    # Nuevos campos (opcionales)
                    elif 'Carnet' in header_str or 'Cédula' in header_str:
                        col_idx['carnet_identidad'] = idx
                    elif 'Nacimiento' in header_str or 'Cumpleaños' in header_str:
                        col_idx['fecha_nacimiento'] = idx
                    elif 'Tipo cliente' in header_str:
                        col_idx['tipo_cliente'] = idx
                    elif 'Sector' in header_str:
                        col_idx['sector'] = idx
                    elif 'Preferencias diseño' in header_str:
                        col_idx['preferencias_diseno'] = idx
                    elif 'Método pago' in header_str:
                        col_idx['metodo_pago_favorito'] = idx
                    elif 'Referido por' in header_str:
                        col_idx['referido_por'] = idx
                    elif 'Frecuencia pedido' in header_str:
                        col_idx['frecuencia_pedido'] = idx
                    elif 'Último pedido' in header_str:
                        col_idx['ultimo_pedido'] = idx
                    elif 'Observaciones internas' in header_str:
                        col_idx['observaciones_internas'] = idx

            # Fallback por posición
            if 'referencia' not in col_idx or 'nombre' not in col_idx:
                col_idx['referencia'] = 0
                col_idx['nombre'] = 1
                col_idx['telefono'] = 2 if len(ws[1]) > 2 else None
                col_idx['etiquetas'] = 3 if len(ws[1]) > 3 else None
                col_idx['pedidos_venta'] = 4 if len(ws[1]) > 4 else None
                col_idx['total_facturado'] = 5 if len(ws[1]) > 5 else None

            imported = 0
            errors = []
            for row in ws.iter_rows(min_row=2, values_only=True):
                if not row or not row[col_idx.get('referencia', 0)]:
                    continue
                referencia = str(row[col_idx['referencia']]).strip()
                nombre = str(row[col_idx['nombre']]).strip() if col_idx.get('nombre') is not None and row[col_idx['nombre']] else ''
                telefono = str(row[col_idx['telefono']]).strip() if col_idx.get('telefono') is not None and row[col_idx['telefono']] else ''
                etiquetas = str(row[col_idx['etiquetas']]).strip() if col_idx.get('etiquetas') is not None and row[col_idx['etiquetas']] else ''
                pedidos_venta = int(row[col_idx['pedidos_venta']]) if col_idx.get('pedidos_venta') is not None and row[col_idx['pedidos_venta']] else 0
                total_facturado = float(row[col_idx['total_facturado']]) if col_idx.get('total_facturado') is not None and row[col_idx['total_facturado']] else 0.0
                # Nuevos campos (opcionales)
                carnet_identidad = str(row[col_idx['carnet_identidad']]).strip() if col_idx.get('carnet_identidad') is not None and row[col_idx['carnet_identidad']] else ''
                fecha_nacimiento_str = str(row[col_idx['fecha_nacimiento']]).strip() if col_idx.get('fecha_nacimiento') is not None and row[col_idx['fecha_nacimiento']] else ''
                tipo_cliente = str(row[col_idx['tipo_cliente']]).strip() if col_idx.get('tipo_cliente') is not None and row[col_idx['tipo_cliente']] else ''
                sector = str(row[col_idx['sector']]).strip() if col_idx.get('sector') is not None and row[col_idx['sector']] else ''
                preferencias_diseno = str(row[col_idx['preferencias_diseno']]).strip() if col_idx.get('preferencias_diseno') is not None and row[col_idx['preferencias_diseno']] else ''
                metodo_pago_favorito = str(row[col_idx['metodo_pago_favorito']]).strip() if col_idx.get('metodo_pago_favorito') is not None and row[col_idx['metodo_pago_favorito']] else ''
                referido_por = str(row[col_idx['referido_por']]).strip() if col_idx.get('referido_por') is not None and row[col_idx['referido_por']] else ''
                frecuencia_pedido = str(row[col_idx['frecuencia_pedido']]).strip() if col_idx.get('frecuencia_pedido') is not None and row[col_idx['frecuencia_pedido']] else ''
                ultimo_pedido_str = str(row[col_idx['ultimo_pedido']]).strip() if col_idx.get('ultimo_pedido') is not None and row[col_idx['ultimo_pedido']] else ''
                observaciones_internas = str(row[col_idx['observaciones_internas']]).strip() if col_idx.get('observaciones_internas') is not None and row[col_idx['observaciones_internas']] else ''

                if not nombre:
                    errors.append(f'Fila sin nombre: {referencia}')
                    continue

                fecha_nacimiento = None
                if fecha_nacimiento_str:
                    try:
                        fecha_nacimiento = datetime.strptime(fecha_nacimiento_str, '%Y-%m-%d').date()
                    except:
                        pass
                ultimo_pedido = None
                if ultimo_pedido_str:
                    try:
                        ultimo_pedido = datetime.strptime(ultimo_pedido_str, '%Y-%m-%d').date()
                    except:
                        pass

                # Evitar duplicados
                if Client.query.filter_by(referencia=referencia).first():
                    client = Client.query.filter_by(referencia=referencia).first()
                    client.nombre = nombre
                    client.telefono = telefono
                    client.etiquetas = etiquetas
                    client.pedidos_venta = pedidos_venta
                    client.total_facturado = total_facturado
                    if carnet_identidad: client.carnet_identidad = carnet_identidad
                    if fecha_nacimiento: client.fecha_nacimiento = fecha_nacimiento
                    if tipo_cliente: client.tipo_cliente = tipo_cliente
                    if sector: client.sector = sector
                    if preferencias_diseno: client.preferencias_diseno = preferencias_diseno
                    if metodo_pago_favorito: client.metodo_pago_favorito = metodo_pago_favorito
                    if referido_por: client.referido_por = referido_por
                    if frecuencia_pedido: client.frecuencia_pedido = frecuencia_pedido
                    if ultimo_pedido: client.ultimo_pedido = ultimo_pedido
                    if observaciones_internas: client.observaciones_internas = observaciones_internas
                    db.session.add(client)
                else:
                    client = Client(
                        referencia=referencia,
                        nombre=nombre,
                        telefono=telefono,
                        etiquetas=etiquetas,
                        pedidos_venta=pedidos_venta,
                        total_facturado=total_facturado,
                        carnet_identidad=carnet_identidad or None,
                        fecha_nacimiento=fecha_nacimiento,
                        tipo_cliente=tipo_cliente or None,
                        sector=sector or None,
                        preferencias_diseno=preferencias_diseno or None,
                        metodo_pago_favorito=metodo_pago_favorito or None,
                        referido_por=referido_por or None,
                        frecuencia_pedido=frecuencia_pedido or None,
                        ultimo_pedido=ultimo_pedido,
                        observaciones_internas=observaciones_internas or None,
                        created_by_id=current_user.id
                    )
                    db.session.add(client)
                imported += 1

            db.session.commit()
            flash(f'Importación completada. {imported} clientes importados/actualizados.', 'success')
            if errors:
                flash(f'Errores: {", ".join(errors[:5])}', 'warning')
        except Exception as e:
            flash(f'Error al procesar el archivo: {str(e)}', 'danger')
            return render_template('import_clientes.html')

        return redirect(url_for('clientes.list_clients'))

    return render_template('import_clientes.html')

# ==========================================
# EXPORTAR A EXCEL (con filtros actuales)
# ==========================================
@clientes_bp.route('/exportar-excel')
@login_required
@comercial_or_admin_required
def export_excel():
    # Reutilizar los mismos filtros de la lista
    search = request.args.get('search', '')
    tipo_cliente = request.args.get('tipo_cliente', '')
    sector = request.args.get('sector', '')
    frecuencia = request.args.get('frecuencia', '')

    query = Client.query
    if search:
        query = query.filter(
            db.or_(
                Client.nombre.ilike(f'%{search}%'),
                Client.referencia.ilike(f'%{search}%'),
                Client.telefono.ilike(f'%{search}%'),
                Client.etiquetas.ilike(f'%{search}%')
            )
        )
    if tipo_cliente:
        query = query.filter(Client.tipo_cliente == tipo_cliente)
    if sector:
        query = query.filter(Client.sector == sector)
    if frecuencia:
        query = query.filter(Client.frecuencia_pedido == frecuencia)

    clients = query.order_by(Client.nombre).all()

    # Crear libro de Excel
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Clientes"

    # Encabezados
    headers = [
        'Referencia', 'Nombre', 'Teléfono', 'Email', 'Dirección', 'Etiquetas',
        'Pedidos de venta', 'Total facturado', 'Gustos', 'Notas',
        'Carnet identidad', 'Fecha nacimiento', 'Tipo cliente', 'Sector',
        'Preferencias diseño', 'Método pago favorito', 'Referido por',
        'Frecuencia pedido', 'Último pedido', 'Observaciones internas'
    ]
    ws.append(headers)

    # Datos
    for c in clients:
        ws.append([
            c.referencia,
            c.nombre,
            c.telefono or '',
            c.email or '',
            c.direccion or '',
            c.etiquetas or '',
            c.pedidos_venta or 0,
            c.total_facturado or 0.0,
            c.gustos or '',
            c.notas or '',
            c.carnet_identidad or '',
            c.fecha_nacimiento.strftime('%Y-%m-%d') if c.fecha_nacimiento else '',
            c.tipo_cliente or '',
            c.sector or '',
            c.preferencias_diseno or '',
            c.metodo_pago_favorito or '',
            c.referido_por or '',
            c.frecuencia_pedido or '',
            c.ultimo_pedido.strftime('%Y-%m-%d') if c.ultimo_pedido else '',
            c.observaciones_internas or ''
        ])

    # Guardar en memoria
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name='clientes_export.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

# ==========================================
# BUSCAR CLIENTE (AJAX para autocomplete)
# ==========================================
@clientes_bp.route('/buscar', methods=['GET'])
@login_required
def search_clients():
    term = request.args.get('term', '')
    if len(term) < 2:
        return jsonify([])
    clients = Client.query.filter(
        db.or_(
            Client.nombre.ilike(f'%{term}%'),
            Client.referencia.ilike(f'%{term}%')
        )
    ).limit(10).all()
    result = [{'id': c.id, 'text': f'{c.referencia} - {c.nombre}', 'nombre': c.nombre, 'referencia': c.referencia} for c in clients]
    return jsonify(result)