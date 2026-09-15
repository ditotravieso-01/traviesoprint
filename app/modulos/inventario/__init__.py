from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import login_required, current_user
from app.models import Producto, Movimiento, Order, OrdenProducto, Categoria, Area, Ubicacion, TipoProducto, Unidad, GrupoAtributos, Atributo, Client, Proveedor, User, ArchivoAdjunto
from app import db
from datetime import datetime, timedelta, date
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from collections import defaultdict
from openpyxl.styles import Font, Alignment, PatternFill
from werkzeug.utils import secure_filename
import io
import openpyxl
import os
import tempfile
import json
import math

from app.services.notification_service import notificar_usuarios

inventario_bp = Blueprint('inventario', __name__, url_prefix='/inventario', template_folder='templates')

# ==========================================
# DECORADORES DE PERMISOS
# ==========================================
def economico_or_admin_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if current_user.role not in ['admin', 'economico']:
            flash('No tienes permiso para acceder al inventario.', 'danger')
            return redirect(url_for('home.index'))
        return func(*args, **kwargs)
    return wrapper

def admin_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if current_user.role != 'admin':
            flash('Solo el administrador puede realizar esta acción.', 'danger')
            return redirect(url_for('inventario.index'))
        return func(*args, **kwargs)
    return wrapper

# ==========================================
# NOTIFICAR STOCK BAJO
# ==========================================
def verificar_y_notificar_stock_bajo(producto):
    if not producto or producto.stock_minimo is None or producto.stock_minimo <= 0:
        return
    if producto.stock < producto.stock_minimo:
        usuarios = User.query.filter(User.role.in_(['economico', 'admin'])).all()
        if not usuarios:
            return
        mensaje = f"⚠️ Stock crítico: {producto.nombre} (stock: {producto.stock:.2f} {producto.unidad or 'u'}, mínimo: {producto.stock_minimo:.2f})"
        enlace = url_for('inventario.detalle_producto', producto_id=producto.id, _external=True)
        usuario_ids = [u.id for u in usuarios]
        notificar_usuarios(
            usuario_ids=usuario_ids,
            mensaje=mensaje,
            tipo='stock_bajo',
            order_id=None,
            enlace=enlace
        )

# ==========================================
# AUXILIARES DE CATEGORÍAS
# ==========================================
def get_categoria_tree():
    root_cats = Categoria.query.filter_by(parent_id=None).order_by(Categoria.nombre).all()
    def build_tree(cat):
        children = Categoria.query.filter_by(parent_id=cat.id).order_by(Categoria.nombre).all()
        return {
            'id': cat.id,
            'nombre': cat.nombre,
            'descripcion': cat.descripcion,
            'es_material_impresion': cat.es_material_impresion,
            'children': [build_tree(c) for c in children]
        }
    return [build_tree(c) for c in root_cats]

def get_categoria_options(cats=None, nivel=0):
    """
    Devuelve la lista plana de categorías con indentación visual según nivel.
    - nivel 0: 'Materiales de Impresión'
    - nivel 1: '　└─ Rollos'
    - nivel 2: '　　└─ vinilo'
    """
    if cats is None:
        cats = Categoria.query.filter_by(parent_id=None).order_by(Categoria.nombre).all()
    options = []
    for cat in cats:
        if nivel == 0:
            display = cat.nombre
        else:
            display = ('　' * (nivel - 1)) + '└─ ' + cat.nombre
        options.append({
            'id': cat.id,
            'nombre': display,           # nombre visible con indentación
            'nombre_puro': cat.nombre,   # nombre sin indentación
            'nivel': nivel,
        })
        children = Categoria.query.filter_by(parent_id=cat.id).order_by(Categoria.nombre).all()
        options.extend(get_categoria_options(children, nivel + 1))
    return options

def get_all_subcategory_ids(categoria_id):
    """Devuelve [id_categoria] + [ids de todos los descendientes]."""
    if not categoria_id:
        return []
    cat = Categoria.query.get(categoria_id)
    if not cat:
        return []
    ids = [cat.id]
    def get_child_ids(parent):
        children = Categoria.query.filter_by(parent_id=parent.id).all()
        for child in children:
            ids.append(child.id)
            get_child_ids(child)
    get_child_ids(cat)
    return ids

def get_grupo_atributos_para_categoria(categoria_id):
    """
    Devuelve el grupo de atributos asociado a la categoría O a su ancestro más cercano.
    Así un grupo definido en 'Rollos' aplica también a 'vinilo', 'backlit', etc.
    """
    if not categoria_id:
        return None
    cat = Categoria.query.get(categoria_id)
    while cat:
        grupo = GrupoAtributos.query.filter_by(categoria_id=cat.id).first()
        if grupo:
            return grupo
        cat = cat.parent
    return None

# ==========================================
# MERMA OPERATIVA ACUMULADA POR PRODUCTO
# ==========================================
def calcular_merma_estimada_producto(producto_id):
    archivos = ArchivoAdjunto.query.filter(
        ArchivoAdjunto.producto_id == producto_id,
        ArchivoAdjunto.parametros_etiqueta.isnot(None)
    ).all()

    area_facturada = 0.0
    material_consumido = 0.0
    merma_operativa = 0.0
    merma_borde = 0.0
    merma_cut = 0.0
    merma_gap = 0.0
    merma_interna = 0.0
    total_lineas = 0
    ordenes_ids = set()

    for a in archivos:
        try:
            params = json.loads(a.parametros_etiqueta) if a.parametros_etiqueta else {}
        except Exception:
            continue
        if 'merma_operativa_m2' not in params and 'merma_estimada_m2' not in params:
            continue

        area_facturada += float(params.get('area_m2', 0) or 0)
        material_consumido += float(params.get('material_consumido_m2', 0) or 0)
        merma_operativa += float(params.get('merma_operativa_m2', params.get('merma_estimada_m2', 0)) or 0)
        merma_borde += float(params.get('merma_borde_rollo_m2', 0) or 0)
        merma_cut += float(params.get('merma_cut_marks_m2', 0) or 0)
        merma_gap += float(params.get('merma_gap_m2', 0) or 0)
        merma_interna += float(params.get('merma_interna_m2', 0) or 0)
        total_lineas += 1
        if a.orden_id:
            ordenes_ids.add(a.orden_id)

    if total_lineas == 0:
        return None

    merma_pct = (merma_operativa / area_facturada * 100) if area_facturada > 0 else 0

    return {
        'area_facturada_m2': round(area_facturada, 2),
        'material_consumido_m2': round(material_consumido, 2),
        'merma_operativa_m2': round(merma_operativa, 2),
        'merma_operativa_pct': round(merma_pct, 2),
        'merma_borde_rollo_m2': round(merma_borde, 2),
        'merma_cut_marks_m2': round(merma_cut, 2),
        'merma_gap_m2': round(merma_gap, 2),
        'merma_interna_m2': round(merma_interna, 2),
        'total_lineas': total_lineas,
        'total_ordenes': len(ordenes_ids),
    }

# ==========================================
# DASHBOARD
# ==========================================
@inventario_bp.route('/')
@login_required
@economico_or_admin_required
def index():
    total_productos = Producto.query.count()
    stock_total = db.session.query(func.sum(Producto.stock)).scalar() or 0
    stock_metros_total = db.session.query(func.sum(Producto.stock_metros)).scalar() or 0
    productos = Producto.query.all()
    stock_m2_total = 0
    for p in productos:
        if p.es_material_impresion and p.ancho_rollo and p.ancho_rollo > 0:
            stock_m2_total += (p.stock_metros or 0) * p.ancho_rollo
        else:
            stock_m2_total += (p.stock_metros or 0)
    stock_m2_total = round(stock_m2_total, 2)
    valor_total = db.session.query(func.sum(Producto.inversion_total)).scalar() or 0
    criticos = Producto.query.filter(Producto.stock < Producto.stock_minimo).count()

    ultimos_movimientos = Movimiento.query.order_by(Movimiento.fecha.desc()).limit(10).all()
    for m in ultimos_movimientos:
        if m.producto and m.producto.es_material_impresion and m.producto.ancho_rollo and m.producto.ancho_rollo > 0:
            metros = m.cantidad_metros if m.cantidad_metros else m.cantidad
            m.cantidad_m2 = metros * m.producto.ancho_rollo
        else:
            m.cantidad_m2 = None

    root_cats = Categoria.query.filter_by(parent_id=None).order_by(Categoria.nombre).all()
    categorias_data = []
    for cat in root_cats:
        cat_ids = get_all_subcategory_ids(cat.id)
        productos_cat = Producto.query.filter(Producto.categoria_id.in_(cat_ids)).all()
        categorias_data.append({
            'categoria': cat,
            'total_productos': len(productos_cat),
            'stock_total': sum(p.stock or 0 for p in productos_cat),
            'inversion_total': sum(p.inversion_total or 0 for p in productos_cat)
        })

    hoy = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    inicio = hoy - timedelta(days=30)
    movs = Movimiento.query.filter(Movimiento.fecha >= inicio).order_by(Movimiento.fecha).all()
    fechas = []
    valores = []
    saldo = 0
    for d in range(31):
        fecha = inicio + timedelta(days=d)
        fechas.append(fecha.strftime('%d/%m'))
        dia_movs = [m for m in movs if m.fecha.date() == fecha.date()]
        for m in dia_movs:
            if m.tipo in ['entrada', 'entrada_ajuste']:
                saldo += m.cantidad
            elif m.tipo in ['consumo', 'salida_ajuste', 'reserva']:
                saldo -= m.cantidad
        valores.append(round(saldo, 2))

    inicio_mes = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    archivos_mes = ArchivoAdjunto.query.filter(
        ArchivoAdjunto.parametros_etiqueta.isnot(None)
    ).join(Order, ArchivoAdjunto.orden_id == Order.id).filter(
        Order.date >= inicio_mes.date()
    ).all()

    merma_mes_m2 = 0.0
    area_facturada_mes_m2 = 0.0
    for a in archivos_mes:
        try:
            params = json.loads(a.parametros_etiqueta) if a.parametros_etiqueta else {}
        except Exception:
            continue
        if 'merma_operativa_m2' in params or 'merma_estimada_m2' in params:
            merma_mes_m2 += float(params.get('merma_operativa_m2', params.get('merma_estimada_m2', 0)) or 0)
            area_facturada_mes_m2 += float(params.get('area_m2', 0) or 0)
    merma_mes_pct = (merma_mes_m2 / area_facturada_mes_m2 * 100) if area_facturada_mes_m2 > 0 else 0

    return render_template('inventario.html',
                           total_productos=total_productos,
                           stock_total=round(stock_total, 2),
                           stock_metros_total=round(stock_metros_total, 2),
                           stock_m2_total=stock_m2_total,
                           valor_total=round(valor_total, 2),
                           criticos=criticos,
                           ultimos_movimientos=ultimos_movimientos,
                           categorias_data=categorias_data,
                           merma_estimada_mes_m2=round(merma_mes_m2, 2),
                           merma_estimada_mes_pct=round(merma_mes_pct, 1),
                           fechas_json=json.dumps(fechas),
                           valores_json=json.dumps(valores))

# ==========================================
# TODOS LOS PRODUCTOS
# ==========================================
@inventario_bp.route('/todos')
@login_required
@economico_or_admin_required
def todos_productos():
    categoria_id = request.args.get('categoria', type=int)
    search = request.args.get('search', '').strip()
    sort = request.args.get('sort', 'nombre')
    order = request.args.get('order', 'asc')
    page = request.args.get('page', 1, type=int)
    per_page = 20

    query = Producto.query
    if categoria_id:
        cat_ids = get_all_subcategory_ids(categoria_id)
        if cat_ids:
            query = query.filter(Producto.categoria_id.in_(cat_ids))
    if search:
        query = query.filter(Producto.nombre.ilike(f'%{search}%'))

    if sort == 'nombre':
        col = Producto.nombre
    elif sort == 'stock':
        col = Producto.stock
    elif sort == 'disponible':
        col = (Producto.stock - Producto.stock_comprometido).label('disponible')
    elif sort == 'comprometido':
        col = Producto.stock_comprometido
    elif sort == 'costo':
        col = Producto.costo
    elif sort == 'categoria':
        col = Producto.categoria_id
    else:
        col = Producto.nombre

    if order == 'desc':
        query = query.order_by(col.desc())
    else:
        query = query.order_by(col.asc())

    paginated = query.paginate(page=page, per_page=per_page, error_out=False)
    productos = paginated.items
    total = paginated.total
    total_pages = paginated.pages

    for p in productos:
        p.disponible = (p.stock or 0) - (p.stock_comprometido or 0)
        p.disponible_metros = (p.stock_metros or 0) - (p.stock_comprometido_metros or 0)
        if p.es_material_impresion and p.ancho_rollo and p.ancho_rollo > 0:
            p.stock_metros_m2 = (p.stock_metros or 0) * p.ancho_rollo
            p.comprometido_metros_m2 = (p.stock_comprometido_metros or 0) * p.ancho_rollo
            p.disponible_metros_m2 = (p.disponible_metros or 0) * p.ancho_rollo
        else:
            p.stock_metros_m2 = p.stock_metros or 0
            p.comprometido_metros_m2 = p.stock_comprometido_metros or 0
            p.disponible_metros_m2 = p.disponible_metros or 0

    categorias = Categoria.query.order_by(Categoria.nombre).all()
    categoria_options = get_categoria_options()
    proveedores = Proveedor.query.order_by(Proveedor.nombre).all()

    return render_template('todos_productos.html',
                           productos=productos,
                           categorias=categorias,
                           categoria_options=categoria_options,
                           categoria_seleccionada=categoria_id,
                           search=search,
                           sort=sort,
                           order=order,
                           proveedores=proveedores,
                           page=page,
                           total=total,
                           total_pages=total_pages,
                           per_page=per_page)

# ==========================================
# PRODUCTOS POR CATEGORÍA
# ==========================================
@inventario_bp.route('/categoria/<int:categoria_id>')
@login_required
@economico_or_admin_required
def productos_por_categoria(categoria_id):
    cat = Categoria.query.get_or_404(categoria_id)
    subcategoria_id = request.args.get('subcategoria', type=int)
    search = request.args.get('search', '').strip()
    sort = request.args.get('sort', 'nombre')
    order = request.args.get('order', 'asc')
    page = request.args.get('page', 1, type=int)
    per_page = 20

    cat_ids = get_all_subcategory_ids(categoria_id)
    query = Producto.query.filter(Producto.categoria_id.in_(cat_ids))

    # ===== FIX: si se filtra por subcategoría, incluir sus descendientes =====
    if subcategoria_id:
        sub_ids = get_all_subcategory_ids(subcategoria_id)
        if sub_ids:
            query = query.filter(Producto.categoria_id.in_(sub_ids))

    if search:
        query = query.filter(Producto.nombre.ilike(f'%{search}%'))

    if sort == 'nombre':
        col = Producto.nombre
    elif sort == 'stock':
        col = Producto.stock
    elif sort == 'disponible':
        col = (Producto.stock - Producto.stock_comprometido).label('disponible')
    elif sort == 'comprometido':
        col = Producto.stock_comprometido
    elif sort == 'costo':
        col = Producto.costo
    elif sort == 'categoria':
        col = Producto.categoria_id
    else:
        col = Producto.nombre

    if order == 'desc':
        query = query.order_by(col.desc())
    else:
        query = query.order_by(col.asc())

    paginated = query.paginate(page=page, per_page=per_page, error_out=False)
    productos = paginated.items
    total = paginated.total
    total_pages = paginated.pages

    for p in productos:
        p.disponible = (p.stock or 0) - (p.stock_comprometido or 0)
        p.disponible_metros = (p.stock_metros or 0) - (p.stock_comprometido_metros or 0)
        if p.es_material_impresion and p.ancho_rollo and p.ancho_rollo > 0:
            p.stock_metros_m2 = (p.stock_metros or 0) * p.ancho_rollo
            p.comprometido_metros_m2 = (p.stock_comprometido_metros or 0) * p.ancho_rollo
            p.disponible_metros_m2 = (p.disponible_metros or 0) * p.ancho_rollo
        else:
            p.stock_metros_m2 = p.stock_metros or 0
            p.comprometido_metros_m2 = p.stock_comprometido_metros or 0
            p.disponible_metros_m2 = p.disponible_metros or 0

    # Subcategorías directas (hijas) para el filtro
    subcategorias = Categoria.query.filter_by(parent_id=cat.id).order_by(Categoria.nombre).all()
    categoria_options = get_categoria_options()
    proveedores = Proveedor.query.order_by(Proveedor.nombre).all()

    return render_template('productos_por_categoria.html',
                           categoria=cat,
                           productos=productos,
                           subcategorias=subcategorias,
                           subcategoria_seleccionada=subcategoria_id,
                           search=search,
                           sort=sort,
                           order=order,
                           categoria_options=categoria_options,
                           proveedores=proveedores,
                           page=page,
                           total=total,
                           total_pages=total_pages,
                           per_page=per_page)

# ==========================================
# PANEL DE ADMINISTRACIÓN
# ==========================================
@inventario_bp.route('/admin')
@login_required
@admin_required
def admin_panel():
    areas = Area.query.order_by(Area.nombre).all()
    categorias = Categoria.query.order_by(Categoria.nombre).all()
    ubicaciones = Ubicacion.query.order_by(Ubicacion.nombre).all()
    tipos = TipoProducto.query.order_by(TipoProducto.nombre).all()
    unidades = Unidad.query.order_by(Unidad.nombre).all()
    proveedores = Proveedor.query.order_by(Proveedor.nombre).all()
    grupos = GrupoAtributos.query.order_by(GrupoAtributos.nombre).all()
    return render_template('admin_panel.html',
                           areas=areas,
                           categorias=categorias,
                           ubicaciones=ubicaciones,
                           tipos=tipos,
                           unidades=unidades,
                           proveedores=proveedores,
                           grupos=grupos)

# ==========================================
# CATEGORÍAS
# ==========================================
@inventario_bp.route('/categorias')
@login_required
@admin_required
def listar_categorias():
    categorias = Categoria.query.order_by(Categoria.nombre).all()
    return render_template('categorias.html', categorias=categorias)

@inventario_bp.route('/categoria/crear', methods=['GET', 'POST'])
@login_required
@admin_required
def crear_categoria():
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        parent_id = request.form.get('parent_id', type=int) or None
        es_material_impresion = request.form.get('es_material_impresion') == 'on'
        if not nombre:
            flash('El nombre es obligatorio.', 'danger')
            return render_template('form_categoria.html')
        if Categoria.query.filter_by(nombre=nombre).first():
            flash('Ya existe una categoría con ese nombre.', 'danger')
            return render_template('form_categoria.html')
        cat = Categoria(nombre=nombre, descripcion=descripcion, parent_id=parent_id, es_material_impresion=es_material_impresion)
        db.session.add(cat)
        db.session.commit()
        flash(f'Categoría "{nombre}" creada correctamente.', 'success')
        return redirect(url_for('inventario.listar_categorias'))
    categoria_options = get_categoria_options()
    return render_template('form_categoria.html', categoria_options=categoria_options)

@inventario_bp.route('/categoria/editar/<int:categoria_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_categoria(categoria_id):
    cat = Categoria.query.get_or_404(categoria_id)
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        parent_id = request.form.get('parent_id', type=int) or None
        es_material_impresion = request.form.get('es_material_impresion') == 'on'
        if not nombre:
            flash('El nombre es obligatorio.', 'danger')
            return render_template('form_categoria.html', categoria=cat)
        if parent_id == cat.id:
            flash('No se puede asignar una categoría como su propio padre.', 'danger')
            return render_template('form_categoria.html', categoria=cat)
        existente = Categoria.query.filter(Categoria.nombre == nombre, Categoria.id != cat.id).first()
        if existente:
            flash('Ya existe otra categoría con ese nombre.', 'danger')
            return render_template('form_categoria.html', categoria=cat)
        cat.nombre = nombre
        cat.descripcion = descripcion
        cat.parent_id = parent_id
        cat.es_material_impresion = es_material_impresion
        db.session.commit()
        flash('Categoría actualizada.', 'success')
        return redirect(url_for('inventario.listar_categorias'))
    categoria_options = get_categoria_options()
    return render_template('form_categoria.html', categoria=cat, categoria_options=categoria_options)

@inventario_bp.route('/categoria/eliminar/<int:categoria_id>', methods=['POST'])
@login_required
@admin_required
def eliminar_categoria(categoria_id):
    cat = Categoria.query.get_or_404(categoria_id)
    if Producto.query.filter_by(categoria_id=cat.id).first():
        flash('No se puede eliminar una categoría con productos asociados.', 'danger')
        return redirect(url_for('inventario.listar_categorias'))
    children = Categoria.query.filter_by(parent_id=cat.id).all()
    for child in children:
        child.parent_id = cat.parent_id
    db.session.delete(cat)
    db.session.commit()
    flash('Categoría eliminada.', 'success')
    return redirect(url_for('inventario.listar_categorias'))

# ==========================================
# ÁREAS (LEGACY)
# ==========================================
@inventario_bp.route('/areas')
@login_required
@admin_required
def gestion_areas():
    flash('Las áreas están obsoletas. Usa Categorías en su lugar.', 'info')
    return redirect(url_for('inventario.admin_panel'))

@inventario_bp.route('/area/crear', methods=['GET', 'POST'])
@login_required
@admin_required
def crear_area():
    flash('Las áreas están obsoletas. Usa Categorías en su lugar.', 'info')
    return redirect(url_for('inventario.crear_categoria'))

@inventario_bp.route('/area/editar/<int:area_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_area(area_id):
    flash('Las áreas están obsoletas. Usa Categorías en su lugar.', 'info')
    return redirect(url_for('inventario.admin_panel'))

@inventario_bp.route('/area/eliminar/<int:area_id>', methods=['POST'])
@login_required
@admin_required
def eliminar_area(area_id):
    flash('Las áreas están obsoletas. Usa Categorías en su lugar.', 'info')
    return redirect(url_for('inventario.admin_panel'))

# ==========================================
# UBICACIONES
# ==========================================
@inventario_bp.route('/ubicaciones')
@login_required
@admin_required
def listar_ubicaciones():
    ubicaciones = Ubicacion.query.order_by(Ubicacion.nombre).all()
    return render_template('ubicaciones.html', ubicaciones=ubicaciones)

@inventario_bp.route('/ubicacion/crear', methods=['GET', 'POST'])
@login_required
@admin_required
def crear_ubicacion():
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        if not nombre:
            flash('El nombre es obligatorio.', 'danger')
            return render_template('form_ubicacion.html')
        if Ubicacion.query.filter_by(nombre=nombre).first():
            flash('Ya existe una ubicación con ese nombre.', 'danger')
            return render_template('form_ubicacion.html')
        ubi = Ubicacion(nombre=nombre, descripcion=descripcion)
        db.session.add(ubi)
        db.session.commit()
        flash(f'Ubicación "{nombre}" creada correctamente.', 'success')
        return redirect(url_for('inventario.listar_ubicaciones'))
    return render_template('form_ubicacion.html')

@inventario_bp.route('/ubicacion/editar/<int:ubicacion_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_ubicacion(ubicacion_id):
    ubi = Ubicacion.query.get_or_404(ubicacion_id)
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        if not nombre:
            flash('El nombre es obligatorio.', 'danger')
            return render_template('form_ubicacion.html', ubicacion=ubi)
        existente = Ubicacion.query.filter(Ubicacion.nombre == nombre, Ubicacion.id != ubi.id).first()
        if existente:
            flash('Ya existe otra ubicación con ese nombre.', 'danger')
            return render_template('form_ubicacion.html', ubicacion=ubi)
        ubi.nombre = nombre
        ubi.descripcion = descripcion
        db.session.commit()
        flash('Ubicación actualizada.', 'success')
        return redirect(url_for('inventario.listar_ubicaciones'))
    return render_template('form_ubicacion.html', ubicacion=ubi)

@inventario_bp.route('/ubicacion/eliminar/<int:ubicacion_id>', methods=['POST'])
@login_required
@admin_required
def eliminar_ubicacion(ubicacion_id):
    ubi = Ubicacion.query.get_or_404(ubicacion_id)
    if Producto.query.filter_by(ubicacion_id=ubi.id).first():
        flash('No se puede eliminar una ubicación con productos asociados.', 'danger')
        return redirect(url_for('inventario.listar_ubicaciones'))
    db.session.delete(ubi)
    db.session.commit()
    flash('Ubicación eliminada.', 'success')
    return redirect(url_for('inventario.listar_ubicaciones'))

# ==========================================
# TIPOS (LEGACY)
# ==========================================
@inventario_bp.route('/tipos')
@login_required
@admin_required
def listar_tipos():
    tipos = TipoProducto.query.order_by(TipoProducto.nombre).all()
    return render_template('tipos.html', tipos=tipos)

@inventario_bp.route('/tipo/crear', methods=['GET', 'POST'])
@login_required
@admin_required
def crear_tipo():
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        if not nombre:
            flash('El nombre es obligatorio.', 'danger')
            return render_template('form_tipo.html')
        if TipoProducto.query.filter_by(nombre=nombre).first():
            flash('Ya existe un tipo con ese nombre.', 'danger')
            return render_template('form_tipo.html')
        tipo = TipoProducto(nombre=nombre, descripcion=descripcion)
        db.session.add(tipo)
        db.session.commit()
        flash(f'Tipo "{nombre}" creado correctamente.', 'success')
        return redirect(url_for('inventario.listar_tipos'))
    return render_template('form_tipo.html')

@inventario_bp.route('/tipo/editar/<int:tipo_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_tipo(tipo_id):
    tipo = TipoProducto.query.get_or_404(tipo_id)
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        if not nombre:
            flash('El nombre es obligatorio.', 'danger')
            return render_template('form_tipo.html', tipo=tipo)
        existente = TipoProducto.query.filter(TipoProducto.nombre == nombre, TipoProducto.id != tipo.id).first()
        if existente:
            flash('Ya existe otro tipo con ese nombre.', 'danger')
            return render_template('form_tipo.html', tipo=tipo)
        tipo.nombre = nombre
        tipo.descripcion = descripcion
        db.session.commit()
        flash('Tipo actualizado.', 'success')
        return redirect(url_for('inventario.listar_tipos'))
    return render_template('form_tipo.html', tipo=tipo)

@inventario_bp.route('/tipo/eliminar/<int:tipo_id>', methods=['POST'])
@login_required
@admin_required
def eliminar_tipo(tipo_id):
    tipo = TipoProducto.query.get_or_404(tipo_id)
    if Producto.query.filter_by(tipo_producto_id=tipo.id).first():
        flash('No se puede eliminar un tipo con productos asociados.', 'danger')
        return redirect(url_for('inventario.listar_tipos'))
    db.session.delete(tipo)
    db.session.commit()
    flash('Tipo eliminado.', 'success')
    return redirect(url_for('inventario.listar_tipos'))

# ==========================================
# UNIDADES
# ==========================================
@inventario_bp.route('/unidades')
@login_required
@admin_required
def listar_unidades():
    unidades = Unidad.query.order_by(Unidad.nombre).all()
    return render_template('unidades.html', unidades=unidades)

@inventario_bp.route('/unidad/crear', methods=['GET', 'POST'])
@login_required
@admin_required
def crear_unidad():
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        simbolo = request.form.get('simbolo', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        if not nombre:
            flash('El nombre es obligatorio.', 'danger')
            return render_template('form_unidad.html')
        if Unidad.query.filter_by(nombre=nombre).first():
            flash('Ya existe una unidad con ese nombre.', 'danger')
            return render_template('form_unidad.html')
        uni = Unidad(nombre=nombre, simbolo=simbolo, descripcion=descripcion)
        db.session.add(uni)
        db.session.commit()
        flash(f'Unidad "{nombre}" creada correctamente.', 'success')
        return redirect(url_for('inventario.listar_unidades'))
    return render_template('form_unidad.html')

@inventario_bp.route('/unidad/editar/<int:unidad_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_unidad(unidad_id):
    uni = Unidad.query.get_or_404(unidad_id)
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        simbolo = request.form.get('simbolo', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        if not nombre:
            flash('El nombre es obligatorio.', 'danger')
            return render_template('form_unidad.html', unidad=uni)
        existente = Unidad.query.filter(Unidad.nombre == nombre, Unidad.id != uni.id).first()
        if existente:
            flash('Ya existe otra unidad con ese nombre.', 'danger')
            return render_template('form_unidad.html', unidad=uni)
        uni.nombre = nombre
        uni.simbolo = simbolo
        uni.descripcion = descripcion
        db.session.commit()
        flash('Unidad actualizada.', 'success')
        return redirect(url_for('inventario.listar_unidades'))
    return render_template('form_unidad.html', unidad=uni)

@inventario_bp.route('/unidad/eliminar/<int:unidad_id>', methods=['POST'])
@login_required
@admin_required
def eliminar_unidad(unidad_id):
    uni = Unidad.query.get_or_404(unidad_id)
    if Producto.query.filter_by(unidad_id=uni.id).first():
        flash('No se puede eliminar una unidad con productos asociados.', 'danger')
        return redirect(url_for('inventario.listar_unidades'))
    db.session.delete(uni)
    db.session.commit()
    flash('Unidad eliminada.', 'success')
    return redirect(url_for('inventario.listar_unidades'))

# ==========================================
# ACCIONES ADMIN
# ==========================================
@inventario_bp.route('/producto/<int:producto_id>/borrar-historial', methods=['POST'])
@login_required
@admin_required
def borrar_historial(producto_id):
    producto = Producto.query.get_or_404(producto_id)
    Movimiento.query.filter_by(producto_id=producto.id).delete()
    producto.stock_comprometido = 0
    producto.stock_comprometido_metros = 0
    db.session.commit()
    flash(f'Historial de "{producto.nombre}" eliminado.', 'success')
    return redirect(url_for('inventario.detalle_producto', producto_id=producto.id))

@inventario_bp.route('/producto/<int:producto_id>/resetear-comprometido', methods=['POST'])
@login_required
@admin_required
def resetear_comprometido(producto_id):
    producto = Producto.query.get_or_404(producto_id)
    producto.stock_comprometido = 0
    producto.stock_comprometido_metros = 0
    db.session.commit()
    flash(f'Stock comprometido de "{producto.nombre}" reseteado a 0.', 'success')
    return redirect(url_for('inventario.detalle_producto', producto_id=producto.id))

@inventario_bp.route('/area/<int:area_id>/resetear-comprometido', methods=['POST'])
@login_required
@admin_required
def resetear_comprometido_area(area_id):
    area = Area.query.get_or_404(area_id)
    productos = Producto.query.filter_by(area_id=area.id).all()
    for p in productos:
        p.stock_comprometido = 0
        p.stock_comprometido_metros = 0
    db.session.commit()
    flash(f'Stock comprometido reseteado.', 'success')
    return redirect(url_for('inventario.index'))

# ==========================================
# CREAR PRODUCTO
# ==========================================
@inventario_bp.route('/crear', methods=['GET', 'POST'])
@login_required
@economico_or_admin_required
def crear_producto():
    categorias = Categoria.query.order_by(Categoria.nombre).all()
    areas = Area.query.order_by(Area.nombre).all()
    ubicaciones = Ubicacion.query.order_by(Ubicacion.nombre).all()
    tipos = TipoProducto.query.order_by(TipoProducto.nombre).all()
    unidades = Unidad.query.order_by(Unidad.nombre).all()
    categoria_options = get_categoria_options()

    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        costo = request.form.get('costo', type=float, default=0.0)
        stock = request.form.get('stock', type=float, default=0.0)
        stock_metros = request.form.get('stock_metros', type=float, default=0.0)
        stock_minimo = request.form.get('stock_minimo', type=float, default=0.0)
        categoria_id = request.form.get('categoria_id', type=int)
        area_id = request.form.get('area_id', type=int)
        ubicacion_id = request.form.get('ubicacion_id', type=int)
        tipo_producto_id = request.form.get('tipo_producto_id', type=int)
        unidad_id = request.form.get('unidad_id', type=int)
        ancho_rollo = request.form.get('ancho_rollo', type=float)
        ancho_util = request.form.get('ancho_util', type=float)
        gap_panno_cm = request.form.get('gap_panno_cm', type=float, default=6.5)
        merma_porcentaje = request.form.get('merma_porcentaje', type=float, default=0.0)
        largo_rollo = request.form.get('largo_rollo', type=float)
        fecha_vencimiento = request.form.get('fecha_vencimiento', '')
        es_material_impresion = request.form.get('es_material_impresion') == 'on'

        atributos_extra = {}
        if categoria_id:
            # ===== FIX: hereda del ancestro si la categoría no tiene grupo propio =====
            grupo = get_grupo_atributos_para_categoria(categoria_id)
            if grupo:
                for attr in grupo.atributos.all():
                    val = request.form.get(f'attr_{attr.nombre}', '').strip()
                    if val:
                        if attr.tipo == 'numero':
                            try:
                                val = float(val)
                            except:
                                val = 0
                        elif attr.tipo == 'booleano':
                            val = val == '1' or val == 'on' or val == 'true'
                        atributos_extra[attr.nombre] = val

        if not nombre or not categoria_id:
            flash('Nombre y categoría son obligatorios.', 'danger')
            return render_template('form_producto.html', categorias=categorias, areas=areas,
                                   ubicaciones=ubicaciones, tipos=tipos, unidades=unidades,
                                   categoria_options=categoria_options)

        if Producto.query.filter_by(nombre=nombre).first():
            flash('Ya existe un producto con ese nombre.', 'danger')
            return render_template('form_producto.html', categorias=categorias, areas=areas,
                                   ubicaciones=ubicaciones, tipos=tipos, unidades=unidades,
                                   categoria_options=categoria_options)

        if largo_rollo and largo_rollo > 0 and stock > 0 and not stock_metros:
            stock_metros = stock * largo_rollo

        producto = Producto(
            nombre=nombre,
            descripcion=descripcion,
            costo=costo,
            stock=stock,
            stock_metros=stock_metros,
            stock_minimo=stock_minimo,
            categoria_id=categoria_id,
            area_id=area_id if area_id else None,
            ubicacion_id=ubicacion_id if ubicacion_id else None,
            tipo_producto_id=tipo_producto_id if tipo_producto_id else None,
            unidad_id=unidad_id if unidad_id else None,
            ancho_rollo=ancho_rollo,
            ancho_util=ancho_util,
            gap_panno_cm=gap_panno_cm if gap_panno_cm is not None else 6.5,
            merma_porcentaje=merma_porcentaje,
            largo_rollo=largo_rollo,
            inversion_total=0.0,
            es_material_impresion=es_material_impresion,
            atributos_extra=atributos_extra if atributos_extra else None
        )
        if fecha_vencimiento:
            try:
                producto.fecha_vencimiento = datetime.strptime(fecha_vencimiento, '%Y-%m-%d').date()
            except:
                pass

        db.session.add(producto)
        db.session.commit()

        if stock > 0:
            movimiento = Movimiento(
                producto_id=producto.id,
                tipo='entrada',
                cantidad=stock,
                cantidad_metros=stock_metros,
                comentario='Stock inicial',
                usuario_id=current_user.id
            )
            db.session.add(movimiento)
            db.session.commit()

        verificar_y_notificar_stock_bajo(producto)

        flash(f'Producto "{nombre}" creado correctamente.', 'success')
        return redirect(url_for('inventario.productos_por_categoria', categoria_id=producto.categoria_id))

    return render_template('form_producto.html', producto=None, categorias=categorias, areas=areas,
                           ubicaciones=ubicaciones, tipos=tipos, unidades=unidades,
                           categoria_options=categoria_options)

# ==========================================
# EDITAR PRODUCTO
# ==========================================
@inventario_bp.route('/editar/<int:producto_id>', methods=['GET', 'POST'])
@login_required
@economico_or_admin_required
def editar_producto(producto_id):
    producto = Producto.query.get_or_404(producto_id)
    categorias = Categoria.query.order_by(Categoria.nombre).all()
    areas = Area.query.order_by(Area.nombre).all()
    ubicaciones = Ubicacion.query.order_by(Ubicacion.nombre).all()
    tipos = TipoProducto.query.order_by(TipoProducto.nombre).all()
    unidades = Unidad.query.order_by(Unidad.nombre).all()
    categoria_options = get_categoria_options()

    if request.method == 'POST':
        producto.nombre = request.form.get('nombre', '').strip()
        producto.descripcion = request.form.get('descripcion', '').strip()
        producto.costo = request.form.get('costo', type=float, default=0.0)
        producto.stock_minimo = request.form.get('stock_minimo', type=float, default=0.0)
        producto.categoria_id = request.form.get('categoria_id', type=int) or None
        producto.area_id = request.form.get('area_id', type=int) or None
        producto.ubicacion_id = request.form.get('ubicacion_id', type=int) or None
        producto.tipo_producto_id = request.form.get('tipo_producto_id', type=int) or None
        producto.unidad_id = request.form.get('unidad_id', type=int) or None
        producto.ancho_rollo = request.form.get('ancho_rollo', type=float)
        producto.largo_rollo = request.form.get('largo_rollo', type=float)
        producto.ancho_util = request.form.get('ancho_util', type=float)
        gap_panno_cm = request.form.get('gap_panno_cm', type=float)
        producto.gap_panno_cm = gap_panno_cm if gap_panno_cm is not None else 6.5
        producto.merma_porcentaje = request.form.get('merma_porcentaje', type=float, default=0.0)
        producto.es_material_impresion = request.form.get('es_material_impresion') == 'on'
        fecha_vencimiento = request.form.get('fecha_vencimiento', '')
        stock_metros = request.form.get('stock_metros', type=float)
        if stock_metros is not None:
            producto.stock_metros = stock_metros

        atributos_extra = {}
        if producto.categoria_id:
            # ===== FIX: hereda del ancestro si la categoría no tiene grupo propio =====
            grupo = get_grupo_atributos_para_categoria(producto.categoria_id)
            if grupo:
                for attr in grupo.atributos.all():
                    val = request.form.get(f'attr_{attr.nombre}', '').strip()
                    if val:
                        if attr.tipo == 'numero':
                            try:
                                val = float(val)
                            except:
                                val = 0
                        elif attr.tipo == 'booleano':
                            val = val == '1' or val == 'on' or val == 'true'
                        atributos_extra[attr.nombre] = val

        producto.atributos_extra = atributos_extra if atributos_extra else None

        if fecha_vencimiento:
            try:
                producto.fecha_vencimiento = datetime.strptime(fecha_vencimiento, '%Y-%m-%d').date()
            except:
                producto.fecha_vencimiento = None
        else:
            producto.fecha_vencimiento = None

        db.session.commit()
        verificar_y_notificar_stock_bajo(producto)
        flash(f'Producto "{producto.nombre}" actualizado.', 'success')
        return redirect(url_for('inventario.detalle_producto', producto_id=producto.id))

    return render_template('form_producto.html', producto=producto, categorias=categorias, areas=areas,
                           ubicaciones=ubicaciones, tipos=tipos, unidades=unidades,
                           categoria_options=categoria_options)

# ==========================================
# ELIMINAR / DUPLICAR PRODUCTO
# ==========================================
@inventario_bp.route('/eliminar/<int:producto_id>', methods=['POST'])
@login_required
@economico_or_admin_required
def eliminar_producto(producto_id):
    producto = Producto.query.get_or_404(producto_id)
    if Movimiento.query.filter_by(producto_id=producto.id).first():
        flash('No se puede eliminar un producto con movimientos.', 'danger')
        return redirect(url_for('inventario.productos_por_categoria', categoria_id=producto.categoria_id or 0))
    if OrdenProducto.query.filter_by(producto_id=producto.id).first():
        flash('No se puede eliminar un producto asociado a órdenes.', 'danger')
        return redirect(url_for('inventario.productos_por_categoria', categoria_id=producto.categoria_id or 0))
    nombre = producto.nombre
    db.session.delete(producto)
    db.session.commit()
    flash(f'Producto "{nombre}" eliminado.', 'success')
    return redirect(url_for('inventario.index'))

@inventario_bp.route('/duplicar/<int:producto_id>')
@login_required
@economico_or_admin_required
def duplicar_producto(producto_id):
    original = Producto.query.get_or_404(producto_id)
    nueva = Producto(
        nombre=f"Copia de {original.nombre}",
        descripcion=original.descripcion,
        costo=original.costo,
        stock=0,
        stock_metros=0,
        stock_minimo=original.stock_minimo,
        categoria_id=original.categoria_id,
        area_id=original.area_id,
        ubicacion_id=original.ubicacion_id,
        tipo_producto_id=original.tipo_producto_id,
        unidad_id=original.unidad_id,
        ancho_rollo=original.ancho_rollo,
        largo_rollo=original.largo_rollo,
        gap_panno_cm=original.gap_panno_cm,
        merma_porcentaje=original.merma_porcentaje,
        fecha_vencimiento=original.fecha_vencimiento,
        inversion_total=0.0,
        es_material_impresion=original.es_material_impresion,
        atributos_extra=original.atributos_extra
    )
    db.session.add(nueva)
    db.session.commit()
    flash(f'Producto "{original.nombre}" duplicado correctamente.', 'success')
    return redirect(url_for('inventario.editar_producto', producto_id=nueva.id))

# ==========================================
# DETALLE DE PRODUCTO
# ==========================================
@inventario_bp.route('/producto/<int:producto_id>')
@login_required
@economico_or_admin_required
def detalle_producto(producto_id):
    producto = Producto.query.get_or_404(producto_id)
    producto.disponible = producto.get_stock_unidades_disponible()
    producto.disponible_metros = producto.get_stock_metros_disponible()
    if producto.es_material_impresion and producto.ancho_rollo and producto.ancho_rollo > 0:
        producto.stock_m2 = (producto.stock_metros or 0) * producto.ancho_rollo
        producto.disponible_m2 = (producto.disponible_metros or 0) * producto.ancho_rollo
    else:
        producto.stock_m2 = producto.stock_metros or 0
        producto.disponible_m2 = producto.disponible_metros or 0

    movimientos = Movimiento.query.filter_by(producto_id=producto_id).order_by(Movimiento.fecha.asc()).all()
    saldo = 0
    saldo_metros = 0
    fechas = []
    saldos = []
    saldos_metros = []
    # Tipos que suman stock
    TIPOS_SUMAN = ['entrada', 'entrada_ajuste', 'sobrante', 'correccion_alta']
    # Tipos que restan stock
    TIPOS_RESTAN = ['consumo', 'merma', 'reserva', 'correccion_baja']
    for m in movimientos:
        if m.tipo in TIPOS_SUMAN:
            saldo += m.cantidad
            saldo_metros += m.cantidad_metros or m.cantidad
        elif m.tipo in TIPOS_RESTAN:
            saldo -= m.cantidad
            saldo_metros -= m.cantidad_metros or m.cantidad
        fechas.append(m.fecha.strftime('%Y-%m-%d %H:%M'))
        saldos.append(round(saldo, 2))
        saldos_metros.append(round(saldo_metros, 2))
    if not fechas:
        fechas.append(datetime.now().strftime('%Y-%m-%d'))
        saldos.append(round(producto.stock, 2))
        saldos_metros.append(round(producto.stock_metros, 2))
    if len(fechas) > 50:
        fechas = fechas[-50:]
        saldos = saldos[-50:]
        saldos_metros = saldos_metros[-50:]

    movimientos_recientes = Movimiento.query.filter_by(producto_id=producto_id).order_by(Movimiento.fecha.desc()).limit(50).all()
    proveedores = Proveedor.query.order_by(Proveedor.nombre).all()

    merma_estimada = calcular_merma_estimada_producto(producto_id)

    return render_template('detalle_producto.html',
                           producto=producto,
                           movimientos=movimientos_recientes,
                           proveedores=proveedores,
                           merma_estimada=merma_estimada,
                           fechas_json=json.dumps(fechas),
                           saldos_json=json.dumps(saldos),
                           saldos_metros_json=json.dumps(saldos_metros))

# ==========================================
# COMPRAR
# ==========================================
@inventario_bp.route('/comprar', methods=['POST'])
@login_required
@economico_or_admin_required
def comprar():
    producto_id = request.form.get('producto_id', type=int)
    cantidad = request.form.get('cantidad', type=float)
    cantidad_metros = request.form.get('cantidad_metros', type=float)
    costo_unitario = request.form.get('costo', type=float, default=0.0)
    comentario = request.form.get('comentario', '').strip()
    proveedor_id = request.form.get('proveedor_id', type=int)

    if not producto_id or not cantidad or cantidad <= 0:
        flash('Datos inválidos.', 'danger')
        return redirect(url_for('inventario.index'))

    producto = Producto.query.get(producto_id)
    if not producto:
        flash('Producto no encontrado.', 'danger')
        return redirect(url_for('inventario.index'))

    producto.stock += cantidad
    if producto.largo_rollo and producto.largo_rollo > 0:
        metros_agregados = cantidad * producto.largo_rollo
        producto.stock_metros += metros_agregados
    else:
        metros_agregados = cantidad_metros if cantidad_metros else cantidad
        producto.stock_metros += metros_agregados

    if costo_unitario > 0:
        producto.costo = costo_unitario
    else:
        costo_unitario = producto.costo

    costo_total = cantidad * costo_unitario
    producto.inversion_total += costo_total

    movimiento = Movimiento(
        producto_id=producto.id,
        tipo='entrada',
        cantidad=cantidad,
        cantidad_metros=metros_agregados,
        costo_unitario=costo_unitario,
        costo_total=costo_total,
        comentario=comentario or 'Compra',
        usuario_id=current_user.id,
        proveedor_id=proveedor_id if proveedor_id else None
    )
    db.session.add(movimiento)
    db.session.commit()

    verificar_y_notificar_stock_bajo(producto)
    flash(f'Compra registrada.', 'success')
    return redirect(url_for('inventario.detalle_producto', producto_id=producto.id))

# ==========================================
# AJUSTAR (solo correcciones de captura)
# ==========================================
# NOTA: Esta ruta es SOLO para corregir errores de captura.
# NO afecta la merma real. Los conteos físicos se hacen en
# /inventario/conteos-semanales/nuevo (nuevo_conteo).
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
        flash('El stock ya coincide con el valor ingresado.', 'info')
        return redirect(url_for('inventario.detalle_producto', producto_id=producto.id))

    # SIEMPRE corrección de error (nunca merma/sobrante)
    tipo = 'correccion_baja' if diferencia > 0 else 'correccion_alta'
    cantidad = abs(diferencia)

    producto.stock = stock_real
    producto.stock_metros = stock_real * (producto.largo_rollo or 1)

    movimiento = Movimiento(
        producto_id=producto.id,
        tipo=tipo,
        cantidad=cantidad,
        cantidad_metros=cantidad * (producto.largo_rollo or 1),
        comentario=comentario or f'Corrección de captura ({tipo.replace("correccion_", "")})',
        usuario_id=current_user.id,
        tipo_ajuste='correccion'
    )
    db.session.add(movimiento)
    db.session.commit()

    verificar_y_notificar_stock_bajo(producto)
    flash('Corrección registrada. Para conteos físicos usa "Conteos semanales".', 'success')
    return redirect(url_for('inventario.detalle_producto', producto_id=producto.id))

# ==========================================
# REPORTE DE MERMA
# ==========================================
@inventario_bp.route('/merma')
@login_required
@economico_or_admin_required
def merma():
    periodo = request.args.get('periodo', 'month')
    fecha_inicio_str = request.args.get('fecha_inicio')
    fecha_fin_str = request.args.get('fecha_fin')
    agrupar_por = request.args.get('agrupar_por', 'producto')
    tipo_merma = request.args.get('tipo_merma', 'real')

    hoy = datetime.now()
    if fecha_inicio_str and fecha_fin_str:
        try:
            fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d')
            fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d') + timedelta(days=1) - timedelta(seconds=1)
        except:
            fecha_inicio = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            fecha_fin = hoy
    else:
        if periodo == 'day':
            fecha_inicio = hoy.replace(hour=0, minute=0, second=0, microsecond=0)
            fecha_fin = hoy
        elif periodo == 'week':
            inicio_semana = hoy - timedelta(days=hoy.weekday())
            fecha_inicio = inicio_semana.replace(hour=0, minute=0, second=0, microsecond=0)
            fecha_fin = hoy
        elif periodo == 'month':
            fecha_inicio = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            fecha_fin = hoy
        else:
            fecha_inicio = hoy.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            fecha_fin = hoy

    datos_lista = []
    labels = []
    merma_values = []
    pie_labels = []
    pie_values = []

    if tipo_merma == 'estimada':
        archivos = ArchivoAdjunto.query.filter(
            ArchivoAdjunto.parametros_etiqueta.isnot(None)
        ).join(Order, ArchivoAdjunto.orden_id == Order.id).filter(
            Order.date >= fecha_inicio.date(),
            Order.date <= fecha_fin.date()
        ).all()

        def _get_params_merma(params):
            area = float(params.get('area_m2', 0) or 0)
            material = float(params.get('material_consumido_m2', 0) or 0)
            m_op = float(params.get('merma_operativa_m2', params.get('merma_estimada_m2', 0)) or 0)
            return area, material, m_op

        if agrupar_por == 'categoria':
            grupos = {}
            for a in archivos:
                try:
                    params = json.loads(a.parametros_etiqueta) if a.parametros_etiqueta else {}
                except:
                    continue
                if 'merma_operativa_m2' not in params and 'merma_estimada_m2' not in params:
                    continue
                prod = a.producto
                cat = prod.categoria.nombre if prod and prod.categoria else 'Sin categoría'
                if cat not in grupos:
                    grupos[cat] = {'area_m2': 0, 'material_m2': 0, 'merma_m2': 0, 'lineas': 0}
                area, material, m_op = _get_params_merma(params)
                grupos[cat]['area_m2'] += area
                grupos[cat]['material_m2'] += material
                grupos[cat]['merma_m2'] += m_op
                grupos[cat]['lineas'] += 1
            for cat, vals in grupos.items():
                pct = (vals['merma_m2'] / vals['area_m2'] * 100) if vals['area_m2'] > 0 else 0
                datos_lista.append({
                    'nombre': cat, 'categoria': '—',
                    'area_facturada_m2': round(vals['area_m2'], 2),
                    'material_consumido_m2': round(vals['material_m2'], 2),
                    'merma_operativa_m2': round(vals['merma_m2'], 2),
                    'merma_operativa_pct': round(pct, 2),
                    'lineas': vals['lineas'],
                })
            datos_lista.sort(key=lambda x: x['merma_operativa_m2'], reverse=True)

        elif agrupar_por == 'linea':
            for a in archivos:
                try:
                    params = json.loads(a.parametros_etiqueta) if a.parametros_etiqueta else {}
                except:
                    continue
                if 'merma_operativa_m2' not in params and 'merma_estimada_m2' not in params:
                    continue
                prod = a.producto
                cat = prod.categoria.nombre if prod and prod.categoria else 'Sin categoría'
                orden_num = a.orden.order_num if a.orden else '—'
                cliente = a.orden.client.nombre if a.orden and a.orden.client else '—'
                area, material, m_op = _get_params_merma(params)
                pct = (m_op / area * 100) if area > 0 else 0
                datos_lista.append({
                    'nombre': a.nombre_visible or '—',
                    'categoria': cat,
                    'orden_num': orden_num,
                    'cliente': cliente,
                    'area_facturada_m2': round(area, 2),
                    'material_consumido_m2': round(material, 2),
                    'merma_operativa_m2': round(m_op, 2),
                    'merma_operativa_pct': round(pct, 2),
                    'lineas': 1,
                })
            datos_lista.sort(key=lambda x: x['merma_operativa_m2'], reverse=True)

        else:  # producto
            grupos = {}
            for a in archivos:
                try:
                    params = json.loads(a.parametros_etiqueta) if a.parametros_etiqueta else {}
                except:
                    continue
                if 'merma_operativa_m2' not in params and 'merma_estimada_m2' not in params:
                    continue
                prod = a.producto
                nombre = prod.nombre if prod else 'Sin producto'
                cat = prod.categoria.nombre if prod and prod.categoria else 'Sin categoría'
                key = prod.id if prod else 0
                if key not in grupos:
                    grupos[key] = {'nombre': nombre, 'categoria': cat, 'area_m2': 0, 'material_m2': 0, 'merma_m2': 0, 'lineas': 0}
                area, material, m_op = _get_params_merma(params)
                grupos[key]['area_m2'] += area
                grupos[key]['material_m2'] += material
                grupos[key]['merma_m2'] += m_op
                grupos[key]['lineas'] += 1
            for key, vals in grupos.items():
                pct = (vals['merma_m2'] / vals['area_m2'] * 100) if vals['area_m2'] > 0 else 0
                datos_lista.append({
                    'nombre': vals['nombre'],
                    'categoria': vals['categoria'],
                    'area_facturada_m2': round(vals['area_m2'], 2),
                    'material_consumido_m2': round(vals['material_m2'], 2),
                    'merma_operativa_m2': round(vals['merma_m2'], 2),
                    'merma_operativa_pct': round(pct, 2),
                    'lineas': vals['lineas'],
                })
            datos_lista.sort(key=lambda x: x['merma_operativa_m2'], reverse=True)

        labels = [d['nombre'][:25] for d in datos_lista[:10]]
        merma_values = [d['merma_operativa_m2'] for d in datos_lista[:10]]
        pie_labels = labels
        pie_values = merma_values

    else:
        movimientos = Movimiento.query.filter(
            Movimiento.fecha >= fecha_inicio,
            Movimiento.fecha <= fecha_fin,
            Movimiento.tipo.notin_(['correccion_baja', 'correccion_alta'])
        ).all()

        if agrupar_por == 'categoria':
            datos = {}
            for m in movimientos:
                producto = m.producto
                if not producto:
                    continue
                cat = producto.categoria
                cat_nombre = cat.nombre if cat else 'Sin categoría'
                if cat_nombre not in datos:
                    datos[cat_nombre] = {'entradas': 0, 'consumos': 0, 'merma': 0}
                if m.tipo == 'entrada':
                    datos[cat_nombre]['entradas'] += m.cantidad
                elif m.tipo == 'consumo':
                    datos[cat_nombre]['consumos'] += m.cantidad
                elif m.tipo == 'merma':
                    datos[cat_nombre]['merma'] += m.cantidad
                elif m.tipo == 'sobrante':
                    datos[cat_nombre]['merma'] -= m.cantidad
            for cat, vals in datos.items():
                merma_val = vals['merma']
                pct = (merma_val / (vals['entradas'] + vals['consumos']) * 100) if (vals['entradas'] + vals['consumos']) > 0 else 0
                datos_lista.append({
                    'nombre': cat, 'categoria': '—',
                    'entradas': round(vals['entradas'], 2),
                    'consumos': round(vals['consumos'], 2),
                    'merma': round(merma_val, 2),
                    'porcentaje': round(pct, 2),
                })
            datos_lista.sort(key=lambda x: abs(x['merma']), reverse=True)

        else:
            datos = {}
            for m in movimientos:
                producto = m.producto
                if not producto:
                    continue
                key = producto.id
                if key not in datos:
                    datos[key] = {
                        'nombre': producto.nombre,
                        'categoria': producto.categoria.nombre if producto.categoria else 'Sin categoría',
                        'entradas': 0, 'consumos': 0, 'merma': 0
                    }
                if m.tipo == 'entrada':
                    datos[key]['entradas'] += m.cantidad
                elif m.tipo == 'consumo':
                    datos[key]['consumos'] += m.cantidad
                elif m.tipo == 'merma':
                    datos[key]['merma'] += m.cantidad
                elif m.tipo == 'sobrante':
                    datos[key]['merma'] -= m.cantidad
            for key, vals in datos.items():
                merma_val = vals['merma']
                pct = (merma_val / (vals['entradas'] + vals['consumos']) * 100) if (vals['entradas'] + vals['consumos']) > 0 else 0
                datos_lista.append({
                    'nombre': vals['nombre'],
                    'categoria': vals['categoria'],
                    'entradas': round(vals['entradas'], 2),
                    'consumos': round(vals['consumos'], 2),
                    'merma': round(merma_val, 2),
                    'porcentaje': round(pct, 2),
                })
            datos_lista.sort(key=lambda x: abs(x['merma']), reverse=True)

        labels = [d['nombre'][:20] for d in datos_lista[:10]]
        merma_values = [round(d['merma'], 2) for d in datos_lista[:10]]
        pie_labels = labels
        pie_values = merma_values

    return render_template('merma.html',
                           datos=datos_lista,
                           periodo=periodo,
                           fecha_inicio=fecha_inicio.strftime('%Y-%m-%d'),
                           fecha_fin=fecha_fin.strftime('%Y-%m-%d'),
                           agrupar_por=agrupar_por,
                           tipo_merma=tipo_merma,
                           labels=json.dumps(labels),
                           merma_values=json.dumps(merma_values),
                           pie_labels=json.dumps(pie_labels),
                           pie_values=json.dumps(pie_values))

# ==========================================
# MOVIMIENTOS
# ==========================================
@inventario_bp.route('/movimientos-json/<int:producto_id>')
@login_required
@economico_or_admin_required
def movimientos_json(producto_id):
    producto = Producto.query.get_or_404(producto_id)
    movs = Movimiento.query.filter_by(producto_id=producto_id).order_by(Movimiento.fecha.desc()).limit(30).all()
    data = [{
        'id': m.id,
        'tipo': m.tipo,
        'cantidad': round(m.cantidad, 2),
        'cantidad_metros': round(m.cantidad_metros, 2) if m.cantidad_metros else None,
        'costo_unitario': round(m.costo_unitario, 2) if m.costo_unitario else None,
        'costo_total': round(m.costo_total, 2) if m.costo_total else None,
        'fecha': m.fecha.strftime('%d/%m/%Y %H:%M'),
        'comentario': m.comentario,
        'orden': m.orden.order_num if m.orden else None
    } for m in movs]
    return jsonify(data)

@inventario_bp.route('/movimientos', methods=['GET'])
@login_required
@economico_or_admin_required
def movimientos():
    producto_id = request.args.get('producto_id', type=int)
    categoria_id = request.args.get('categoria_id', type=int)
    tipo = request.args.get('tipo', '').strip()
    fecha_inicio_str = request.args.get('fecha_inicio')
    fecha_fin_str = request.args.get('fecha_fin')
    cliente_id = request.args.get('cliente_id', type=int)
    order_num = request.args.get('order_num', '').strip()
    export = request.args.get('export', '0') == '1'
    sort = request.args.get('sort', 'fecha')
    order = request.args.get('order', 'desc')
    page = request.args.get('page', 1, type=int)
    per_page = 20

    query = Movimiento.query.join(Producto, Movimiento.producto_id == Producto.id)

    if categoria_id:
        cat_ids = get_all_subcategory_ids(categoria_id)
        if cat_ids:
            query = query.filter(Producto.categoria_id.in_(cat_ids))
    if producto_id:
        query = query.filter(Movimiento.producto_id == producto_id)
    if tipo:
        query = query.filter(Movimiento.tipo == tipo)
    if fecha_inicio_str:
        try:
            fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d')
            query = query.filter(Movimiento.fecha >= fecha_inicio)
        except:
            pass
    if fecha_fin_str:
        try:
            fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d') + timedelta(days=1) - timedelta(seconds=1)
            query = query.filter(Movimiento.fecha <= fecha_fin)
        except:
            pass

    if cliente_id or order_num:
        query = query.join(Order, Movimiento.orden_id == Order.id)
        if cliente_id:
            query = query.filter(Order.client_id == cliente_id)
        if order_num:
            query = query.filter(Order.order_num.ilike(f'%{order_num}%'))

    if sort == 'fecha':
        sort_col = Movimiento.fecha
    elif sort == 'producto':
        sort_col = Producto.nombre
    elif sort == 'tipo':
        sort_col = Movimiento.tipo
    elif sort == 'cantidad':
        sort_col = Movimiento.cantidad
    elif sort == 'costo':
        sort_col = Movimiento.costo_total
    elif sort == 'categoria':
        sort_col = Producto.categoria_id
    else:
        sort_col = Movimiento.fecha

    if order == 'asc':
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())

    query = query.options(
        joinedload(Movimiento.producto),
        joinedload(Movimiento.orden).joinedload(Order.client)
    )

    paginated = query.paginate(page=page, per_page=per_page, error_out=False)
    movimientos = paginated.items
    total_movimientos = paginated.total
    total_pages = paginated.pages

    for m in movimientos:
        if m.producto and m.producto.es_material_impresion and m.producto.ancho_rollo and m.producto.ancho_rollo > 0:
            m.cantidad_metros_m2 = (m.cantidad_metros or 0) * m.producto.ancho_rollo
        else:
            m.cantidad_metros_m2 = None

    if export:
        return exportar_movimientos_excel(movimientos)

    chart_data = generar_datos_graficos_movimientos(movimientos)

    productos = Producto.query.order_by(Producto.nombre).all()
    categorias = Categoria.query.order_by(Categoria.nombre).all()
    clientes = Client.query.order_by(Client.nombre).all()
    tipos_lista = ['entrada', 'consumo', 'reserva', 'merma', 'sobrante', 'correccion_baja', 'correccion_alta']
    fecha_inicio_defecto = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    fecha_fin_defecto = datetime.now().strftime('%Y-%m-%d')

    return render_template('movimientos.html',
                           movimientos=movimientos,
                           productos=productos,
                           categorias=categorias,
                           clientes=clientes,
                           cliente_seleccionado=cliente_id,
                           order_num=order_num,
                           tipos=tipos_lista,
                           producto_seleccionado=producto_id,
                           categoria_seleccionada=categoria_id,
                           tipo_seleccionado=tipo,
                           fecha_inicio=fecha_inicio_str or fecha_inicio_defecto,
                           fecha_fin=fecha_fin_str or fecha_fin_defecto,
                           chart_data=json.dumps(chart_data),
                           sort=sort,
                           order=order,
                           total_movimientos=total_movimientos,
                           page=page,
                           total_pages=total_pages,
                           per_page=per_page)

def exportar_movimientos_excel(movimientos):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Movimientos'
    headers = ['ID', 'Producto', 'Categoría', 'Tipo', 'Cantidad', 'Cantidad (m lineales)', 'Área (m²)', 'Costo', 'Fecha', 'Comentario', 'Orden']
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal='center')
        cell.fill = PatternFill(start_color='D3D3D3', end_color='D3D3D3', fill_type='solid')
    for row_idx, mov in enumerate(movimientos, 2):
        ws.cell(row=row_idx, column=1, value=mov.id)
        ws.cell(row=row_idx, column=2, value=mov.producto.nombre if mov.producto else '')
        ws.cell(row=row_idx, column=3, value=mov.producto.categoria.nombre if mov.producto and mov.producto.categoria else '')
        ws.cell(row=row_idx, column=4, value=mov.tipo)
        ws.cell(row=row_idx, column=5, value=round(mov.cantidad, 2))
        ws.cell(row=row_idx, column=6, value=round(mov.cantidad_metros, 2) if mov.cantidad_metros else '')
        if mov.producto and mov.producto.es_material_impresion and mov.producto.ancho_rollo:
            area = (mov.cantidad_metros or 0) * mov.producto.ancho_rollo
            ws.cell(row=row_idx, column=7, value=round(area, 2) if area else '')
        else:
            ws.cell(row=row_idx, column=7, value='')
        if mov.tipo == 'entrada' and mov.costo_total:
            ws.cell(row=row_idx, column=8, value=round(mov.costo_total, 2))
        else:
            ws.cell(row=row_idx, column=8, value='')
        ws.cell(row=row_idx, column=9, value=mov.fecha.strftime('%Y-%m-%d %H:%M') if mov.fecha else '')
        ws.cell(row=row_idx, column=10, value=mov.comentario or '')
        ws.cell(row=row_idx, column=11, value=mov.orden.order_num if mov.orden else '')
    for col in range(1, len(headers)+1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 18
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output,
                     as_attachment=True,
                     download_name=f'movimientos_{datetime.now().strftime("%Y%m%d")}.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

def generar_datos_graficos_movimientos(movimientos):
    TIPOS_ORDEN = ['entrada', 'consumo', 'reserva', 'merma', 'sobrante', 'correccion_baja', 'correccion_alta']
    colores = {
        'entrada':          '#10b981',
        'consumo':          '#f59e0b',
        'reserva':          '#3b82f6',
        'merma':            '#dc2626',
        'sobrante':         '#0ea5e9',
        'correccion_baja':  '#92400e',
        'correccion_alta':  '#3730a3',
    }
    dict_diario = defaultdict(lambda: {t: 0 for t in TIPOS_ORDEN})
    for m in movimientos:
        fecha_key = m.fecha.strftime('%Y-%m-%d')
        if m.tipo in dict_diario[fecha_key]:
            dict_diario[fecha_key][m.tipo] += m.cantidad
    fechas_ordenadas = sorted(dict_diario.keys())
    datasets = []
    for t in TIPOS_ORDEN:
        data = [dict_diario[fecha].get(t, 0) for fecha in fechas_ordenadas]
        if any(data):
            datasets.append({
                'label': t.replace('_', ' ').title(),
                'data': data,
                'borderColor': colores.get(t, '#888'),
                'backgroundColor': colores.get(t, '#888') + '40',
                'fill': False,
                'tension': 0.3
            })
    dict_tipos = defaultdict(float)
    for m in movimientos:
        dict_tipos[m.tipo] += m.cantidad
    pie_labels = list(dict_tipos.keys())
    pie_values = [round(v, 2) for v in dict_tipos.values()]

    dict_productos = defaultdict(float)
    for m in movimientos:
        if m.producto:
            dict_productos[m.producto.nombre] += m.cantidad
    top_productos = sorted(dict_productos.items(), key=lambda x: x[1], reverse=True)[:10]
    top_labels = [p[0] for p in top_productos]
    top_values = [round(p[1], 2) for p in top_productos]

    return {
        'fechas': fechas_ordenadas,
        'datasets': datasets,
        'pie_labels': pie_labels,
        'pie_values': pie_values,
        'top_labels': top_labels,
        'top_values': top_values
    }

# ==========================================
# EXPORTAR PRODUCTOS
# ==========================================
@inventario_bp.route('/exportar', methods=['GET', 'POST'])
@login_required
@economico_or_admin_required
def exportar_productos():
    if request.method == 'POST':
        columnas = request.form.getlist('columnas')
        if not columnas:
            flash('Selecciona al menos una columna.', 'danger')
            return redirect(url_for('inventario.exportar_productos'))

        categoria_id = request.form.get('categoria_id', type=int)
        query = Producto.query
        if categoria_id:
            cat_ids = get_all_subcategory_ids(categoria_id)
            if cat_ids:
                query = query.filter(Producto.categoria_id.in_(cat_ids))
        productos = query.order_by(Producto.nombre).all()

        mapa_columnas = {
            'id': 'id', 'nombre': 'nombre', 'descripcion': 'descripcion',
            'costo': 'costo', 'inversion_total': 'inversion_total',
            'stock': 'stock', 'stock_metros': 'stock_metros',
            'stock_minimo': 'stock_minimo',
            'stock_comprometido': 'stock_comprometido',
            'stock_comprometido_metros': 'stock_comprometido_metros',
            'fecha_vencimiento': 'fecha_vencimiento',
            'categoria': 'categoria.nombre', 'area': 'area.nombre',
            'ubicacion': 'ubicacion_rel.nombre', 'tipo_producto': 'tipo_rel.nombre',
            'unidad_medida': 'unidad_rel.nombre', 'simbolo_unidad': 'unidad_rel.simbolo',
            'ancho_rollo': 'ancho_rollo', 'largo_rollo': 'largo_rollo',
            'gap_panno_cm': 'gap_panno_cm',
            'es_material_impresion': 'es_material_impresion',
            'atributos_extra': 'atributos_extra', 'created_at': 'created_at'
        }

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Productos'
        for col_idx, col_name in enumerate(columnas, 1):
            cell = ws.cell(row=1, column=col_idx, value=col_name.replace('_', ' ').title())
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal='center')
            cell.fill = PatternFill(start_color='D3D3D3', end_color='D3D3D3', fill_type='solid')

        for row_idx, prod in enumerate(productos, 2):
            for col_idx, col_name in enumerate(columnas, 1):
                attr = mapa_columnas.get(col_name)
                valor = None
                if attr:
                    if '.' in attr:
                        parts = attr.split('.')
                        obj = prod
                        for part in parts:
                            if obj:
                                obj = getattr(obj, part, None)
                        valor = obj
                    else:
                        valor = getattr(prod, attr, None)
                    if isinstance(valor, datetime):
                        valor = valor.strftime('%Y-%m-%d %H:%M')
                    elif isinstance(valor, date):
                        valor = valor.strftime('%Y-%m-%d')
                    elif isinstance(valor, float):
                        valor = round(valor, 2)
                    elif isinstance(valor, bool):
                        valor = 'Sí' if valor else 'No'
                    elif isinstance(valor, (dict, list)):
                        valor = json.dumps(valor, ensure_ascii=False)
                ws.cell(row=row_idx, column=col_idx, value=valor)

        for col in range(1, len(columnas)+1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 18
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return send_file(output,
                         as_attachment=True,
                         download_name=f'productos_{datetime.now().strftime("%Y%m%d")}.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    categoria_id = request.args.get('categoria_id', type=int)
    categorias = Categoria.query.order_by(Categoria.nombre).all()
    areas = Area.query.order_by(Area.nombre).all()
    categoria_options = get_categoria_options()

    columnas_disponibles = [
        {'id': 'id', 'label': 'ID'},
        {'id': 'nombre', 'label': 'Nombre'},
        {'id': 'descripcion', 'label': 'Descripción'},
        {'id': 'costo', 'label': 'Costo Unitario'},
        {'id': 'inversion_total', 'label': 'Inversión Total'},
        {'id': 'stock', 'label': 'Stock (unidades)'},
        {'id': 'stock_metros', 'label': 'Stock (metros lineales)'},
        {'id': 'stock_minimo', 'label': 'Stock Mínimo'},
        {'id': 'stock_comprometido', 'label': 'Comprometido (unidades)'},
        {'id': 'stock_comprometido_metros', 'label': 'Comprometido (metros lineales)'},
        {'id': 'fecha_vencimiento', 'label': 'Fecha Vencimiento'},
        {'id': 'categoria', 'label': 'Categoría'},
        {'id': 'area', 'label': 'Área'},
        {'id': 'ubicacion', 'label': 'Ubicación'},
        {'id': 'tipo_producto', 'label': 'Tipo de Producto'},
        {'id': 'unidad_medida', 'label': 'Unidad de Medida'},
        {'id': 'simbolo_unidad', 'label': 'Símbolo de Unidad'},
        {'id': 'ancho_rollo', 'label': 'Ancho Rollo (m)'},
        {'id': 'largo_rollo', 'label': 'Largo Rollo (m)'},
        {'id': 'gap_panno_cm', 'label': 'Gap entre Paños (cm)'},
        {'id': 'es_material_impresion', 'label': 'Material Impresión'},
        {'id': 'atributos_extra', 'label': 'Atributos Extra (JSON)'},
        {'id': 'created_at', 'label': 'Fecha Creación'}
    ]
    return render_template('exportar_productos.html',
                           columnas=columnas_disponibles,
                           categorias=categorias,
                           areas=areas,
                           categoria_options=categoria_options,
                           categoria_seleccionada=categoria_id)

# ==========================================
# IMPORTAR PRODUCTOS
# ==========================================
@inventario_bp.route('/importar', methods=['GET', 'POST'])
@login_required
@economico_or_admin_required
def importar_productos():
    if request.method == 'POST':
        if 'archivo' not in request.files:
            flash('No se seleccionó ningún archivo.', 'danger')
            return redirect(url_for('inventario.importar_productos'))
        archivo = request.files['archivo']
        if archivo.filename == '':
            flash('No se seleccionó ningún archivo.', 'danger')
            return redirect(url_for('inventario.importar_productos'))
        if not archivo.filename.endswith(('.xlsx', '.xls')):
            flash('Formato no soportado. Use .xlsx o .xls', 'danger')
            return redirect(url_for('inventario.importar_productos'))

        try:
            wb = openpyxl.load_workbook(archivo)
            ws = wb.active

            headers = [cell.value.strip() if cell.value else '' for cell in ws[1]]
            col_map = {}
            for idx, h in enumerate(headers):
                h_clean = h.lower().replace(' ', '_').replace('(', '').replace(')', '').replace('ñ', 'n')
                if 'nombre' in h_clean:
                    col_map['nombre'] = idx
                elif 'descripcion' in h_clean:
                    col_map['descripcion'] = idx
                elif 'costo' in h_clean and 'unitario' in h_clean:
                    col_map['costo'] = idx
                elif 'inversion_total' in h_clean or 'inversion' in h_clean:
                    col_map['inversion_total'] = idx
                elif 'stock' in h_clean and 'minimo' not in h_clean and 'comprometido' not in h_clean and 'metros' not in h_clean:
                    col_map['stock'] = idx
                elif 'stock_metros' in h_clean or 'stock metros' in h_clean:
                    col_map['stock_metros'] = idx
                elif 'stock_minimo' in h_clean or 'minimo' in h_clean:
                    col_map['stock_minimo'] = idx
                elif 'stock_comprometido' in h_clean and 'metros' not in h_clean:
                    col_map['stock_comprometido'] = idx
                elif 'stock_comprometido_metros' in h_clean or 'comprometido metros' in h_clean:
                    col_map['stock_comprometido_metros'] = idx
                elif 'vencimiento' in h_clean:
                    col_map['fecha_vencimiento'] = idx
                elif 'categoria' in h_clean:
                    col_map['categoria'] = idx
                elif 'area' in h_clean:
                    col_map['area'] = idx
                elif 'gap' in h_clean or 'pano' in h_clean or 'paño' in h_clean:
                    col_map['gap_panno_cm'] = idx
                elif 'ancho_rollo' in h_clean or 'ancho' in h_clean:
                    col_map['ancho_rollo'] = idx
                elif 'largo_rollo' in h_clean or 'largo' in h_clean:
                    col_map['largo_rollo'] = idx
                elif 'material_impresion' in h_clean:
                    col_map['es_material_impresion'] = idx
                elif 'unidad_medida' in h_clean or 'unidad de medida' in h_clean:
                    col_map['unidad_medida'] = idx
                elif 'simbolo_unidad' in h_clean or 'simbolo' in h_clean:
                    col_map['simbolo_unidad'] = idx
                elif 'atributos_extra' in h_clean or 'atributos' in h_clean:
                    col_map['atributos_extra'] = idx

            if 'nombre' not in col_map:
                flash('El archivo debe contener una columna "Nombre".', 'danger')
                return redirect(url_for('inventario.importar_productos'))

            contador = 0
            actualizados = 0

            for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                if not row or not any(row):
                    continue
                nombre = str(row[col_map['nombre']]).strip() if col_map.get('nombre') is not None and row[col_map['nombre']] else ''
                if not nombre:
                    continue

                producto = Producto.query.filter_by(nombre=nombre).first()
                if producto:
                    if col_map.get('descripcion') is not None and row[col_map['descripcion']]:
                        producto.descripcion = str(row[col_map['descripcion']]).strip()
                    if col_map.get('costo') is not None and row[col_map['costo']]:
                        try:
                            producto.costo = float(str(row[col_map['costo']]).replace(',', ''))
                        except:
                            pass
                    if col_map.get('inversion_total') is not None and row[col_map['inversion_total']]:
                        try:
                            producto.inversion_total = float(str(row[col_map['inversion_total']]).replace(',', ''))
                        except:
                            pass
                    if col_map.get('stock') is not None and row[col_map['stock']]:
                        try:
                            producto.stock = float(str(row[col_map['stock']]).replace(',', ''))
                        except:
                            pass
                    if col_map.get('stock_metros') is not None and row[col_map['stock_metros']]:
                        try:
                            producto.stock_metros = float(str(row[col_map['stock_metros']]).replace(',', ''))
                        except:
                            pass
                    if col_map.get('stock_minimo') is not None and row[col_map['stock_minimo']]:
                        try:
                            producto.stock_minimo = float(str(row[col_map['stock_minimo']]).replace(',', ''))
                        except:
                            pass
                    if col_map.get('stock_comprometido') is not None and row[col_map['stock_comprometido']]:
                        try:
                            producto.stock_comprometido = float(str(row[col_map['stock_comprometido']]).replace(',', ''))
                        except:
                            pass
                    if col_map.get('stock_comprometido_metros') is not None and row[col_map['stock_comprometido_metros']]:
                        try:
                            producto.stock_comprometido_metros = float(str(row[col_map['stock_comprometido_metros']]).replace(',', ''))
                        except:
                            pass
                    if col_map.get('fecha_vencimiento') is not None and row[col_map['fecha_vencimiento']]:
                        try:
                            val = row[col_map['fecha_vencimiento']]
                            if isinstance(val, datetime):
                                producto.fecha_vencimiento = val.date()
                            elif isinstance(val, (int, float)):
                                producto.fecha_vencimiento = date(1899, 12, 30) + timedelta(days=int(val))
                            else:
                                producto.fecha_vencimiento = datetime.strptime(str(val), '%Y-%m-%d').date()
                        except:
                            pass
                    if col_map.get('ancho_rollo') is not None and row[col_map['ancho_rollo']]:
                        try:
                            producto.ancho_rollo = float(str(row[col_map['ancho_rollo']]).replace(',', ''))
                        except:
                            pass
                    if col_map.get('largo_rollo') is not None and row[col_map['largo_rollo']]:
                        try:
                            producto.largo_rollo = float(str(row[col_map['largo_rollo']]).replace(',', ''))
                        except:
                            pass
                    if col_map.get('gap_panno_cm') is not None and row[col_map['gap_panno_cm']]:
                        try:
                            producto.gap_panno_cm = float(str(row[col_map['gap_panno_cm']]).replace(',', ''))
                        except:
                            pass
                    if col_map.get('es_material_impresion') is not None and row[col_map['es_material_impresion']]:
                        val = str(row[col_map['es_material_impresion']]).strip().lower()
                        producto.es_material_impresion = val in ['sí', 'si', 'yes', 'true', '1', 'x', 'on']

                    if col_map.get('categoria') is not None and row[col_map['categoria']]:
                        cat_nombre = str(row[col_map['categoria']]).strip()
                        if cat_nombre:
                            cat = Categoria.query.filter_by(nombre=cat_nombre).first()
                            if not cat:
                                cat = Categoria(nombre=cat_nombre)
                                db.session.add(cat)
                                db.session.flush()
                            producto.categoria_id = cat.id
                    if col_map.get('area') is not None and row[col_map['area']]:
                        area_nombre = str(row[col_map['area']]).strip()
                        if area_nombre:
                            area = Area.query.filter_by(nombre=area_nombre).first()
                            if not area:
                                area = Area(nombre=area_nombre)
                                db.session.add(area)
                                db.session.flush()
                            producto.area_id = area.id
                    if col_map.get('unidad_medida') is not None and row[col_map['unidad_medida']]:
                        uni_nombre = str(row[col_map['unidad_medida']]).strip()
                        if uni_nombre:
                            uni = Unidad.query.filter_by(nombre=uni_nombre).first()
                            if not uni:
                                simbolo = str(row[col_map['simbolo_unidad']]).strip() if col_map.get('simbolo_unidad') is not None and row[col_map['simbolo_unidad']] else ''
                                uni = Unidad(nombre=uni_nombre, simbolo=simbolo)
                                db.session.add(uni)
                                db.session.flush()
                            producto.unidad_id = uni.id

                    if col_map.get('atributos_extra') is not None and row[col_map['atributos_extra']]:
                        try:
                            attr_val = row[col_map['atributos_extra']]
                            if isinstance(attr_val, str):
                                producto.atributos_extra = json.loads(attr_val)
                            elif isinstance(attr_val, dict):
                                producto.atributos_extra = attr_val
                        except:
                            pass

                    producto.updated_at = datetime.now()
                    actualizados += 1
                else:
                    nuevo = Producto(nombre=nombre)
                    if col_map.get('descripcion') is not None and row[col_map['descripcion']]:
                        nuevo.descripcion = str(row[col_map['descripcion']]).strip()
                    if col_map.get('costo') is not None and row[col_map['costo']]:
                        try:
                            nuevo.costo = float(str(row[col_map['costo']]).replace(',', ''))
                        except:
                            pass
                    if col_map.get('inversion_total') is not None and row[col_map['inversion_total']]:
                        try:
                            nuevo.inversion_total = float(str(row[col_map['inversion_total']]).replace(',', ''))
                        except:
                            pass
                    if col_map.get('stock') is not None and row[col_map['stock']]:
                        try:
                            nuevo.stock = float(str(row[col_map['stock']]).replace(',', ''))
                        except:
                            pass
                    if col_map.get('stock_metros') is not None and row[col_map['stock_metros']]:
                        try:
                            nuevo.stock_metros = float(str(row[col_map['stock_metros']]).replace(',', ''))
                        except:
                            pass
                    if col_map.get('stock_minimo') is not None and row[col_map['stock_minimo']]:
                        try:
                            nuevo.stock_minimo = float(str(row[col_map['stock_minimo']]).replace(',', ''))
                        except:
                            pass
                    if col_map.get('stock_comprometido') is not None and row[col_map['stock_comprometido']]:
                        try:
                            nuevo.stock_comprometido = float(str(row[col_map['stock_comprometido']]).replace(',', ''))
                        except:
                            pass
                    if col_map.get('stock_comprometido_metros') is not None and row[col_map['stock_comprometido_metros']]:
                        try:
                            nuevo.stock_comprometido_metros = float(str(row[col_map['stock_comprometido_metros']]).replace(',', ''))
                        except:
                            pass
                    if col_map.get('fecha_vencimiento') is not None and row[col_map['fecha_vencimiento']]:
                        try:
                            val = row[col_map['fecha_vencimiento']]
                            if isinstance(val, datetime):
                                nuevo.fecha_vencimiento = val.date()
                            elif isinstance(val, (int, float)):
                                nuevo.fecha_vencimiento = date(1899, 12, 30) + timedelta(days=int(val))
                            else:
                                nuevo.fecha_vencimiento = datetime.strptime(str(val), '%Y-%m-%d').date()
                        except:
                            pass
                    if col_map.get('ancho_rollo') is not None and row[col_map['ancho_rollo']]:
                        try:
                            nuevo.ancho_rollo = float(str(row[col_map['ancho_rollo']]).replace(',', ''))
                        except:
                            pass
                    if col_map.get('largo_rollo') is not None and row[col_map['largo_rollo']]:
                        try:
                            nuevo.largo_rollo = float(str(row[col_map['largo_rollo']]).replace(',', ''))
                        except:
                            pass
                    if col_map.get('gap_panno_cm') is not None and row[col_map['gap_panno_cm']]:
                        try:
                            nuevo.gap_panno_cm = float(str(row[col_map['gap_panno_cm']]).replace(',', ''))
                        except:
                            pass
                    if col_map.get('es_material_impresion') is not None and row[col_map['es_material_impresion']]:
                        val = str(row[col_map['es_material_impresion']]).strip().lower()
                        nuevo.es_material_impresion = val in ['sí', 'si', 'yes', 'true', '1', 'x', 'on']

                    if col_map.get('categoria') is not None and row[col_map['categoria']]:
                        cat_nombre = str(row[col_map['categoria']]).strip()
                        if cat_nombre:
                            cat = Categoria.query.filter_by(nombre=cat_nombre).first()
                            if not cat:
                                cat = Categoria(nombre=cat_nombre)
                                db.session.add(cat)
                                db.session.flush()
                            nuevo.categoria_id = cat.id
                    if col_map.get('area') is not None and row[col_map['area']]:
                        area_nombre = str(row[col_map['area']]).strip()
                        if area_nombre:
                            area = Area.query.filter_by(nombre=area_nombre).first()
                            if not area:
                                area = Area(nombre=area_nombre)
                                db.session.add(area)
                                db.session.flush()
                            nuevo.area_id = area.id
                    if col_map.get('unidad_medida') is not None and row[col_map['unidad_medida']]:
                        uni_nombre = str(row[col_map['unidad_medida']]).strip()
                        if uni_nombre:
                            simbolo = str(row[col_map['simbolo_unidad']]).strip() if col_map.get('simbolo_unidad') is not None and row[col_map['simbolo_unidad']] else ''
                            uni = Unidad.query.filter_by(nombre=uni_nombre).first()
                            if not uni:
                                uni = Unidad(nombre=uni_nombre, simbolo=simbolo)
                                db.session.add(uni)
                                db.session.flush()
                            nuevo.unidad_id = uni.id
                    if col_map.get('atributos_extra') is not None and row[col_map['atributos_extra']]:
                        try:
                            attr_val = row[col_map['atributos_extra']]
                            if isinstance(attr_val, str):
                                nuevo.atributos_extra = json.loads(attr_val)
                            elif isinstance(attr_val, dict):
                                nuevo.atributos_extra = attr_val
                        except:
                            pass

                    db.session.add(nuevo)
                    contador += 1

            db.session.commit()
            flash(f'Importación completada: {contador} nuevos, {actualizados} actualizados.', 'success')
            return redirect(url_for('inventario.index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al importar: {str(e)}', 'danger')
            return redirect(url_for('inventario.importar_productos'))

    return render_template('importar_productos.html')

# ==========================================
# API ATRIBUTOS DINÁMICOS (con herencia)
# ==========================================
@inventario_bp.route('/api/atributos-por-categoria/<int:categoria_id>')
@login_required
def api_atributos_por_categoria(categoria_id):
    cat = Categoria.query.get_or_404(categoria_id)
    grupo = get_grupo_atributos_para_categoria(categoria_id)
    atributos = []
    if grupo:
        atributos = [{
            'id': a.id,
            'nombre': a.nombre,
            'etiqueta': a.etiqueta,
            'tipo': a.tipo,
            'requerido': a.requerido,
            'opciones': a.opciones.split(',') if a.opciones else []
        } for a in grupo.atributos.order_by(Atributo.orden).all()]

    return jsonify({
        'atributos': atributos,
        'es_material_impresion': cat.es_material_impresion,
        'grupo_origen': grupo.nombre if grupo else None,
        'grupo_categoria': grupo.categoria.nombre if grupo and grupo.categoria else None
    })

# ==========================================
# GRUPOS DE ATRIBUTOS
# ==========================================
@inventario_bp.route('/grupos-atributos')
@login_required
@admin_required
def listar_grupos():
    grupos = GrupoAtributos.query.order_by(GrupoAtributos.nombre).all()
    return render_template('grupos_atributos.html', grupos=grupos)

@inventario_bp.route('/grupo-atributos/crear', methods=['GET', 'POST'])
@login_required
@admin_required
def crear_grupo():
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        categoria_id = request.form.get('categoria_id', type=int) or None
        if not nombre:
            flash('El nombre es obligatorio.', 'danger')
            return render_template('form_grupo_atributos.html', categoria_options=get_categoria_options())
        if GrupoAtributos.query.filter_by(nombre=nombre).first():
            flash('Ya existe un grupo con ese nombre.', 'danger')
            return render_template('form_grupo_atributos.html', categoria_options=get_categoria_options())
        grupo = GrupoAtributos(nombre=nombre, descripcion=descripcion, categoria_id=categoria_id)
        db.session.add(grupo)
        db.session.commit()
        flash(f'Grupo "{nombre}" creado correctamente.', 'success')
        return redirect(url_for('inventario.listar_grupos'))
    categoria_options = get_categoria_options()
    return render_template('form_grupo_atributos.html', categoria_options=categoria_options)

@inventario_bp.route('/grupo-atributos/editar/<int:grupo_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_grupo(grupo_id):
    grupo = GrupoAtributos.query.get_or_404(grupo_id)
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        categoria_id = request.form.get('categoria_id', type=int) or None
        if not nombre:
            flash('El nombre es obligatorio.', 'danger')
            return render_template('form_grupo_atributos.html', grupo=grupo, categoria_options=get_categoria_options())
        existente = GrupoAtributos.query.filter(GrupoAtributos.nombre == nombre, GrupoAtributos.id != grupo.id).first()
        if existente:
            flash('Ya existe otro grupo con ese nombre.', 'danger')
            return render_template('form_grupo_atributos.html', grupo=grupo, categoria_options=get_categoria_options())
        grupo.nombre = nombre
        grupo.descripcion = descripcion
        grupo.categoria_id = categoria_id
        db.session.commit()
        flash('Grupo actualizado.', 'success')
        return redirect(url_for('inventario.listar_grupos'))
    categoria_options = get_categoria_options()
    return render_template('form_grupo_atributos.html', grupo=grupo, categoria_options=categoria_options)

@inventario_bp.route('/grupo-atributos/eliminar/<int:grupo_id>', methods=['POST'])
@login_required
@admin_required
def eliminar_grupo(grupo_id):
    grupo = GrupoAtributos.query.get_or_404(grupo_id)
    db.session.delete(grupo)
    db.session.commit()
    flash('Grupo eliminado.', 'success')
    return redirect(url_for('inventario.listar_grupos'))

@inventario_bp.route('/grupo-atributos/<int:grupo_id>/atributos')
@login_required
@admin_required
def listar_atributos(grupo_id):
    grupo = GrupoAtributos.query.get_or_404(grupo_id)
    atributos = grupo.atributos.order_by(Atributo.orden).all()
    return render_template('atributos_list.html', grupo=grupo, atributos=atributos)

@inventario_bp.route('/grupo-atributos/<int:grupo_id>/atributo/crear', methods=['GET', 'POST'])
@login_required
@admin_required
def crear_atributo(grupo_id):
    grupo = GrupoAtributos.query.get_or_404(grupo_id)
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        etiqueta = request.form.get('etiqueta', '').strip()
        tipo = request.form.get('tipo', '').strip()
        requerido = request.form.get('requerido') == 'on'
        opciones = request.form.get('opciones', '')
        orden = request.form.get('orden', type=int, default=0)
        if not nombre or not etiqueta or not tipo:
            flash('Nombre, etiqueta y tipo son obligatorios.', 'danger')
            return render_template('form_atributo.html', grupo=grupo)
        if Atributo.query.filter_by(grupo_id=grupo_id, nombre=nombre).first():
            flash('Ya existe un atributo con ese nombre en este grupo.', 'danger')
            return render_template('form_atributo.html', grupo=grupo)
        attr = Atributo(grupo_id=grupo_id, nombre=nombre, etiqueta=etiqueta, tipo=tipo, requerido=requerido, opciones=opciones, orden=orden)
        db.session.add(attr)
        db.session.commit()
        flash('Atributo creado correctamente.', 'success')
        return redirect(url_for('inventario.listar_atributos', grupo_id=grupo_id))
    return render_template('form_atributo.html', grupo=grupo)

@inventario_bp.route('/grupo-atributos/<int:grupo_id>/atributo/editar/<int:atributo_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_atributo(grupo_id, atributo_id):
    grupo = GrupoAtributos.query.get_or_404(grupo_id)
    attr = Atributo.query.get_or_404(atributo_id)
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        etiqueta = request.form.get('etiqueta', '').strip()
        tipo = request.form.get('tipo', '').strip()
        requerido = request.form.get('requerido') == 'on'
        opciones = request.form.get('opciones', '')
        orden = request.form.get('orden', type=int, default=0)
        if not nombre or not etiqueta or not tipo:
            flash('Nombre, etiqueta y tipo son obligatorios.', 'danger')
            return render_template('form_atributo.html', grupo=grupo, atributo=attr)
        existente = Atributo.query.filter(Atributo.grupo_id == grupo_id, Atributo.nombre == nombre, Atributo.id != attr.id).first()
        if existente:
            flash('Ya existe otro atributo con ese nombre en este grupo.', 'danger')
            return render_template('form_atributo.html', grupo=grupo, atributo=attr)
        attr.nombre = nombre
        attr.etiqueta = etiqueta
        attr.tipo = tipo
        attr.requerido = requerido
        attr.opciones = opciones
        attr.orden = orden
        db.session.commit()
        flash('Atributo actualizado.', 'success')
        return redirect(url_for('inventario.listar_atributos', grupo_id=grupo_id))
    return render_template('form_atributo.html', grupo=grupo, atributo=attr)

@inventario_bp.route('/grupo-atributos/<int:grupo_id>/atributo/eliminar/<int:atributo_id>', methods=['POST'])
@login_required
@admin_required
def eliminar_atributo(grupo_id, atributo_id):
    attr = Atributo.query.get_or_404(atributo_id)
    db.session.delete(attr)
    db.session.commit()
    flash('Atributo eliminado.', 'success')
    return redirect(url_for('inventario.listar_atributos', grupo_id=grupo_id))

# ==========================================
# PROVEEDORES
# ==========================================
@inventario_bp.route('/proveedores')
@login_required
@economico_or_admin_required
def listar_proveedores():
    proveedores = Proveedor.query.order_by(Proveedor.nombre).all()
    return render_template('proveedores.html', proveedores=proveedores)

@inventario_bp.route('/proveedor/crear', methods=['GET', 'POST'])
@login_required
@economico_or_admin_required
def crear_proveedor():
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        if not nombre:
            flash('El nombre es obligatorio.', 'danger')
            return render_template('form_proveedor.html')
        proveedor = Proveedor(
            nombre=nombre,
            ruc=request.form.get('ruc', '').strip(),
            telefono=request.form.get('telefono', '').strip(),
            email=request.form.get('email', '').strip(),
            direccion=request.form.get('direccion', '').strip(),
            contacto=request.form.get('contacto', '').strip(),
            notas=request.form.get('notas', '').strip()
        )
        db.session.add(proveedor)
        db.session.commit()
        flash(f'Proveedor "{nombre}" creado correctamente.', 'success')
        return redirect(url_for('inventario.listar_proveedores'))
    return render_template('form_proveedor.html')

@inventario_bp.route('/proveedor/editar/<int:proveedor_id>', methods=['GET', 'POST'])
@login_required
@economico_or_admin_required
def editar_proveedor(proveedor_id):
    proveedor = Proveedor.query.get_or_404(proveedor_id)
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        if not nombre:
            flash('El nombre es obligatorio.', 'danger')
            return render_template('form_proveedor.html', proveedor=proveedor)
        proveedor.nombre = nombre
        proveedor.ruc = request.form.get('ruc', '').strip()
        proveedor.telefono = request.form.get('telefono', '').strip()
        proveedor.email = request.form.get('email', '').strip()
        proveedor.direccion = request.form.get('direccion', '').strip()
        proveedor.contacto = request.form.get('contacto', '').strip()
        proveedor.notas = request.form.get('notas', '').strip()
        db.session.commit()
        flash('Proveedor actualizado.', 'success')
        return redirect(url_for('inventario.listar_proveedores'))
    return render_template('form_proveedor.html', proveedor=proveedor)

@inventario_bp.route('/proveedor/eliminar/<int:proveedor_id>', methods=['POST'])
@login_required
@economico_or_admin_required
def eliminar_proveedor(proveedor_id):
    proveedor = Proveedor.query.get_or_404(proveedor_id)
    if Movimiento.query.filter_by(proveedor_id=proveedor.id).first():
        flash('No se puede eliminar un proveedor con movimientos asociados.', 'danger')
        return redirect(url_for('inventario.listar_proveedores'))
    db.session.delete(proveedor)
    db.session.commit()
    flash('Proveedor eliminado.', 'success')
    return redirect(url_for('inventario.listar_proveedores'))

# ==========================================
# ESTADÍSTICAS DE PROVEEDORES
# ==========================================
@inventario_bp.route('/proveedores/estadisticas')
@login_required
@economico_or_admin_required
def estadisticas_proveedores():
    stats = db.session.query(
        Proveedor.id,
        Proveedor.nombre,
        func.sum(Movimiento.cantidad).label('total_unidades'),
        func.sum(Movimiento.costo_total).label('total_inversion')
    ).join(Movimiento, Movimiento.proveedor_id == Proveedor.id)\
     .filter(Movimiento.tipo == 'entrada')\
     .group_by(Proveedor.id, Proveedor.nombre)\
     .order_by(func.sum(Movimiento.costo_total).desc()).all()
    return render_template('estadisticas_proveedores.html', stats=stats)

# ==========================================
# AYUDA
# ==========================================
@inventario_bp.route('/admin/help')
@login_required
@admin_required
def admin_help():
    return render_template('admin_help.html')

# ==========================================
# LEGACY
# ==========================================
@inventario_bp.route('/area/<int:area_id>')
@login_required
@economico_or_admin_required
def productos_por_area(area_id):
    area = Area.query.get_or_404(area_id)
    cat = Categoria.query.filter_by(nombre=area.nombre).first()
    if cat:
        return redirect(url_for('inventario.productos_por_categoria', categoria_id=cat.id))
    productos = Producto.query.filter_by(area_id=area_id).first()
    if productos and productos.categoria_id:
        return redirect(url_for('inventario.productos_por_categoria', categoria_id=productos.categoria_id))
    flash('No se encontró una categoría equivalente para esta área.', 'warning')
    return redirect(url_for('inventario.index'))

# ==========================================
# DESGLOSE DETALLADO DE MERMA POR PRODUCTO
# ==========================================
@inventario_bp.route('/producto/<int:producto_id>/desglose-merma')
@login_required
@economico_or_admin_required
def desglose_merma_producto(producto_id):
    """
    Vista detallada: muestra cada línea de orden que usó este producto,
    con el desglose de aire, gap efectivo, cut y material consumido.
    """
    producto = Producto.query.get_or_404(producto_id)
    
    archivos = ArchivoAdjunto.query.filter(
        ArchivoAdjunto.producto_id == producto_id,
        ArchivoAdjunto.parametros_etiqueta.isnot(None)
    ).order_by(ArchivoAdjunto.orden_id.desc()).all()
    
    lineas = []
    for a in archivos:
        try:
            params = json.loads(a.parametros_etiqueta) if a.parametros_etiqueta else {}
        except Exception:
            continue
        
        if 'merma_operativa_m2' not in params and 'merma_estimada_m2' not in params:
            continue
        
        orden = a.orden
        area = float(params.get('area_m2', 0) or 0)
        material = float(params.get('material_consumido_m2', 0) or 0)
        merma_op = float(params.get('merma_operativa_m2', params.get('merma_estimada_m2', 0)) or 0)
        merma_pct = (merma_op / area * 100) if area > 0 else 0
        
        lineas.append({
            'archivo_id': a.id,
            'orden_id': orden.id if orden else None,
            'orden_num': orden.order_num if orden else '—',
            'cliente': orden.client.nombre if orden and orden.client else '—',
            'fecha': orden.date if orden else None,
            'nombre_linea': a.nombre_visible,
            'cantidad': a.cantidad,
            'unidad': a.unidad,
            'ancho_cm': params.get('ancho', '—'),
            'alto_cm': params.get('alto', '—'),
            'n_paños': params.get('n_paños', 1),
            'filas': params.get('filas', 0),
            'columnas': params.get('columnas', 0),
            'area_facturada_m2': area,
            'material_consumido_m2': material,
            'largo_total_m': params.get('largo_total_m', 0),
            'merma_operativa_m2': merma_op,
            'merma_operativa_pct': merma_pct,
            'gap_usado_cm': params.get('gap_usado_cm', 6.5),
            'desglose_paños': params.get('desglose_paños', []),
        })
    
    # Totales
    total_area = sum(l['area_facturada_m2'] for l in lineas)
    total_material = sum(l['material_consumido_m2'] for l in lineas)
    total_merma = sum(l['merma_operativa_m2'] for l in lineas)
    total_pct = (total_merma / total_area * 100) if total_area > 0 else 0
    
    totales = {
        'area_facturada_m2': round(total_area, 2),
        'material_consumido_m2': round(total_material, 2),
        'merma_operativa_m2': round(total_merma, 2),
        'merma_operativa_pct': round(total_pct, 2),
        'total_lineas': len(lineas),
    }
    
    return render_template('desglose_merma_producto.html',
                           producto=producto,
                           lineas=lineas,
                           totales=totales)

# ==========================================
# CONTEO SEMANAL DEL ECONÓMICO
# ==========================================

def _calcular_merma_operativa_semana(semana):
    """Suma la merma operativa (m²) de todos los ArchivoAdjunto cuya orden
    cayó dentro de la semana ISO indicada."""
    from app.models import ConteoSemanal
    # Parsear semana "YYYY-Www"
    try:
        year, week = semana.split('-W')
        year, week = int(year), int(week)
    except Exception:
        return 0.0

    # Lunes de esa semana ISO
    lunes = datetime.fromisocalendar(year, week, 1)
    domingo = lunes + timedelta(days=7)

    archivos = ArchivoAdjunto.query.join(Order, ArchivoAdjunto.orden_id == Order.id).filter(
        Order.date >= lunes.date(),
        Order.date < domingo.date(),
        ArchivoAdjunto.parametros_etiqueta.isnot(None)
    ).all()

    total = 0.0
    for a in archivos:
        try:
            params = json.loads(a.parametros_etiqueta) if a.parametros_etiqueta else {}
        except Exception:
            continue
        total += float(params.get('merma_operativa_m2', 0) or 0)
    return round(total, 4)


@inventario_bp.route('/conteos-semanales')
@login_required
@economico_or_admin_required
def listar_conteos():
    """Listado de conteos semanales agrupados por semana."""
    from app.models import ConteoSemanal
    semana = request.args.get('semana', '').strip()
    producto_id = request.args.get('producto_id', type=int)

    query = ConteoSemanal.query
    if semana:
        query = query.filter(ConteoSemanal.semana == semana)
    if producto_id:
        query = query.filter(ConteoSemanal.producto_id == producto_id)

    conteos = query.order_by(ConteoSemanal.fecha.desc()).all()

    # Agrupar por semana para resumen
    semanas_resumen = {}
    for c in conteos:
        if c.semana not in semanas_resumen:
            semanas_resumen[c.semana] = {
                'semana': c.semana,
                'total_conteos': 0,
                'total_merma_imprevista_m2': 0.0,
                'total_merma_operativa_m2': 0.0,
                'fecha_primera': c.fecha,
            }
        semanas_resumen[c.semana]['total_conteos'] += 1
        semanas_resumen[c.semana]['total_merma_imprevista_m2'] += c.merma_imprevista_m2 or 0
        semanas_resumen[c.semana]['total_merma_operativa_m2'] += c.merma_operativa_semana_m2 or 0

    semanas_lista = sorted(semanas_resumen.values(), key=lambda x: x['semana'], reverse=True)

    # Lista de productos para el filtro
    productos = Producto.query.filter(
        Producto.es_material_impresion == True,
        Producto.largo_rollo > 0
    ).order_by(Producto.nombre).all()

    return render_template('conteos_semanales.html',
                           conteos=conteos,
                           semanas_lista=semanas_lista,
                           productos=productos,
                           semana_seleccionada=semana,
                           producto_seleccionado=producto_id)


@inventario_bp.route('/conteos-semanales/nuevo', methods=['GET', 'POST'])
@login_required
@economico_or_admin_required
def nuevo_conteo():
    """Formulario de conteo rápido semanal. Input: unidades (rollos)."""
    from app.models import ConteoSemanal

    if request.method == 'POST':
        producto_id = request.form.get('producto_id', type=int)
        stock_fisico_unidades = request.form.get('stock_fisico_unidades', type=float)
        comentario = request.form.get('comentario', '').strip()
        fecha_str = request.form.get('fecha', '').strip()

        if not producto_id or stock_fisico_unidades is None or stock_fisico_unidades < 0:
            flash('Datos inválidos. Verifica producto y unidades.', 'danger')
            return redirect(url_for('inventario.nuevo_conteo'))

        producto = Producto.query.get(producto_id)
        if not producto:
            flash('Producto no encontrado.', 'danger')
            return redirect(url_for('inventario.nuevo_conteo'))

        if not producto.largo_rollo or producto.largo_rollo <= 0:
            flash('El producto no tiene largo de rollo definido.', 'danger')
            return redirect(url_for('inventario.nuevo_conteo'))

        # Fecha del conteo (default: hoy)
        if fecha_str:
            try:
                fecha_conteo = datetime.strptime(fecha_str, '%Y-%m-%d')
            except Exception:
                fecha_conteo = datetime.utcnow()
        else:
            fecha_conteo = datetime.utcnow()

        semana = ConteoSemanal.semana_iso(fecha_conteo)

        # Snapshot del sistema
        stock_sistema_unidades = producto.stock or 0.0
        stock_sistema_metros = producto.stock_metros or 0.0

        # Conversiones (metros lineales y m²)
        largo_rollo = producto.largo_rollo
        ancho_rollo = producto.ancho_rollo or 1.34

        stock_fisico_metros = stock_fisico_unidades * largo_rollo
        stock_fisico_m2 = stock_fisico_metros * ancho_rollo
        stock_sistema_m2 = stock_sistema_metros * ancho_rollo

        # Diferencias
        diferencia_unidades = stock_sistema_unidades - stock_fisico_unidades
        diferencia_metros = stock_sistema_metros - stock_fisico_metros
        diferencia_m2 = stock_sistema_m2 - stock_fisico_m2

        # Merma operativa teórica de la semana
        merma_operativa_m2 = _calcular_merma_operativa_semana(semana)

        # Merma imprevista = diferencia en m² − merma operativa teórica
        merma_imprevista_m2 = diferencia_m2 - merma_operativa_m2
        merma_imprevista_metros = merma_imprevista_m2 / ancho_rollo if ancho_rollo > 0 else 0

        conteo = ConteoSemanal(
            producto_id=producto.id,
            usuario_id=current_user.id,
            fecha=fecha_conteo,
            semana=semana,
            stock_sistema_unidades=stock_sistema_unidades,
            stock_sistema_metros=stock_sistema_metros,
            stock_fisico_unidades=stock_fisico_unidades,
            stock_fisico_metros=stock_fisico_metros,
            diferencia_unidades=diferencia_unidades,
            diferencia_metros=diferencia_metros,
            merma_operativa_semana_m2=merma_operativa_m2,
            merma_imprevista_metros=merma_imprevista_metros,
            merma_imprevista_m2=merma_imprevista_m2,
            comentario=comentario
        )
        db.session.add(conteo)

        # Ajustar stock del sistema al valor contado
        if abs(diferencia_unidades) > 0.001:
            tipo = 'merma' if diferencia_unidades > 0 else 'sobrante'
            producto.stock = stock_fisico_unidades
            producto.stock_metros = stock_fisico_metros
            mov = Movimiento(
                producto_id=producto.id,
                tipo=tipo,
                cantidad=abs(diferencia_unidades),
                cantidad_metros=abs(diferencia_metros),
                comentario=f'Conteo semanal {semana}: {comentario or "ajuste por conteo"}',
                usuario_id=current_user.id,
                tipo_ajuste='conteo'
            )
            db.session.add(mov)

        db.session.commit()

        flash(f'Conteo registrado para la semana {semana}.', 'success')
        return redirect(url_for('inventario.reporte_conteos', semana=semana))

    # GET
    productos = Producto.query.filter(
        Producto.es_material_impresion == True,
        Producto.largo_rollo > 0
    ).order_by(Producto.nombre).all()

    return render_template('form_conteo_semanal.html',
                           productos=productos,
                           hoy=datetime.utcnow().strftime('%Y-%m-%d'))


@inventario_bp.route('/conteos-semanales/reporte')
@login_required
@economico_or_admin_required
def reporte_conteos():
    """Reporte detallado de una semana: merma operativa vs imprevista."""
    from app.models import ConteoSemanal

    semana = request.args.get('semana', ConteoSemanal.semana_iso())
    conteos = ConteoSemanal.query.filter_by(semana=semana).order_by(ConteoSemanal.fecha.desc()).all()

    # Agrupar por producto
    por_producto = {}
    for c in conteos:
        pid = c.producto_id
        if pid not in por_producto:
            por_producto[pid] = {
                'producto': c.producto,
                'conteos': [],
                'total_diferencia_m2': 0.0,
                'total_merma_operativa_m2': 0.0,
                'total_merma_imprevista_m2': 0.0,
            }
        por_producto[pid]['conteos'].append(c)
        por_producto[pid]['total_diferencia_m2'] += (c.diferencia_metros or 0) * (c.producto.ancho_rollo or 1.34)
        por_producto[pid]['total_merma_operativa_m2'] += c.merma_operativa_semana_m2 or 0
        por_producto[pid]['total_merma_imprevista_m2'] += c.merma_imprevista_m2 or 0

    # Totales globales
    total_diferencia_m2 = sum(v['total_diferencia_m2'] for v in por_producto.values())
    total_merma_operativa_m2 = sum(v['total_merma_operativa_m2'] for v in por_producto.values())
    total_merma_imprevista_m2 = sum(v['total_merma_imprevista_m2'] for v in por_producto.values())

    # Desglose de merma operativa POR ORDEN dentro de la semana
    try:
        year, week = semana.split('-W')
        year, week = int(year), int(week)
        lunes = datetime.fromisocalendar(year, week, 1)
        domingo = lunes + timedelta(days=7)
    except Exception:
        lunes = datetime.utcnow()
        domingo = lunes + timedelta(days=7)

    archivos_semana = ArchivoAdjunto.query.join(Order, ArchivoAdjunto.orden_id == Order.id).filter(
        Order.date >= lunes.date(),
        Order.date < domingo.date(),
        ArchivoAdjunto.parametros_etiqueta.isnot(None)
    ).all()

    merma_por_orden = {}
    for a in archivos_semana:
        try:
            params = json.loads(a.parametros_etiqueta) if a.parametros_etiqueta else {}
        except Exception:
            continue
        if 'merma_operativa_m2' not in params:
            continue
        orden = a.orden
        if not orden:
            continue
        key = orden.id
        if key not in merma_por_orden:
            merma_por_orden[key] = {
                'orden_id': orden.id,
                'orden_num': orden.order_num or 'Sin número',
                'cliente': orden.client.nombre if orden.client else 'Sin cliente',
                'fecha': orden.date,
                'lineas': [],
                'total_area_m2': 0.0,
                'total_material_m2': 0.0,
                'total_merma_m2': 0.0,
            }
        merma_por_orden[key]['lineas'].append({
            'nombre': a.nombre_visible,
            'producto': a.producto.nombre if a.producto else '—',
            'area_m2': float(params.get('area_m2', 0) or 0),
            'material_m2': float(params.get('material_consumido_m2', 0) or 0),
            'merma_m2': float(params.get('merma_operativa_m2', 0) or 0),
            'merma_pct': float(params.get('merma_operativa_pct', 0) or 0),
            'ancho_cm': params.get('ancho', '—'),
            'alto_cm': params.get('alto', '—'),
            'n_paños': params.get('n_paños', 1),
            'filas': params.get('filas', 0),
            'columnas': params.get('columnas', 0),
            'largo_total_m': float(params.get('largo_total_m', 0) or 0),
            'gap_usado_cm': params.get('gap_usado_cm', 6.5),
            'desglose_paños': params.get('desglose_paños', []),
        })
        merma_por_orden[key]['total_area_m2'] += float(params.get('area_m2', 0) or 0)
        merma_por_orden[key]['total_material_m2'] += float(params.get('material_consumido_m2', 0) or 0)
        merma_por_orden[key]['total_merma_m2'] += float(params.get('merma_operativa_m2', 0) or 0)

    ordenes_lista = sorted(merma_por_orden.values(), key=lambda x: x['total_merma_m2'], reverse=True)

    # Semanas disponibles para el dropdown
    semanas_disponibles = sorted(
        {c.semana for c in ConteoSemanal.query.all()},
        reverse=True
    )

    return render_template('reporte_conteos.html',
                           semana=semana,
                           conteos=conteos,
                           por_producto=por_producto,
                           ordenes_lista=ordenes_lista,
                           total_diferencia_m2=round(total_diferencia_m2, 2),
                           total_merma_operativa_m2=round(total_merma_operativa_m2, 2),
                           total_merma_imprevista_m2=round(total_merma_imprevista_m2, 2),
                           semanas_disponibles=semanas_disponibles)


@inventario_bp.route('/conteos-semanales/eliminar/<int:conteo_id>', methods=['POST'])
@login_required
@admin_required
def eliminar_conteo(conteo_id):
    from app.models import ConteoSemanal
    c = ConteoSemanal.query.get_or_404(conteo_id)
    db.session.delete(c)
    db.session.commit()
    flash('Conteo eliminado.', 'success')
    return redirect(url_for('inventario.listar_conteos'))

# ==========================================
# MERMA DETALLADA POR ORDEN (vista del económico)
# ==========================================
@inventario_bp.route('/merma-por-orden')
@login_required
@economico_or_admin_required
def merma_por_orden():
    """Vista de merma agrupada por orden, con desglose por línea."""
    fecha_inicio_str = request.args.get('fecha_inicio')
    fecha_fin_str = request.args.get('fecha_fin')
    order_num = request.args.get('order_num', '').strip()
    producto_id = request.args.get('producto_id', type=int)

    hoy = datetime.utcnow()
    if fecha_inicio_str:
        try:
            fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d')
        except Exception:
            fecha_inicio = hoy - timedelta(days=30)
    else:
        fecha_inicio = hoy - timedelta(days=30)

    if fecha_fin_str:
        try:
            fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d') + timedelta(days=1)
        except Exception:
            fecha_fin = hoy + timedelta(days=1)
    else:
        fecha_fin = hoy + timedelta(days=1)

    query = ArchivoAdjunto.query.join(Order, ArchivoAdjunto.orden_id == Order.id).filter(
        Order.date >= fecha_inicio.date(),
        Order.date < fecha_fin.date(),
        ArchivoAdjunto.parametros_etiqueta.isnot(None)
    )

    if order_num:
        query = query.filter(Order.order_num.ilike(f'%{order_num}%'))
    if producto_id:
        query = query.filter(ArchivoAdjunto.producto_id == producto_id)

    archivos = query.all()

    ordenes = {}
    for a in archivos:
        try:
            params = json.loads(a.parametros_etiqueta) if a.parametros_etiqueta else {}
        except Exception:
            continue
        if 'merma_operativa_m2' not in params:
            continue
        orden = a.orden
        if not orden:
            continue
        key = orden.id
        if key not in ordenes:
            ordenes[key] = {
                'orden_id': orden.id,
                'orden_num': orden.order_num or 'Sin número',
                'cliente': orden.client.nombre if orden.client else 'Sin cliente',
                'fecha': orden.date,
                'estado': orden.column,
                'lineas': [],
                'total_area_m2': 0.0,
                'total_material_m2': 0.0,
                'total_merma_m2': 0.0,
            }
        ordenes[key]['lineas'].append({
            'archivo_id': a.id,
            'nombre': a.nombre_visible,
            'producto': a.producto.nombre if a.producto else '—',
            'producto_id': a.producto_id,
            'area_m2': float(params.get('area_m2', 0) or 0),
            'material_m2': float(params.get('material_consumido_m2', 0) or 0),
            'merma_m2': float(params.get('merma_operativa_m2', 0) or 0),
            'merma_pct': float(params.get('merma_operativa_pct', 0) or 0),
            'ancho_cm': params.get('ancho', '—'),
            'alto_cm': params.get('alto', '—'),
            'n_paños': params.get('n_paños', 1),
            'filas': params.get('filas', 0),
            'columnas': params.get('columnas', 0),
            'largo_total_m': float(params.get('largo_total_m', 0) or 0),
            'largo_etiquetas_m': float(params.get('largo_etiquetas_m', 0) or 0),
            'largo_gaps_m': float(params.get('largo_gaps_m', 0) or 0),
            'largo_cut_m': float(params.get('largo_cut_m', 0) or 0),
            'gap_usado_cm': params.get('gap_usado_cm', 6.5),
            'desglose_paños': params.get('desglose_paños', []),
        })
        ordenes[key]['total_area_m2'] += float(params.get('area_m2', 0) or 0)
        ordenes[key]['total_material_m2'] += float(params.get('material_consumido_m2', 0) or 0)
        ordenes[key]['total_merma_m2'] += float(params.get('merma_operativa_m2', 0) or 0)

    ordenes_lista = sorted(ordenes.values(), key=lambda x: x['fecha'] or datetime.min, reverse=True)

    # Totales
    total_area = sum(o['total_area_m2'] for o in ordenes_lista)
    total_material = sum(o['total_material_m2'] for o in ordenes_lista)
    total_merma = sum(o['total_merma_m2'] for o in ordenes_lista)
    pct_global = (total_merma / total_area * 100) if total_area > 0 else 0

    productos = Producto.query.filter(
        Producto.es_material_impresion == True
    ).order_by(Producto.nombre).all()

    return render_template('merma_por_orden.html',
                           ordenes=ordenes_lista,
                           productos=productos,
                           producto_seleccionado=producto_id,
                           order_num=order_num,
                           fecha_inicio=fecha_inicio.strftime('%Y-%m-%d'),
                           fecha_fin=(fecha_fin - timedelta(days=1)).strftime('%Y-%m-%d'),
                           total_area=round(total_area, 2),
                           total_material=round(total_material, 2),
                           total_merma=round(total_merma, 2),
                           pct_global=round(pct_global, 2))