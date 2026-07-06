from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app.models import Client
from app import db
import openpyxl
from datetime import datetime

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
# LISTAR CLIENTES (con búsqueda)
# ==========================================
@clientes_bp.route('/')
@login_required
@comercial_or_admin_required
def list_clients():
    search = request.args.get('search', '')
    if search:
        clients = Client.query.filter(
            db.or_(
                Client.nombre.ilike(f'%{search}%'),
                Client.referencia.ilike(f'%{search}%'),
                Client.telefono.ilike(f'%{search}%')
            )
        ).order_by(Client.nombre).all()
    else:
        clients = Client.query.order_by(Client.nombre).all()
    return render_template('list_clientes.html', clients=clients, search=search)

# ==========================================
# CREAR CLIENTE
# ==========================================
@clientes_bp.route('/crear', methods=['GET', 'POST'])
@login_required
@comercial_or_admin_required
def create_client():
    if request.method == 'POST':
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

        if not referencia or not nombre:
            flash('Referencia y nombre son obligatorios.', 'danger')
            return render_template('form_cliente.html', client_data=request.form)

        if Client.query.filter_by(referencia=referencia).first():
            flash(f'Ya existe un cliente con la referencia {referencia}.', 'danger')
            return render_template('form_cliente.html', client_data=request.form)

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
        db.session.commit()
        flash('Cliente actualizado correctamente.', 'success')
        return redirect(url_for('clientes.list_clients'))

    return render_template('form_cliente.html', client_data=client, edit=True)

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
# IMPORTAR DESDE EXCEL
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
                if header and 'Referencia' in str(header):
                    col_idx['referencia'] = idx
                elif header and 'Nombre completo' in str(header):
                    col_idx['nombre'] = idx
                elif header and 'Móvil' in str(header):
                    col_idx['telefono'] = idx
                elif header and 'Etiquetas' in str(header):
                    col_idx['etiquetas'] = idx
                elif header and 'Número de pedidos' in str(header):
                    col_idx['pedidos_venta'] = idx
                elif header and 'Total facturado' in str(header):
                    col_idx['total_facturado'] = idx

            if 'referencia' not in col_idx or 'nombre' not in col_idx:
                # Fallback por posición
                col_idx['referencia'] = 0
                col_idx['nombre'] = 1
                col_idx['telefono'] = 2 if len(ws[1]) > 2 else None
                col_idx['etiquetas'] = 3 if len(ws[1]) > 3 else None
                col_idx['pedidos_venta'] = 4 if len(ws[1]) > 4 else None
                col_idx['total_facturado'] = 5 if len(ws[1]) > 5 else None

            imported = 0
            errors = []
            for row in ws.iter_rows(min_row=2, values_only=True):
                if not row or not row[col_idx['referencia']]:
                    continue
                referencia = str(row[col_idx['referencia']]).strip()
                nombre = str(row[col_idx['nombre']]).strip() if row[col_idx['nombre']] else ''
                telefono = str(row[col_idx['telefono']]).strip() if col_idx.get('telefono') is not None and row[col_idx['telefono']] else ''
                etiquetas = str(row[col_idx['etiquetas']]).strip() if col_idx.get('etiquetas') is not None and row[col_idx['etiquetas']] else ''
                pedidos_venta = int(row[col_idx['pedidos_venta']]) if col_idx.get('pedidos_venta') is not None and row[col_idx['pedidos_venta']] else 0
                total_facturado = float(row[col_idx['total_facturado']]) if col_idx.get('total_facturado') is not None and row[col_idx['total_facturado']] else 0.0

                if not nombre:
                    errors.append(f'Fila sin nombre: {referencia}')
                    continue

                # Evitar duplicados por referencia
                if Client.query.filter_by(referencia=referencia).first():
                    client = Client.query.filter_by(referencia=referencia).first()
                    client.nombre = nombre
                    client.telefono = telefono
                    client.etiquetas = etiquetas
                    client.pedidos_venta = pedidos_venta
                    client.total_facturado = total_facturado
                    db.session.add(client)
                else:
                    client = Client(
                        referencia=referencia,
                        nombre=nombre,
                        telefono=telefono,
                        etiquetas=etiquetas,
                        pedidos_venta=pedidos_venta,
                        total_facturado=total_facturado,
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