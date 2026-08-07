from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, current_app, jsonify
from flask_login import login_required, current_user
from app.models import Order, User, ArchivoAdjunto, Client, Producto, Movimiento, OrdenProducto, Categoria
from app import db
from weasyprint import HTML
import json
from datetime import datetime, timedelta
import tempfile
import os
import uuid
from werkzeug.utils import secure_filename
from app.services.notification_service import notificar_usuarios
import math

ordenes_bp = Blueprint('ordenes', __name__, url_prefix='/ordenes', template_folder='templates')

# ==========================================
# DECORADORES DE PERMISOS
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

def view_orders_or_admin_comercial_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if current_user.role not in ['comercial', 'admin', 'economico']:
            flash('No tienes permiso.', 'danger')
            return redirect(url_for('home.home'))
        return func(*args, **kwargs)
    return wrapper


# ==========================================
# FUNCIÓN AUXILIAR PARA CONTEXTO DEL FORMULARIO
# ==========================================
def _get_form_context(form_data=None, edit=False, order=None):
    servicios_disponibles = ['Diseño', 'Rúter', 'Láser', 'Montaje', 'Herrería']
    clients_list = Client.query.order_by(Client.nombre).all()
    clients_data = [{'id': c.id, 'nombre': c.nombre, 'referencia': c.referencia, 'telefono': c.telefono} for c in clients_list]
    todos_usuarios = User.query.filter_by(is_active=True).order_by(User.username).all()

    # Solo productos con stock > 0 para el selector de materiales
    productos = Producto.query.filter(Producto.stock > 0).order_by(Producto.nombre).all()
    productos_data = [{'id': p.id, 'nombre': p.nombre, 'unidad': p.unidad, 'stock': p.stock, 'ancho_rollo': p.ancho_rollo} for p in productos]

    context = {
        'servicios_disponibles': servicios_disponibles,
        'clients_list': clients_data,
        'todos_usuarios': todos_usuarios,
        'productos': productos_data,
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
@view_orders_or_admin_comercial_required
def list_orders():
    orders = Order.query.order_by(Order.created_at.desc()).all()
    return render_template('list_ordenes.html', orders=orders)


# ==========================================
# DETALLE DE ORDEN (SOLO LECTURA)
# ==========================================
@ordenes_bp.route('/detalle/<int:order_id>')
@login_required
def detalle_order(order_id):
    order = Order.query.get_or_404(order_id)
    columnas_nombres = {
        'pendiente': 'Pendiente',
        'por-preparar': 'Por preparar',
        'preparados': 'Preparados',
        'imprimir-hoy': 'Imprimir hoy',
        'impreso-corte': 'Impreso y corte',
        'listo': 'Listo',
        'entregados': 'Entregados'
    }
    return render_template('detalle_orden.html', order=order, now=datetime.now(), columnas_nombres=columnas_nombres)


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
# CONSUMIR MATERIALES (integración con inventario)
# ==========================================
def consumir_materiales(orden_id):
    """Consume los materiales de una orden al pasar a 'Impreso y corte'."""
    order = Order.query.get(orden_id)
    if not order:
        return False, "Orden no encontrada"

    op_items = OrdenProducto.query.filter_by(orden_id=orden_id).all()
    if not op_items:
        return True, "No hay materiales asociados a esta orden"

    for item in op_items:
        producto = Producto.query.get(item.producto_id)
        if not producto:
            continue

        if producto.stock < item.cantidad_estimada:
            return False, f"Stock insuficiente de {producto.nombre} (disponible: {producto.stock}, necesario: {item.cantidad_estimada})"

        producto.stock -= item.cantidad_estimada
        producto.stock_comprometido = max(0, (producto.stock_comprometido or 0) - item.cantidad_estimada)

        movimiento = Movimiento(
            producto_id=producto.id,
            tipo='consumo',
            cantidad=item.cantidad_estimada,
            comentario=f'Consumo para orden {order.order_num or "sin número"}',
            orden_id=order.id,
            usuario_id=current_user.id if hasattr(current_user, 'id') else None
        )
        db.session.add(movimiento)
        item.cantidad_real = item.cantidad_estimada

    db.session.commit()
    return True, "Materiales consumidos correctamente"


# ==========================================
# CREAR ORDEN
# ==========================================
@ordenes_bp.route('/crear', methods=['GET', 'POST'])
@login_required
@comercial_or_admin_required
def create_order():
    if request.method == 'POST':
        order_num = request.form.get('order_num', '').strip() or None
        date = request.form.get('date')
        client_id = request.form.get('client_id')
        solicitado = request.form.get('solicitado')
        tipo_proyecto = request.form.get('tipo_proyecto')
        priority = request.form.get('priority')
        descripcion = request.form.get('descripcion')

        if not client_id or not date:
            flash('Cliente y Fecha son obligatorios.', 'danger')
            context = _get_form_context(form_data=request.form, edit=False, order=None)
            return render_template('form_orden.html', **context)

        client = Client.query.get(client_id)
        if not client:
            flash('Cliente no encontrado.', 'danger')
            context = _get_form_context(form_data=request.form, edit=False, order=None)
            return render_template('form_orden.html', **context)

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
            proyecto='',
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

        # ============================================================
        # PROCESAR LÍNEAS DE TRABAJO
        # ============================================================
        nombres_visibles = request.form.getlist('nombres_visibles[]')
        productos_ids = request.form.getlist('productos_ids[]')
        cantidades = request.form.getlist('cantidades[]')
        unidades = request.form.getlist('unidades[]')
        proyectos_linea = request.form.getlist('proyecto_linea[]')

        ancho_etiqueta_list = request.form.getlist('ancho_etiqueta[]')
        alto_etiqueta_list = request.form.getlist('alto_etiqueta[]')
        precio_etiqueta_list = request.form.getlist('precio_etiqueta[]')
        mesa_etiqueta_list = request.form.getlist('mesa_etiqueta[]')
        girar_etiqueta_list = request.form.getlist('girar_etiqueta[]')
        auto_girar_etiqueta_list = request.form.getlist('auto_girar_etiqueta[]')

        for i, nombre_visible in enumerate(nombres_visibles):
            if not nombre_visible.strip():
                continue

            producto_id = int(productos_ids[i]) if i < len(productos_ids) and productos_ids[i] else None
            cantidad_str = cantidades[i] if i < len(cantidades) else ''
            unidad = unidades[i] if i < len(unidades) else 'm'
            cantidad_original = None
            if cantidad_str.strip():
                try:
                    cantidad_original = float(cantidad_str)
                except ValueError:
                    cantidad_original = None
            proyecto_linea = proyectos_linea[i] if i < len(proyectos_linea) else 'otros'
            producto = Producto.query.get(producto_id) if producto_id else None

            adjunto = None

            if proyecto_linea == 'etiquetas':
                if not producto:
                    flash(f'Línea {i+1}: Debes seleccionar un producto del inventario.', 'danger')
                    db.session.rollback()
                    context = _get_form_context(form_data=request.form, edit=False, order=None)
                    return render_template('form_orden.html', **context)

                ancho_cm = float(ancho_etiqueta_list[i]) if i < len(ancho_etiqueta_list) and ancho_etiqueta_list[i] else 0
                alto_cm = float(alto_etiqueta_list[i]) if i < len(alto_etiqueta_list) and alto_etiqueta_list[i] else 0
                precio = float(precio_etiqueta_list[i]) if i < len(precio_etiqueta_list) and precio_etiqueta_list[i] else 10.0
                mesa = mesa_etiqueta_list[i] == '1' if i < len(mesa_etiqueta_list) else False
                girar = girar_etiqueta_list[i] == '1' if i < len(girar_etiqueta_list) else False
                auto_girar = auto_girar_etiqueta_list[i] == '1' if i < len(auto_girar_etiqueta_list) else False

                if not ancho_cm or not alto_cm:
                    flash(f'Línea {i+1}: Faltan ancho o alto de etiqueta.', 'danger')
                    db.session.rollback()
                    context = _get_form_context(form_data=request.form, edit=False, order=None)
                    return render_template('form_orden.html', **context)

                ancho_rollo_m = producto.ancho_rollo or 1.3
                tipo_rollo = '1.3m' if ancho_rollo_m >= 1.3 else '1m'

                from app.modulos.etiquetas import calcular_datos

                if unidad == 'unidades':
                    cantidad_str_calc = str(cantidad_original) if cantidad_original else '0'
                    area_str_calc = ''
                else:  # metros
                    if cantidad_original:
                        area_calc = cantidad_original * ancho_rollo_m
                        area_str_calc = str(area_calc)
                        cantidad_str_calc = ''
                    else:
                        area_str_calc = ''
                        cantidad_str_calc = ''

                calculo = calcular_datos(
                    ancho_cm=ancho_cm,
                    alto_cm=alto_cm,
                    precio_m2=precio,
                    mesa_activo=mesa,
                    girar_activo=girar,
                    auto_girar_activo=auto_girar,
                    cantidad_str=cantidad_str_calc,
                    area_str=area_str_calc,
                    tipo_rollo=tipo_rollo
                )

                if calculo['error']:
                    flash(f'Línea {i+1}: {calculo["error"]}', 'danger')
                    db.session.rollback()
                    context = _get_form_context(form_data=request.form, edit=False, order=None)
                    return render_template('form_orden.html', **context)

                simData = calculo['simData']
                area_total = simData['areaTotal']

                # DETERMINAR CONSUMO Y COSTO SEGÚN UNIDAD
                if unidad == 'm':
                    # Consumo en metros lineales
                    consumo = cantidad_original if cantidad_original else 0
                    costo_estimado = consumo * precio
                else:
                    # Consumo en área (m²)
                    consumo = area_total
                    costo_estimado = area_total * precio

                if consumo <= 0:
                    flash(f'Línea {i+1}: El consumo estimado es cero.', 'danger')
                    db.session.rollback()
                    context = _get_form_context(form_data=request.form, edit=False, order=None)
                    return render_template('form_orden.html', **context)

                # Cálculo de metros completos y resto (solo para unidades)
                columnas = simData.get('columnas', 1)
                filasPorMetro = simData.get('filasPorMetro', 1)
                etiquetas_por_m2 = columnas * filasPorMetro
                metros_completos = 0
                resto_etiquetas = 0

                if unidad == 'unidades' and cantidad_original and etiquetas_por_m2 > 0:
                    metros_completos = int(cantidad_original // etiquetas_por_m2)
                    resto = cantidad_original % etiquetas_por_m2
                    if resto > 0:
                        filas_extra = math.ceil(resto / columnas)
                        resto_etiquetas = int(filas_extra * columnas)
                    else:
                        resto_etiquetas = 0
                else:
                    metros_completos = 0
                    resto_etiquetas = 0

                adjunto = ArchivoAdjunto(
                    orden_id=order.id,
                    nombre_original='',
                    nombre_visible=nombre_visible or f'Etiquetas {ancho_cm}x{alto_cm} cm',
                    material=producto.nombre,
                    ruta=None,
                    cantidad=cantidad_original if cantidad_original else 0,
                    unidad=unidad,
                    producto_id=producto.id,
                    parametros_etiqueta=json.dumps({
                        'ancho': ancho_cm,
                        'alto': alto_cm,
                        'tipo_rollo': tipo_rollo,
                        'modo': unidad,
                        'cantidad': cantidad_original,
                        'precio': precio,
                        'mesa': mesa,
                        'girar': girar,
                        'auto_girar': auto_girar,
                        'area_m2': area_total,
                        'etiquetas_por_m2': etiquetas_por_m2,
                        'costo_estimado': costo_estimado,
                        'metros_completos': metros_completos,
                        'resto_etiquetas': resto_etiquetas,
                        'columnas': columnas,
                        'filasPorMetro': filasPorMetro,
                        'consumo': consumo  # puede ser metros lineales o m²
                    })
                )
                db.session.add(adjunto)

                # RESERVA: usar 'consumo' (metros lineales o m² según unidad)
                op = OrdenProducto(
                    orden_id=order.id,
                    producto_id=producto.id,
                    cantidad_estimada=consumo
                )
                db.session.add(op)
                producto.stock_comprometido = (producto.stock_comprometido or 0) + consumo
                producto.stock -= consumo

                mov = Movimiento(
                    producto_id=producto.id,
                    tipo='reserva',
                    cantidad=consumo,
                    comentario=f'Reserva para orden {order_num or "sin número"} - línea {i+1} ({consumo:.2f} {"m" if unidad=="m" else "m²"})',
                    orden_id=order.id,
                    usuario_id=current_user.id
                )
                db.session.add(mov)

            else:
                adjunto = ArchivoAdjunto(
                    orden_id=order.id,
                    nombre_original='',
                    nombre_visible=nombre_visible,
                    material=producto.nombre if producto else None,
                    ruta=None,
                    cantidad=cantidad_original if cantidad_original else None,
                    unidad=unidad,
                    producto_id=producto.id if producto else None
                )
                db.session.add(adjunto)

                if producto and cantidad_original and cantidad_original > 0:
                    op = OrdenProducto(
                        orden_id=order.id,
                        producto_id=producto.id,
                        cantidad_estimada=cantidad_original
                    )
                    db.session.add(op)
                    producto.stock_comprometido = (producto.stock_comprometido or 0) + cantidad_original
                    producto.stock -= cantidad_original

                    mov = Movimiento(
                        producto_id=producto.id,
                        tipo='reserva',
                        cantidad=cantidad_original,
                        comentario=f'Reserva para orden {order_num or "sin número"} - línea {i+1}',
                        orden_id=order.id,
                        usuario_id=current_user.id
                    )
                    db.session.add(mov)

        # NOTIFICACIONES
        usuarios_ids = []
        usuarios_notificar = request.form.getlist('usuarios_notificar[]')
        usuarios_ids = [int(id) for id in usuarios_notificar if id.isdigit()]
        if client.comercial:
            comercial_user = User.query.filter_by(username=client.comercial).first()
            if comercial_user:
                usuarios_ids.append(comercial_user.id)
        if current_user.id not in usuarios_ids:
            usuarios_ids.append(current_user.id)
        mensaje = f'Nueva orden {order.order_num or "sin número"} creada por {current_user.username}'
        enlace = url_for('ordenes.edit_order', order_id=order.id, _external=True)
        if usuarios_ids:
            notificar_usuarios(usuarios_ids, mensaje, 'orden_creada', order.id, enlace)
        order.set_usuarios_notificados(usuarios_ids)

        db.session.commit()
        flash(f'Orden {order_num or "sin número"} creada correctamente.', 'success')
        return redirect(url_for('ordenes.edit_order', order_id=order.id))

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
        order_num = request.form.get('order_num', '').strip() or None
        order.order_num = order_num
        order.date = datetime.strptime(request.form.get('date'), '%Y-%m-%d')
        client_id = request.form.get('client_id')
        if client_id:
            client = Client.query.get(client_id)
            if client:
                order.client_id = client_id
            else:
                flash('Cliente no encontrado.', 'danger')
        order.solicitado = request.form.get('solicitado')
        order.proyecto = ''
        order.tipo_proyecto = request.form.get('tipo_proyecto')
        order.priority = request.form.get('priority')
        order.descripcion = request.form.get('descripcion')

        servicios = []
        for key in request.form:
            if key.startswith('serv_') and request.form.get(key) == 'on':
                serv_name = key[5:]
                servicios.append(serv_name)
        otros = request.form.get('servicios_otros', '').strip()
        if otros:
            servicios.append(f'Otros: {otros}')
        order.set_servicios(servicios)

        # ============================================================
        # ACTUALIZAR LÍNEAS EXISTENTES (edición)
        # ============================================================
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

        # ============================================================
        # ELIMINAR LÍNEAS MARCADAS
        # ============================================================
        ids_a_eliminar = request.form.getlist('eliminar_archivos[]')
        for archivo_id in ids_a_eliminar:
            archivo = ArchivoAdjunto.query.get(int(archivo_id))
            if archivo and archivo.orden_id == order.id:
                # Liberar reserva
                if archivo.producto_id and archivo.cantidad:
                    op = OrdenProducto.query.filter_by(orden_id=order.id, producto_id=archivo.producto_id).first()
                    if op:
                        cantidad_a_liberar = op.cantidad_estimada
                        producto = Producto.query.get(archivo.producto_id)
                        if producto:
                            producto.stock_comprometido = max(0, (producto.stock_comprometido or 0) - cantidad_a_liberar)
                            producto.stock += cantidad_a_liberar
                        db.session.delete(op)
                    else:
                        producto = Producto.query.get(archivo.producto_id)
                        if producto:
                            producto.stock_comprometido = max(0, (producto.stock_comprometido or 0) - archivo.cantidad)
                            producto.stock += archivo.cantidad
                db.session.delete(archivo)

        # ============================================================
        # PROCESAR NUEVAS LÍNEAS (añadidas en edición)
        # ============================================================
        nombres_visibles = request.form.getlist('nombres_visibles[]')
        productos_ids = request.form.getlist('productos_ids[]')
        cantidades = request.form.getlist('cantidades[]')
        unidades = request.form.getlist('unidades[]')
        proyectos_linea = request.form.getlist('proyecto_linea[]')

        ancho_etiqueta_list = request.form.getlist('ancho_etiqueta[]')
        alto_etiqueta_list = request.form.getlist('alto_etiqueta[]')
        precio_etiqueta_list = request.form.getlist('precio_etiqueta[]')
        mesa_etiqueta_list = request.form.getlist('mesa_etiqueta[]')
        girar_etiqueta_list = request.form.getlist('girar_etiqueta[]')
        auto_girar_etiqueta_list = request.form.getlist('auto_girar_etiqueta[]')

        for i, nombre_visible in enumerate(nombres_visibles):
            if not nombre_visible.strip():
                continue

            producto_id = int(productos_ids[i]) if i < len(productos_ids) and productos_ids[i] else None
            cantidad_str = cantidades[i] if i < len(cantidades) else ''
            unidad = unidades[i] if i < len(unidades) else 'm'
            cantidad_original = None
            if cantidad_str.strip():
                try:
                    cantidad_original = float(cantidad_str)
                except ValueError:
                    cantidad_original = None
            proyecto_linea = proyectos_linea[i] if i < len(proyectos_linea) else 'otros'
            producto = Producto.query.get(producto_id) if producto_id else None

            if proyecto_linea == 'etiquetas':
                if not producto:
                    flash(f'Línea {i+1}: Debes seleccionar un producto del inventario.', 'danger')
                    db.session.rollback()
                    context = _get_form_context(form_data=request.form, edit=True, order=order)
                    return render_template('form_orden.html', **context)

                ancho_cm = float(ancho_etiqueta_list[i]) if i < len(ancho_etiqueta_list) and ancho_etiqueta_list[i] else 0
                alto_cm = float(alto_etiqueta_list[i]) if i < len(alto_etiqueta_list) and alto_etiqueta_list[i] else 0
                precio = float(precio_etiqueta_list[i]) if i < len(precio_etiqueta_list) and precio_etiqueta_list[i] else 10.0
                mesa = mesa_etiqueta_list[i] == '1' if i < len(mesa_etiqueta_list) else False
                girar = girar_etiqueta_list[i] == '1' if i < len(girar_etiqueta_list) else False
                auto_girar = auto_girar_etiqueta_list[i] == '1' if i < len(auto_girar_etiqueta_list) else False

                ancho_rollo_m = producto.ancho_rollo or 1.3
                tipo_rollo = '1.3m' if ancho_rollo_m >= 1.3 else '1m'

                from app.modulos.etiquetas import calcular_datos

                if unidad == 'unidades':
                    cantidad_str_calc = str(cantidad_original) if cantidad_original else '0'
                    area_str_calc = ''
                else:
                    if cantidad_original:
                        area_calc = cantidad_original * ancho_rollo_m
                        area_str_calc = str(area_calc)
                        cantidad_str_calc = ''
                    else:
                        area_str_calc = ''
                        cantidad_str_calc = ''

                calculo = calcular_datos(
                    ancho_cm=ancho_cm,
                    alto_cm=alto_cm,
                    precio_m2=precio,
                    mesa_activo=mesa,
                    girar_activo=girar,
                    auto_girar_activo=auto_girar,
                    cantidad_str=cantidad_str_calc,
                    area_str=area_str_calc,
                    tipo_rollo=tipo_rollo
                )

                if calculo['error']:
                    flash(f'Línea {i+1}: {calculo["error"]}', 'danger')
                    db.session.rollback()
                    context = _get_form_context(form_data=request.form, edit=True, order=order)
                    return render_template('form_orden.html', **context)

                simData = calculo['simData']
                area_total = simData['areaTotal']

                if unidad == 'm':
                    consumo = cantidad_original if cantidad_original else 0
                    costo_estimado = consumo * precio
                else:
                    consumo = area_total
                    costo_estimado = area_total * precio

                if consumo <= 0:
                    flash(f'Línea {i+1}: Consumo cero.', 'danger')
                    db.session.rollback()
                    context = _get_form_context(form_data=request.form, edit=True, order=order)
                    return render_template('form_orden.html', **context)

                columnas = simData.get('columnas', 1)
                filasPorMetro = simData.get('filasPorMetro', 1)
                etiquetas_por_m2 = columnas * filasPorMetro
                metros_completos = 0
                resto_etiquetas = 0

                if unidad == 'unidades' and cantidad_original and etiquetas_por_m2 > 0:
                    metros_completos = int(cantidad_original // etiquetas_por_m2)
                    resto = cantidad_original % etiquetas_por_m2
                    if resto > 0:
                        filas_extra = math.ceil(resto / columnas)
                        resto_etiquetas = int(filas_extra * columnas)
                    else:
                        resto_etiquetas = 0
                else:
                    metros_completos = 0
                    resto_etiquetas = 0

                adjunto = ArchivoAdjunto(
                    orden_id=order.id,
                    nombre_original='',
                    nombre_visible=nombre_visible or f'Etiquetas {ancho_cm}x{alto_cm} cm',
                    material=producto.nombre,
                    ruta=None,
                    cantidad=cantidad_original if cantidad_original else 0,
                    unidad=unidad,
                    producto_id=producto.id,
                    parametros_etiqueta=json.dumps({
                        'ancho': ancho_cm,
                        'alto': alto_cm,
                        'tipo_rollo': tipo_rollo,
                        'modo': unidad,
                        'cantidad': cantidad_original,
                        'precio': precio,
                        'mesa': mesa,
                        'girar': girar,
                        'auto_girar': auto_girar,
                        'area_m2': area_total,
                        'etiquetas_por_m2': etiquetas_por_m2,
                        'costo_estimado': costo_estimado,
                        'metros_completos': metros_completos,
                        'resto_etiquetas': resto_etiquetas,
                        'columnas': columnas,
                        'filasPorMetro': filasPorMetro,
                        'consumo': consumo
                    })
                )
                db.session.add(adjunto)

                op = OrdenProducto(
                    orden_id=order.id,
                    producto_id=producto.id,
                    cantidad_estimada=consumo
                )
                db.session.add(op)
                producto.stock_comprometido = (producto.stock_comprometido or 0) + consumo
                producto.stock -= consumo

                mov = Movimiento(
                    producto_id=producto.id,
                    tipo='reserva',
                    cantidad=consumo,
                    comentario=f'Reserva para orden {order_num or "sin número"} - línea {i+1} ({consumo:.2f} {"m" if unidad=="m" else "m²"})',
                    orden_id=order.id,
                    usuario_id=current_user.id
                )
                db.session.add(mov)

            else:
                adjunto = ArchivoAdjunto(
                    orden_id=order.id,
                    nombre_original='',
                    nombre_visible=nombre_visible,
                    material=producto.nombre if producto else None,
                    ruta=None,
                    cantidad=cantidad_original if cantidad_original else None,
                    unidad=unidad,
                    producto_id=producto.id if producto else None
                )
                db.session.add(adjunto)

                if producto and cantidad_original and cantidad_original > 0:
                    op = OrdenProducto(
                        orden_id=order.id,
                        producto_id=producto.id,
                        cantidad_estimada=cantidad_original
                    )
                    db.session.add(op)
                    producto.stock_comprometido = (producto.stock_comprometido or 0) + cantidad_original
                    producto.stock -= cantidad_original

                    mov = Movimiento(
                        producto_id=producto.id,
                        tipo='reserva',
                        cantidad=cantidad_original,
                        comentario=f'Reserva para orden {order_num or "sin número"} - línea {i+1}',
                        orden_id=order.id,
                        usuario_id=current_user.id
                    )
                    db.session.add(mov)

        order.add_history(f'Editada por {current_user.username}')

        # NOTIFICACIONES
        usuarios_ids = []
        usuarios_notificar = request.form.getlist('usuarios_notificar[]')
        usuarios_ids = [int(id) for id in usuarios_notificar if id.isdigit()]
        if order.client and order.client.comercial:
            comercial_user = User.query.filter_by(username=order.client.comercial).first()
            if comercial_user:
                usuarios_ids.append(comercial_user.id)
        if current_user.id not in usuarios_ids:
            usuarios_ids.append(current_user.id)
        mensaje = f'Orden {order.order_num or "sin número"} actualizada por {current_user.username}'
        enlace = url_for('ordenes.edit_order', order_id=order.id, _external=True)
        if usuarios_ids:
            notificar_usuarios(usuarios_ids, mensaje, 'orden_editada', order.id, enlace)
        order.set_usuarios_notificados(usuarios_ids)

        db.session.commit()
        flash('Orden actualizada correctamente.', 'success')
        return redirect(url_for('ordenes.edit_order', order_id=order.id))

    # GET
    productos_asociados = OrdenProducto.query.filter_by(orden_id=order.id).all()
    productos_data = []
    for op in productos_asociados:
        productos_data.append({
            'producto_id': op.producto_id,
            'cantidad': op.cantidad_estimada,
            'nombre': op.producto.nombre if op.producto else ''
        })

    form_data = {
        'order_num': order.order_num,
        'date': order.date.strftime('%Y-%m-%d') if order.date else '',
        'client_id': order.client_id,
        'client_nombre': order.client.nombre if order.client else '',
        'solicitado': order.solicitado,
        'tipo_proyecto': order.tipo_proyecto,
        'priority': order.priority,
        'descripcion': order.descripcion,
        'servicios': order.get_servicios(),
        'productos_asociados': productos_data
    }
    context = _get_form_context(form_data=form_data, edit=True, order=order)
    return render_template('form_orden.html', **context)


# ==========================================
# CREAR CLIENTE VÍA AJAX
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
# ELIMINAR ARCHIVO ADJUNTO (LÍNEA) - solo para uso interno (ya no se usa directamente)
# ==========================================
@ordenes_bp.route('/archivo/eliminar/<int:archivo_id>', methods=['POST'])
@login_required
@comercial_or_admin_required
def eliminar_archivo(archivo_id):
    # Esta ruta ya no se usa en edición, se mantiene por compatibilidad pero no se llama
    return jsonify({'success': False, 'error': 'Método obsoleto'}), 405


# ==========================================
# MARCAR ENTRADA AL SISTEMA (CON NÚMERO DE ODOO)
# ==========================================
@ordenes_bp.route('/marcar-entrada/<int:order_id>', methods=['POST'])
@login_required
def marcar_entrada(order_id):
    order = Order.query.get_or_404(order_id)
    if current_user.role not in ['comercial', 'odalys', 'admin', 'economico']:
        flash('No tienes permiso para marcar entrada.', 'danger')
        return redirect(url_for('ordenes.list_orders'))

    if order.entrada_ok:
        flash('Esta orden ya tiene entrada marcada.', 'info')
        return redirect(url_for('ordenes.list_orders'))

    odoo_order_num = request.form.get('odoo_order_num', '').strip()
    if not odoo_order_num:
        flash('Debes ingresar el número de orden de Odoo.', 'danger')
        return redirect(url_for('ordenes.list_orders'))

    order.order_num = odoo_order_num
    order.entrada_ok = True
    order.add_history(f'Entrada al sistema marcada por {current_user.username} con número {odoo_order_num}')
    db.session.commit()
    flash(f'Orden {odoo_order_num} marcada como entrada al sistema.', 'success')
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

    # Liberar stock comprometido
    for op in OrdenProducto.query.filter_by(orden_id=order.id).all():
        producto = Producto.query.get(op.producto_id)
        if producto:
            producto.stock_comprometido = max(0, (producto.stock_comprometido or 0) - op.cantidad_estimada)
            producto.stock += op.cantidad_estimada
        db.session.delete(op)

    Movimiento.query.filter_by(orden_id=order.id).delete()

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
    return send_file(temp_path, as_attachment=True, download_name=f'Orden_{order.order_num or "sin_numero"}.pdf', mimetype='application/pdf')


# ==========================================
# DETALLE JSON (para workflow)
# ==========================================
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
        'archivos': [{'nombre': a.nombre_visible, 'ruta': a.ruta} for a in order.archivos],
        'fecha_entregado': order.fecha_entregado.isoformat() if order.fecha_entregado else None,
        'entrada_ok': order.entrada_ok,
        'proyecto': order.proyecto,
        'solicitado': order.solicitado,
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