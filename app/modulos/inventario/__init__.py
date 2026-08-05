from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app.models import Producto, Movimiento, Order, OrdenProducto
from app import db
from datetime import datetime, timedelta
from sqlalchemy import func

inventario_bp = Blueprint('inventario', __name__, url_prefix='/inventario', template_folder='templates')

# ==========================================
# DECORADOR DE PERMISOS
# ==========================================
def economico_or_admin_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if current_user.role not in ['admin', 'economico']:
            flash('No tienes permiso para acceder al inventario.', 'danger')
            return redirect(url_for('home.home'))
        return func(*args, **kwargs)
    return wrapper

# ==========================================
# LISTADO DE PRODUCTOS
# ==========================================
@inventario_bp.route('/')
@login_required
@economico_or_admin_required
def index():
    productos = Producto.query.order_by(Producto.nombre).all()
    return render_template('inventario.html', productos=productos)

# ==========================================
# CREAR PRODUCTO
# ==========================================
@inventario_bp.route('/crear', methods=['GET', 'POST'])
@login_required
@economico_or_admin_required
def crear_producto():
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        tipo = request.form.get('tipo', '').strip()
        ubicacion = request.form.get('ubicacion', '').strip()
        unidad = request.form.get('unidad', '').strip()
        costo = request.form.get('costo', type=float, default=0.0)
        stock = request.form.get('stock', type=float, default=0.0)
        stock_minimo = request.form.get('stock_minimo', type=float, default=0.0)
        fecha_vencimiento = request.form.get('fecha_vencimiento', '')

        if not nombre:
            flash('El nombre es obligatorio.', 'danger')
            return render_template('form_producto.html')

        # Verificar duplicado
        if Producto.query.filter_by(nombre=nombre).first():
            flash('Ya existe un producto con ese nombre.', 'danger')
            return render_template('form_producto.html')

        producto = Producto(
            nombre=nombre,
            tipo=tipo,
            ubicacion=ubicacion,
            unidad=unidad,
            costo=costo,
            stock=stock,
            stock_minimo=stock_minimo
        )
        if fecha_vencimiento:
            try:
                producto.fecha_vencimiento = datetime.strptime(fecha_vencimiento, '%Y-%m-%d').date()
            except:
                pass

        db.session.add(producto)
        db.session.commit()

        # Registrar movimiento de entrada inicial (si stock > 0)
        if stock > 0:
            movimiento = Movimiento(
                producto_id=producto.id,
                tipo='entrada',
                cantidad=stock,
                comentario='Stock inicial',
                usuario_id=current_user.id
            )
            db.session.add(movimiento)
            db.session.commit()

        flash(f'Producto "{nombre}" creado correctamente.', 'success')
        return redirect(url_for('inventario.detalle_producto', producto_id=producto.id))

    return render_template('form_producto.html')

# ==========================================
# EDITAR PRODUCTO
# ==========================================
@inventario_bp.route('/editar/<int:producto_id>', methods=['GET', 'POST'])
@login_required
@economico_or_admin_required
def editar_producto(producto_id):
    producto = Producto.query.get_or_404(producto_id)

    if request.method == 'POST':
        producto.nombre = request.form.get('nombre', '').strip()
        producto.tipo = request.form.get('tipo', '').strip()
        producto.ubicacion = request.form.get('ubicacion', '').strip()
        producto.unidad = request.form.get('unidad', '').strip()
        producto.costo = request.form.get('costo', type=float, default=0.0)
        producto.stock_minimo = request.form.get('stock_minimo', type=float, default=0.0)
        fecha_vencimiento = request.form.get('fecha_vencimiento', '')
        if fecha_vencimiento:
            try:
                producto.fecha_vencimiento = datetime.strptime(fecha_vencimiento, '%Y-%m-%d').date()
            except:
                producto.fecha_vencimiento = None
        else:
            producto.fecha_vencimiento = None

        db.session.commit()
        flash(f'Producto "{producto.nombre}" actualizado correctamente.', 'success')
        return redirect(url_for('inventario.detalle_producto', producto_id=producto.id))

    return render_template('form_producto.html', producto=producto)

# ==========================================
# ELIMINAR PRODUCTO
# ==========================================
@inventario_bp.route('/eliminar/<int:producto_id>', methods=['POST'])
@login_required
@economico_or_admin_required
def eliminar_producto(producto_id):
    producto = Producto.query.get_or_404(producto_id)
    # Verificar si tiene movimientos o órdenes asociadas
    if Movimiento.query.filter_by(producto_id=producto.id).first():
        flash('No se puede eliminar un producto con movimientos registrados.', 'danger')
        return redirect(url_for('inventario.detalle_producto', producto_id=producto.id))
    if OrdenProducto.query.filter_by(producto_id=producto.id).first():
        flash('No se puede eliminar un producto asociado a órdenes.', 'danger')
        return redirect(url_for('inventario.detalle_producto', producto_id=producto.id))

    nombre = producto.nombre
    db.session.delete(producto)
    db.session.commit()
    flash(f'Producto "{nombre}" eliminado correctamente.', 'success')
    return redirect(url_for('inventario.index'))

# ==========================================
# DETALLE DE PRODUCTO
# ==========================================
@inventario_bp.route('/producto/<int:producto_id>')
@login_required
@economico_or_admin_required
def detalle_producto(producto_id):
    producto = Producto.query.get_or_404(producto_id)
    movimientos = Movimiento.query.filter_by(producto_id=producto_id).order_by(Movimiento.fecha.desc()).limit(50).all()
    return render_template('detalle_producto.html', producto=producto, movimientos=movimientos)

# ==========================================
# REGISTRAR COMPRA
# ==========================================
@inventario_bp.route('/comprar', methods=['POST'])
@login_required
@economico_or_admin_required
def comprar():
    producto_id = request.form.get('producto_id', type=int)
    cantidad = request.form.get('cantidad', type=float)
    costo = request.form.get('costo', type=float, default=0.0)
    comentario = request.form.get('comentario', '').strip()

    if not producto_id or not cantidad or cantidad <= 0:
        flash('Datos inválidos.', 'danger')
        return redirect(url_for('inventario.index'))

    producto = Producto.query.get(producto_id)
    if not producto:
        flash('Producto no encontrado.', 'danger')
        return redirect(url_for('inventario.index'))

    producto.stock += cantidad
    if costo > 0:
        producto.costo = costo

    movimiento = Movimiento(
        producto_id=producto.id,
        tipo='entrada',
        cantidad=cantidad,
        comentario=comentario or 'Compra',
        usuario_id=current_user.id
    )
    db.session.add(movimiento)
    db.session.commit()
    flash('Compra registrada correctamente.', 'success')
    return redirect(url_for('inventario.detalle_producto', producto_id=producto.id))

# ==========================================
# REGISTRAR AJUSTE (conteo físico)
# ==========================================
@inventario_bp.route('/ajustar', methods=['POST'])
@login_required
@economico_or_admin_required
def ajustar():
    producto_id = request.form.get('producto_id', type=int)
    stock_real = request.form.get('stock_real', type=float)
    comentario = request.form.get('comentario', '').strip()

    if not producto_id or stock_real is None or stock_real < 0:
        flash('Datos inválidos.', 'danger')
        return redirect(url_for('inventario.index'))

    producto = Producto.query.get(producto_id)
    if not producto:
        flash('Producto no encontrado.', 'danger')
        return redirect(url_for('inventario.index'))

    diferencia = producto.stock - stock_real

    if diferencia == 0:
        flash('El stock coincide con el real.', 'info')
        return redirect(url_for('inventario.detalle_producto', producto_id=producto.id))

    tipo = 'salida_ajuste' if diferencia > 0 else 'entrada_ajuste'
    cantidad = abs(diferencia)

    producto.stock = stock_real

    movimiento = Movimiento(
        producto_id=producto.id,
        tipo=tipo,
        cantidad=cantidad,
        comentario=comentario or f'Ajuste por conteo físico ({diferencia > 0 and "merma" or "sobrante"})',
        usuario_id=current_user.id
    )
    db.session.add(movimiento)
    db.session.commit()
    flash(f'Ajuste registrado. {diferencia > 0 and "Merma" or "Sobrante"}: {cantidad} {producto.unidad}', 'success')
    return redirect(url_for('inventario.detalle_producto', producto_id=producto.id))

# ==========================================
# REPORTE DE MERMA
# ==========================================
@inventario_bp.route('/merma')
@login_required
@economico_or_admin_required
def merma():
    mes = request.args.get('mes', type=int, default=datetime.now().month)
    anio = request.args.get('anio', type=int, default=datetime.now().year)

    inicio = datetime(anio, mes, 1)
    if mes == 12:
        fin = datetime(anio + 1, 1, 1) - timedelta(seconds=1)
    else:
        fin = datetime(anio, mes + 1, 1) - timedelta(seconds=1)

    productos = Producto.query.join(Movimiento).filter(
        Movimiento.fecha >= inicio,
        Movimiento.fecha <= fin
    ).distinct().all()

    datos = []
    for p in productos:
        entradas = Movimiento.query.filter(
            Movimiento.producto_id == p.id,
            Movimiento.tipo == 'entrada',
            Movimiento.fecha >= inicio,
            Movimiento.fecha <= fin
        ).with_entities(func.sum(Movimiento.cantidad)).scalar() or 0

        consumos = Movimiento.query.filter(
            Movimiento.producto_id == p.id,
            Movimiento.tipo == 'consumo',
            Movimiento.fecha >= inicio,
            Movimiento.fecha <= fin
        ).with_entities(func.sum(Movimiento.cantidad)).scalar() or 0

        ajustes_salida = Movimiento.query.filter(
            Movimiento.producto_id == p.id,
            Movimiento.tipo == 'salida_ajuste',
            Movimiento.fecha >= inicio,
            Movimiento.fecha <= fin
        ).with_entities(func.sum(Movimiento.cantidad)).scalar() or 0

        ajustes_entrada = Movimiento.query.filter(
            Movimiento.producto_id == p.id,
            Movimiento.tipo == 'entrada_ajuste',
            Movimiento.fecha >= inicio,
            Movimiento.fecha <= fin
        ).with_entities(func.sum(Movimiento.cantidad)).scalar() or 0

        merma_total = ajustes_salida - ajustes_entrada

        datos.append({
            'producto': p,
            'entradas': entradas,
            'consumos': consumos,
            'merma': merma_total,
            'porcentaje': (merma_total / (entradas + consumos) * 100) if (entradas + consumos) > 0 else 0
        })

    datos.sort(key=lambda x: x['merma'], reverse=True)

    return render_template('merma.html', datos=datos, mes=mes, anio=anio)

# ==========================================
# OBTENER MOVIMIENTOS (AJAX para modal)
# ==========================================
@inventario_bp.route('/movimientos/<int:producto_id>')
@login_required
@economico_or_admin_required
def movimientos(producto_id):
    producto = Producto.query.get_or_404(producto_id)
    movs = Movimiento.query.filter_by(producto_id=producto_id).order_by(Movimiento.fecha.desc()).limit(30).all()
    data = [{
        'id': m.id,
        'tipo': m.tipo,
        'cantidad': m.cantidad,
        'fecha': m.fecha.strftime('%d/%m/%Y %H:%M'),
        'comentario': m.comentario,
        'orden': m.orden.order_num if m.orden else None
    } for m in movs]
    return jsonify(data)