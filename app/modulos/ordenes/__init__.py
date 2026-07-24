from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, current_app, jsonify
from flask_login import login_required, current_user
from app.models import Order, User, ArchivoAdjunto, Client
from app import db
from weasyprint import HTML
import json
from datetime import datetime
import tempfile
import os
import uuid
from werkzeug.utils import secure_filename
from app.services.notification_service import notificar_usuarios

ordenes_bp = Blueprint('ordenes', __name__, url_prefix='/ordenes', template_folder='templates')

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
# FUNCIÓN AUXILIAR PARA OBTENER CONTEXTO DEL FORMULARIO
# ==========================================
def _get_form_context(form_data=None, edit=False, order=None):
    """Retorna el contexto común para el formulario de órdenes"""
    lista_materiales = [
        'Vinilo blanco brillo', 'Vinilo mate', 'Vinilo corte color', 'dorado',
        'Vinilo transparente/brillo', 'Vinilo transparente/mate', 'wallpaper',
        'Vinilo microperforado', 'Vinilo esmerilado', 'Papel fotografico brillo',
        'Papel fotografico mate', 'Vinilo fondo negro', 'Papel back lite',
        'Lona laminada', 'Lona microperforada'
    ]
    servicios_disponibles = ['Diseño', 'Rúter', 'Láser', 'Montaje', 'Herrería']

    clients_list = Client.query.order_by(Client.nombre).all()
    clients_data = [{'id': c.id, 'nombre': c.nombre, 'referencia': c.referencia, 'telefono': c.telefono} for c in clients_list]

    todos_usuarios = User.query.filter_by(is_active=True).order_by(User.username).all()

    context = {
        'lista_materiales': lista_materiales,
        'servicios_disponibles': servicios_disponibles,
        'clients_list': clients_data,
        'todos_usuarios': todos_usuarios,
        'edit': edit,
        'order': order,
        'form_data': form_data if form_data is not None else {}
    }
    return context

# ==========================================
# LISTAR ÓRDENES
# ==========================================
@ordenes_bp.route('/')
@login_required
@comercial_or_admin_required
def list_orders():
    orders = Order.query.order_by(Order.created_at.desc()).all()
    return render_template('list_ordenes.html', orders=orders)

# ==========================================
# DETALLE DE ORDEN (SOLO LECTURA)
# ==========================================
@ordenes_bp.route('/detalle/<int:order_id>')
@login_required  # ya no usa comercial_or_admin_required
def detalle_order(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template('detalle_orden.html', order=order)

# ==========================================
# FUNCIÓN AUXILIAR PARA GUARDAR ARCHIVO
# ==========================================
def guardar_archivo(orden_id, archivo):
    upload_folder = current_app.config.get('UPLOAD_FOLDER', 'app/static/uploads')
    orden_folder = os.path.join(upload_folder, 'ordenes', str(orden_id))
    os.makedirs(orden_folder, exist_ok=True)

    nombre_original = secure_filename(archivo.filename)
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    uuid_part = str(uuid.uuid4())[:8]
    nombre_guardado = f"{timestamp}_{uuid_part}_{nombre_original}"
    ruta_relativa = os.path.join('ordenes', str(orden_id), nombre_guardado)
    ruta_absoluta = os.path.join(upload_folder, ruta_relativa)

    archivo.save(ruta_absoluta)
    return ruta_relativa

# ==========================================
# CREAR ORDEN
# ==========================================
@ordenes_bp.route('/crear', methods=['GET', 'POST'])
@login_required
@comercial_or_admin_required
def create_order():
    if request.method == 'POST':
        order_num = request.form.get('order_num')
        date = request.form.get('date')
        client_id = request.form.get('client_id')
        solicitado = request.form.get('solicitado')
        proyecto = request.form.get('proyecto')
        invoice = request.form.get('invoice')
        tipo_proyecto = request.form.get('tipo_proyecto')
        priority = request.form.get('priority')
        descripcion = request.form.get('descripcion')

        # Validaciones
        if not order_num or not client_id or not date:
            flash('N° de orden, Cliente y Fecha son obligatorios.', 'danger')
            context = _get_form_context(form_data=request.form, edit=False, order=None)
            return render_template('form_orden.html', **context)

        # Validar que el cliente existe
        client = Client.query.get(client_id)
        if not client:
            flash('Cliente no encontrado.', 'danger')
            context = _get_form_context(form_data=request.form, edit=False, order=None)
            return render_template('form_orden.html', **context)

        # Servicios
        servicios = []
        for key in request.form:
            if key.startswith('serv_') and request.form.get(key) == 'on':
                serv_name = key[5:]
                servicios.append(serv_name)
        otros = request.form.get('servicios_otros', '').strip()
        if otros:
            servicios.append(f'Otros: {otros}')

        order = Order(
            order_num=order_num,
            date=datetime.strptime(date, '%Y-%m-%d'),
            client_id=client_id,
            solicitado=solicitado,
            proyecto=proyecto,
            invoice=invoice,
            tipo_proyecto=tipo_proyecto,
            priority=priority,
            descripcion=descripcion,
            column='pendiente',
            entrada_ok=False,
            created_by_id=current_user.id
        )
        order.set_servicios(servicios)
        order.add_history(f'Creada por {current_user.username}')
        db.session.add(order)
        db.session.flush()

        # ==========================================
        # NOTIFICACIONES
        # ==========================================
        usuarios_ids = []
        usuarios_notificar = request.form.getlist('usuarios_notificar[]')
        usuarios_ids = [int(id) for id in usuarios_notificar if id.isdigit()]

        if client.comercial:
            comercial_user = User.query.filter_by(username=client.comercial).first()
            if comercial_user:
                usuarios_ids.append(comercial_user.id)

        if current_user.id not in usuarios_ids:
            usuarios_ids.append(current_user.id)

        mensaje = f'Nueva orden {order.order_num} creada por {current_user.username}'
        enlace = url_for('ordenes.edit_order', order_id=order.id, _external=True)

        if usuarios_ids:
            notificar_usuarios(usuarios_ids, mensaje, 'orden_creada', order.id, enlace)

        # Guardar usuarios notificados
        order.set_usuarios_notificados(usuarios_ids)

        # Procesar líneas
        nombres_visibles = request.form.getlist('nombres_visibles[]')
        materiales = request.form.getlist('materiales[]')
        cantidades = request.form.getlist('cantidades[]')
        unidades = request.form.getlist('unidades[]')
        archivos = request.files.getlist('archivos_nuevos[]')

        for i, nombre_visible in enumerate(nombres_visibles):
            if not nombre_visible.strip():
                continue
            material = materiales[i] if i < len(materiales) else ''
            cantidad_str = cantidades[i] if i < len(cantidades) else ''
            unidad = unidades[i] if i < len(unidades) else 'm'
            cantidad = None
            if cantidad_str.strip():
                try:
                    cantidad = float(cantidad_str)
                except ValueError:
                    cantidad = None

            archivo = None
            if i < len(archivos):
                archivo = archivos[i]
                if not archivo.filename:
                    archivo = None

            adjunto = ArchivoAdjunto(
                orden_id=order.id,
                nombre_original=archivo.filename if archivo else '',
                nombre_visible=nombre_visible.strip(),
                material=material.strip() if material else None,
                cantidad=cantidad,
                unidad=unidad
            )
            if archivo:
                ruta = guardar_archivo(order.id, archivo)
                adjunto.ruta = ruta
            else:
                adjunto.ruta = None
            db.session.add(adjunto)

        db.session.commit()
        flash(f'Orden {order_num} creada correctamente.', 'success')
        return redirect(url_for('ordenes.edit_order', order_id=order.id))

    # GET: mostrar formulario
    context = _get_form_context(form_data=None, edit=False, order=None)
    return render_template('form_orden.html', **context)

# ==========================================
# EDITAR ORDEN
# ==========================================
@ordenes_bp.route('/editar/<int:order_id>', methods=['GET', 'POST'])
@login_required
@comercial_or_admin_required
def edit_order(order_id):
    order = Order.query.get_or_404(order_id)

    if request.method == 'POST':
        # Actualizar datos básicos
        order.order_num = request.form.get('order_num')
        order.date = datetime.strptime(request.form.get('date'), '%Y-%m-%d')
        client_id = request.form.get('client_id')
        if client_id:
            client = Client.query.get(client_id)
            if client:
                order.client_id = client_id
            else:
                flash('Cliente no encontrado.', 'danger')
        order.solicitado = request.form.get('solicitado')
        order.proyecto = request.form.get('proyecto')
        order.invoice = request.form.get('invoice')
        order.tipo_proyecto = request.form.get('tipo_proyecto')
        order.priority = request.form.get('priority')
        order.descripcion = request.form.get('descripcion')

        # Servicios
        servicios = []
        for key in request.form:
            if key.startswith('serv_') and request.form.get(key) == 'on':
                serv_name = key[5:]
                servicios.append(serv_name)
        otros = request.form.get('servicios_otros', '').strip()
        if otros:
            servicios.append(f'Otros: {otros}')
        order.set_servicios(servicios)

        # Actualizar líneas existentes
        existing_ids = request.form.getlist('archivo_ids[]')
        for archivo_id in existing_ids:
            archivo = ArchivoAdjunto.query.get(int(archivo_id))
            if archivo and archivo.orden_id == order.id:
                nombre_visible = request.form.get(f'nombre_visible_{archivo_id}')
                if nombre_visible:
                    archivo.nombre_visible = nombre_visible.strip()
                material = request.form.get(f'material_{archivo_id}')
                if material is not None:
                    archivo.material = material.strip() if material.strip() else None
                cantidad = request.form.get(f'cantidad_{archivo_id}')
                if cantidad:
                    try:
                        archivo.cantidad = float(cantidad)
                    except ValueError:
                        archivo.cantidad = None
                unidad = request.form.get(f'unidad_{archivo_id}')
                if unidad:
                    archivo.unidad = unidad

        # Añadir nuevas líneas
        nombres_visibles = request.form.getlist('nombres_visibles[]')
        materiales = request.form.getlist('materiales[]')
        cantidades = request.form.getlist('cantidades[]')
        unidades = request.form.getlist('unidades[]')
        archivos = request.files.getlist('archivos_nuevos[]')

        for i, nombre_visible in enumerate(nombres_visibles):
            if not nombre_visible.strip():
                continue
            material = materiales[i] if i < len(materiales) else ''
            cantidad_str = cantidades[i] if i < len(cantidades) else ''
            unidad = unidades[i] if i < len(unidades) else 'm'
            cantidad = None
            if cantidad_str.strip():
                try:
                    cantidad = float(cantidad_str)
                except ValueError:
                    cantidad = None

            archivo = None
            if i < len(archivos):
                archivo = archivos[i]
                if not archivo.filename:
                    archivo = None

            adjunto = ArchivoAdjunto(
                orden_id=order.id,
                nombre_original=archivo.filename if archivo else '',
                nombre_visible=nombre_visible.strip(),
                material=material.strip() if material else None,
                cantidad=cantidad,
                unidad=unidad
            )
            if archivo:
                ruta = guardar_archivo(order.id, archivo)
                adjunto.ruta = ruta
            else:
                adjunto.ruta = None
            db.session.add(adjunto)

        order.add_history(f'Editada por {current_user.username}')

        # ==========================================
        # NOTIFICACIONES
        # ==========================================
        usuarios_ids = []
        usuarios_notificar = request.form.getlist('usuarios_notificar[]')
        usuarios_ids = [int(id) for id in usuarios_notificar if id.isdigit()]

        if order.client and order.client.comercial:
            comercial_user = User.query.filter_by(username=order.client.comercial).first()
            if comercial_user:
                usuarios_ids.append(comercial_user.id)

        if current_user.id not in usuarios_ids:
            usuarios_ids.append(current_user.id)

        mensaje = f'Orden {order.order_num} actualizada por {current_user.username}'
        enlace = url_for('ordenes.edit_order', order_id=order.id, _external=True)

        if usuarios_ids:
            notificar_usuarios(usuarios_ids, mensaje, 'orden_editada', order.id, enlace)

        # Guardar usuarios notificados
        order.set_usuarios_notificados(usuarios_ids)

        db.session.commit()
        flash('Orden actualizada correctamente.', 'success')
        return redirect(url_for('ordenes.edit_order', order_id=order.id))

    # GET: cargar datos
    form_data = {
        'order_num': order.order_num,
        'date': order.date.strftime('%Y-%m-%d') if order.date else '',
        'client_id': order.client_id,
        'client_nombre': order.client.nombre if order.client else '',
        'solicitado': order.solicitado,
        'proyecto': order.proyecto,
        'invoice': order.invoice,
        'tipo_proyecto': order.tipo_proyecto,
        'priority': order.priority,
        'descripcion': order.descripcion,
        'servicios': order.get_servicios()
    }

    context = _get_form_context(form_data=form_data, edit=True, order=order)
    return render_template('form_orden.html', **context)

# ==========================================
# CREAR CLIENTE VÍA AJAX (desde la orden)
# ==========================================
@ordenes_bp.route('/crear-cliente-ajax', methods=['POST'])
@login_required
@comercial_or_admin_required
def crear_cliente_ajax():
    data = request.get_json()
    nombre = data.get('nombre', '').strip()
    if not nombre:
        return jsonify({'error': 'El nombre es obligatorio'}), 400

    referencia = f"CLI-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    cliente = Client(
        referencia=referencia,
        nombre=nombre,
        telefono=data.get('telefono', ''),
        email=data.get('email', ''),
        direccion=data.get('direccion', '')
    )
    db.session.add(cliente)
    db.session.commit()
    return jsonify({'id': cliente.id, 'nombre': cliente.nombre})

# ==========================================
# ELIMINAR ARCHIVO ADJUNTO
# ==========================================
@ordenes_bp.route('/archivo/eliminar/<int:archivo_id>', methods=['POST'])
@login_required
@comercial_or_admin_required
def eliminar_archivo(archivo_id):
    archivo = ArchivoAdjunto.query.get_or_404(archivo_id)
    if current_user.role not in ['admin'] and archivo.orden.created_by_id != current_user.id:
        flash('No tienes permiso para eliminar este archivo.', 'danger')
        return redirect(url_for('ordenes.edit_order', order_id=archivo.orden_id))

    if archivo.ruta:
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'app/static/uploads')
        ruta_absoluta = os.path.join(upload_folder, archivo.ruta)
        if os.path.exists(ruta_absoluta):
            os.remove(ruta_absoluta)

    db.session.delete(archivo)
    db.session.commit()
    flash('Línea eliminada.', 'success')
    return redirect(url_for('ordenes.edit_order', order_id=archivo.orden_id))

# ==========================================
# MARCAR ENTRADA AL SISTEMA
# ==========================================
@ordenes_bp.route('/marcar-entrada/<int:order_id>', methods=['POST'])
@login_required
def marcar_entrada(order_id):
    order = Order.query.get_or_404(order_id)
    if current_user.role not in ['comercial', 'odalys', 'admin']:
        flash('No tienes permiso para marcar entrada.', 'danger')
        return redirect(url_for('ordenes.list_orders'))

    if order.entrada_ok:
        flash('Esta orden ya tiene entrada marcada.', 'info')
    else:
        order.entrada_ok = True
        order.add_history(f'Entrada al sistema marcada por {current_user.username}')
        db.session.commit()
        flash('Entrada al sistema marcada correctamente.', 'success')
    return redirect(url_for('ordenes.list_orders'))

# ==========================================
# ELIMINAR ORDEN
# ==========================================
@ordenes_bp.route('/eliminar/<int:order_id>', methods=['POST'])
@login_required
def delete_order(order_id):
    if current_user.role != 'admin':
        flash('Solo administradores pueden eliminar órdenes.', 'danger')
        return redirect(url_for('ordenes.list_orders'))
    order = Order.query.get_or_404(order_id)

    for archivo in order.archivos:
        if archivo.ruta:
            upload_folder = current_app.config.get('UPLOAD_FOLDER', 'app/static/uploads')
            ruta_absoluta = os.path.join(upload_folder, archivo.ruta)
            if os.path.exists(ruta_absoluta):
                os.remove(ruta_absoluta)

    db.session.delete(order)
    db.session.commit()
    flash('Orden eliminada permanentemente.', 'success')
    return redirect(url_for('ordenes.list_orders'))

# ==========================================
# GENERAR PDF
# ==========================================
@ordenes_bp.route('/pdf/<int:order_id>')
@login_required
def generar_pdf(order_id):
    order = Order.query.get_or_404(order_id)
    now = datetime.now()
    html_content = render_template('pdf_orden.html', order=order, now=now)
    pdf_file = HTML(string=html_content).write_pdf()
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as f:
        f.write(pdf_file)
        temp_path = f.name
    return send_file(temp_path, as_attachment=True, download_name=f'Orden_{order.order_num}.pdf', mimetype='application/pdf')

@ordenes_bp.route('/detalle_json/<int:order_id>')
@login_required
def detalle_json(order_id):
    order = Order.query.get_or_404(order_id)
    data = {
        'id': order.id,
        'numero': order.order_num,
        'cliente': order.client.nombre if order.client else 'Sin cliente',
        'cliente_id': order.client.id if order.client else None,
        'telefono_cliente': order.client.telefono if order.client and order.client.telefono else '',
        'prioridad': order.priority,
        'tipo': order.tipo_proyecto,
        'columna': order.column,
        'fecha_creacion': order.created_at.isoformat() if order.created_at else None,
        'historial': order.get_history(),
        'descripcion': order.descripcion,
        'servicios': order.get_servicios() if hasattr(order, 'get_servicios') else [],
        'materiales': order.get_materiales() if hasattr(order, 'get_materiales') else {},
        'archivos': [{'nombre': a.nombre_visible, 'ruta': a.ruta} for a in order.archivos],
        'fecha_entregado': order.fecha_entregado.isoformat() if order.fecha_entregado else None,
        'entrada_ok': order.entrada_ok,
        'proyecto': order.proyecto,
        'solicitado': order.solicitado,
        'invoice': order.invoice,
    }
    return jsonify(data)

# ==========================================
# DETALLE PARA MODAL (JSON)
# ==========================================
@ordenes_bp.route('/detalle_modal/<int:order_id>')
@login_required
def detalle_modal(order_id):
    order = Order.query.get_or_404(order_id)
    data = {
        'order_num': order.order_num,
        'client': order.client.nombre if order.client else 'Sin cliente',
        'date': order.date.strftime('%d/%m/%Y') if order.date else '-',
        'proyecto': order.proyecto,
        'priority': order.priority,
        'column': order.column,
        'entrada_ok': order.entrada_ok,
        'servicios': order.get_servicios(),
        'descripcion': order.descripcion,
        'lineas': [{
            'nombre_visible': a.nombre_visible,
            'material': a.material,
            'cantidad': a.cantidad,
            'unidad': a.unidad
        } for a in order.archivos]
    }
    return jsonify(data)