from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import Order, User
from app import db
import json
from datetime import datetime

ordenes_bp = Blueprint('ordenes', __name__, url_prefix='/ordenes', template_folder='templates')

# ==========================================
# DECORADOR DE PERMISOS (solo comercial o admin)
# ==========================================
def comercial_or_admin_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if current_user.role not in ['comercial', 'admin']:
            flash('No tienes permiso para acceder a esta sección.', 'danger')
            return redirect(url_for('home.home'))
        return func(*args, **kwargs)
    return wrapper

# ==========================================
# LISTAR ÓRDENES
# ==========================================
@ordenes_bp.route('/')
@login_required
@comercial_or_admin_required
def list_orders():
    orders = Order.query.order_by(Order.created_at.desc()).all()
    return render_template('list.html', orders=orders)

# ==========================================
# CREAR ORDEN
# ==========================================
@ordenes_bp.route('/crear', methods=['GET', 'POST'])
@login_required
@comercial_or_admin_required
def create_order():
    if request.method == 'POST':
        # Recoger datos del formulario
        order_num = request.form.get('order_num')
        date = request.form.get('date')
        client = request.form.get('client')
        solicitado = request.form.get('solicitado')
        proyecto = request.form.get('proyecto')
        invoice = request.form.get('invoice')
        tipo_proyecto = request.form.get('tipo_proyecto')
        priority = request.form.get('priority')
        descripcion = request.form.get('descripcion')
        incidencias = request.form.get('incidencias')

        # Validaciones básicas
        if not order_num or not client or not date:
            flash('N° de orden, Cliente y Fecha son obligatorios.', 'danger')
            return render_template('form.html', form_data=request.form)

        # Procesar materiales (checkboxes + cantidades)
        materiales = {}
        for key in request.form:
            if key.startswith('mat_') and request.form.get(key) == 'on':
                mat_name = key[4:]  # eliminar 'mat_'
                cant_key = f'cant_{mat_name}'
                cantidad = request.form.get(cant_key, '1')
                materiales[mat_name] = cantidad

        # Procesar servicios (checkboxes)
        servicios = []
        for key in request.form:
            if key.startswith('serv_') and request.form.get(key) == 'on':
                serv_name = key[5:]
                servicios.append(serv_name)
        # Servicio "Otros"
        otros = request.form.get('servicios_otros', '').strip()
        if otros:
            servicios.append(f'Otros: {otros}')

        # Crear orden
        order = Order(
            order_num=order_num,
            date=datetime.strptime(date, '%Y-%m-%d'),
            client=client,
            solicitado=solicitado,
            proyecto=proyecto,
            invoice=invoice,
            tipo_proyecto=tipo_proyecto,
            priority=priority,
            materiales=json.dumps(materiales),
            servicios=json.dumps(servicios),
            descripcion=descripcion,
            incidencias=incidencias,
            column='pendiente',
            entrada_ok=False,
            created_by_id=current_user.id
        )
        order.add_history(f'Creada por {current_user.username}')
        db.session.add(order)
        db.session.commit()

        # Guardar archivos adjuntos
        uploaded_files = save_uploaded_files(request.files.getlist('files[]'), order.id)
        if uploaded_files:
            order.add_history(f'Archivos adjuntos: {", ".join(uploaded_files)}')
            db.session.commit()

        flash(f'Orden {order_num} creada correctamente.', 'success')
        return redirect(url_for('ordenes.edit_order', order_id=order.id))

    # GET: mostrar formulario vacío
    return render_template('form.html', form_data=None)

# ==========================================
# EDITAR ORDEN
# ==========================================
@ordenes_bp.route('/editar/<int:order_id>', methods=['GET', 'POST'])
@login_required
@comercial_or_admin_required
def edit_order(order_id):
    order = Order.query.get_or_404(order_id)

    if request.method == 'POST':
        # Actualizar campos
        order.order_num = request.form.get('order_num')
        order.date = datetime.strptime(request.form.get('date'), '%Y-%m-%d')
        order.client = request.form.get('client')
        order.solicitado = request.form.get('solicitado')
        order.proyecto = request.form.get('proyecto')
        order.invoice = request.form.get('invoice')
        order.tipo_proyecto = request.form.get('tipo_proyecto')
        order.priority = request.form.get('priority')
        order.descripcion = request.form.get('descripcion')
        order.incidencias = request.form.get('incidencias')

        # Materiales
        materiales = {}
        for key in request.form:
            if key.startswith('mat_') and request.form.get(key) == 'on':
                mat_name = key[4:]
                cant_key = f'cant_{mat_name}'
                cantidad = request.form.get(cant_key, '1')
                materiales[mat_name] = cantidad
        order.materiales = json.dumps(materiales)

        # Servicios
        servicios = []
        for key in request.form:
            if key.startswith('serv_') and request.form.get(key) == 'on':
                serv_name = key[5:]
                servicios.append(serv_name)
        otros = request.form.get('servicios_otros', '').strip()
        if otros:
            servicios.append(f'Otros: {otros}')
        order.servicios = json.dumps(servicios)

        order.add_history(f'Editada por {current_user.username}')
        db.session.commit()
        flash('Orden actualizada correctamente.', 'success')
        return redirect(url_for('ordenes.edit_order', order_id=order.id))

    # GET: mostrar formulario con datos existentes
    form_data = {
        'order_num': order.order_num,
        'date': order.date.strftime('%Y-%m-%d') if order.date else '',
        'client': order.client,
        'solicitado': order.solicitado,
        'proyecto': order.proyecto,
        'invoice': order.invoice,
        'tipo_proyecto': order.tipo_proyecto,
        'priority': order.priority,
        'descripcion': order.descripcion,
        'incidencias': order.incidencias,
        'materiales': order.get_materiales(),
        'servicios': order.get_servicios()
    }
    return render_template('form.html', form_data=form_data, edit=True, order=order)

# ==========================================
# MARCAR ENTRADA AL SISTEMA
# ==========================================
@ordenes_bp.route('/marcar-entrada/<int:order_id>', methods=['POST'])
@login_required
def marcar_entrada(order_id):
    order = Order.query.get_or_404(order_id)
    # Solo comercial, odalys o admin pueden marcar entrada
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
# ELIMINAR ORDEN (solo admin)
# ==========================================
@ordenes_bp.route('/eliminar/<int:order_id>', methods=['POST'])
@login_required
def delete_order(order_id):
    if current_user.role != 'admin':
        flash('Solo administradores pueden eliminar órdenes.', 'danger')
        return redirect(url_for('ordenes.list_orders'))

    order = Order.query.get_or_404(order_id)
    db.session.delete(order)
    db.session.commit()
    flash('Orden eliminada permanentemente.', 'success')
    return redirect(url_for('ordenes.list_orders'))

import os
from werkzeug.utils import secure_filename
from flask import current_app

# Configuración para subida de archivos
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'uploads', 'ordenes')
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'ai', 'cdr', 'eps', 'svg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_uploaded_files(files, order_id):
    """Guarda los archivos subidos en la carpeta correspondiente."""
    if not files:
        return []
    saved_files = []
    for file in files:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            # Crear carpeta por orden
            order_folder = os.path.join(UPLOAD_FOLDER, str(order_id))
            os.makedirs(order_folder, exist_ok=True)
            filepath = os.path.join(order_folder, filename)
            file.save(filepath)
            saved_files.append(filename)
    return saved_files

from flask import send_file
from weasyprint import HTML
import tempfile
import os

@ordenes_bp.route('/pdf/<int:order_id>')
@login_required
def generar_pdf(order_id):
    """Genera un PDF bonito de la orden usando WeasyPrint."""
    order = Order.query.get_or_404(order_id)
    
    # Renderizar la plantilla HTML con los datos de la orden
    html_content = render_template('pdf_orden.html', order=order)
    
    # Generar PDF desde HTML
    pdf_file = HTML(string=html_content).write_pdf()
    
    # Guardar en un archivo temporal para enviar
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as f:
        f.write(pdf_file)
        temp_path = f.name
    
    return send_file(temp_path, as_attachment=True, download_name=f'Orden_{order.order_num}.pdf', mimetype='application/pdf')