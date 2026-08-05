from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import login_required, current_user
from app.models import Producto, Movimiento, Order, OrdenProducto, Categoria
from app import db
from datetime import datetime, timedelta, date
from sqlalchemy import func
import io
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill
from werkzeug.utils import secure_filename
import os
import tempfile
import json
import math

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
            return redirect(url_for('home.home'))
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
# GESTIÓN DE CATEGORÍAS (solo admin)
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
        if not nombre:
            flash('El nombre de la categoría es obligatorio.', 'danger')
            return render_template('form_categoria.html')
        if Categoria.query.filter_by(nombre=nombre).first():
            flash('Ya existe una categoría con ese nombre.', 'danger')
            return render_template('form_categoria.html')
        cat = Categoria(nombre=nombre, descripcion=descripcion)
        db.session.add(cat)
        db.session.commit()
        flash(f'Categoría "{nombre}" creada correctamente.', 'success')
        return redirect(url_for('inventario.listar_categorias'))
    return render_template('form_categoria.html')

@inventario_bp.route('/categoria/editar/<int:categoria_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_categoria(categoria_id):
    cat = Categoria.query.get_or_404(categoria_id)
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        if not nombre:
            flash('El nombre es obligatorio.', 'danger')
            return render_template('form_categoria.html', categoria=cat)
        existente = Categoria.query.filter(Categoria.nombre == nombre, Categoria.id != cat.id).first()
        if existente:
            flash('Ya existe otra categoría con ese nombre.', 'danger')
            return render_template('form_categoria.html', categoria=cat)
        cat.nombre = nombre
        cat.descripcion = descripcion
        db.session.commit()
        flash('Categoría actualizada.', 'success')
        return redirect(url_for('inventario.listar_categorias'))
    return render_template('form_categoria.html', categoria=cat)

@inventario_bp.route('/categoria/eliminar/<int:categoria_id>', methods=['POST'])
@login_required
@admin_required
def eliminar_categoria(categoria_id):
    cat = Categoria.query.get_or_404(categoria_id)
    if Producto.query.filter_by(categoria_id=cat.id).first():
        flash('No se puede eliminar una categoría con productos asociados.', 'danger')
        return redirect(url_for('inventario.listar_categorias'))
    db.session.delete(cat)
    db.session.commit()
    flash('Categoría eliminada.', 'success')
    return redirect(url_for('inventario.listar_categorias'))

# ==========================================
# LISTADO DE PRODUCTOS
# ==========================================
@inventario_bp.route('/')
@login_required
@economico_or_admin_required
def index():
    categoria_id = request.args.get('categoria', type=int)
    search = request.args.get('search', '').strip()
    query = Producto.query
    if categoria_id:
        query = query.filter_by(categoria_id=categoria_id)
    if search:
        query = query.filter(Producto.nombre.ilike(f'%{search}%'))
    productos = query.order_by(Producto.nombre).all()
    categorias = Categoria.query.order_by(Categoria.nombre).all()
    return render_template('inventario.html', productos=productos, categorias=categorias, categoria_seleccionada=categoria_id, search=search)

# ==========================================
# CREAR PRODUCTO
# ==========================================
@inventario_bp.route('/crear', methods=['GET', 'POST'])
@login_required
@economico_or_admin_required
def crear_producto():
    categorias = Categoria.query.order_by(Categoria.nombre).all()
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        tipo = request.form.get('tipo', '').strip()
        ubicacion = request.form.get('ubicacion', '').strip()
        unidad = request.form.get('unidad', '').strip()
        costo = request.form.get('costo', type=float, default=0.0)
        stock = request.form.get('stock', type=float, default=0.0)
        stock_minimo = request.form.get('stock_minimo', type=float, default=0.0)
        categoria_id = request.form.get('categoria_id', type=int)
        ancho_rollo = request.form.get('ancho_rollo', type=float)
        largo_rollo = request.form.get('largo_rollo', type=float)
        fecha_vencimiento = request.form.get('fecha_vencimiento', '')

        if not nombre:
            flash('El nombre es obligatorio.', 'danger')
            return render_template('form_producto.html', categorias=categorias)

        if Producto.query.filter_by(nombre=nombre).first():
            flash('Ya existe un producto con ese nombre.', 'danger')
            return render_template('form_producto.html', categorias=categorias)

        producto = Producto(
            nombre=nombre,
            tipo=tipo,
            ubicacion=ubicacion,
            unidad=unidad,
            costo=costo,
            stock=stock,
            stock_minimo=stock_minimo,
            categoria_id=categoria_id if categoria_id else None,
            ancho_rollo=ancho_rollo,
            largo_rollo=largo_rollo
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
                comentario='Stock inicial',
                usuario_id=current_user.id
            )
            db.session.add(movimiento)
            db.session.commit()

        flash(f'Producto "{nombre}" creado correctamente.', 'success')
        return redirect(url_for('inventario.detalle_producto', producto_id=producto.id))

    return render_template('form_producto.html', categorias=categorias)

# ==========================================
# EDITAR PRODUCTO
# ==========================================
@inventario_bp.route('/editar/<int:producto_id>', methods=['GET', 'POST'])
@login_required
@economico_or_admin_required
def editar_producto(producto_id):
    producto = Producto.query.get_or_404(producto_id)
    categorias = Categoria.query.order_by(Categoria.nombre).all()
    if request.method == 'POST':
        producto.nombre = request.form.get('nombre', '').strip()
        producto.tipo = request.form.get('tipo', '').strip()
        producto.ubicacion = request.form.get('ubicacion', '').strip()
        producto.unidad = request.form.get('unidad', '').strip()
        producto.costo = request.form.get('costo', type=float, default=0.0)
        producto.stock_minimo = request.form.get('stock_minimo', type=float, default=0.0)
        producto.categoria_id = request.form.get('categoria_id', type=int) or None
        producto.ancho_rollo = request.form.get('ancho_rollo', type=float)
        producto.largo_rollo = request.form.get('largo_rollo', type=float)
        fecha_vencimiento = request.form.get('fecha_vencimiento', '')
        if fecha_vencimiento:
            try:
                producto.fecha_vencimiento = datetime.strptime(fecha_vencimiento, '%Y-%m-%d').date()
            except:
                producto.fecha_vencimiento = None
        else:
            producto.fecha_vencimiento = None

        db.session.commit()
        flash(f'Producto "{producto.nombre}" actualizado.', 'success')
        return redirect(url_for('inventario.detalle_producto', producto_id=producto.id))

    return render_template('form_producto.html', producto=producto, categorias=categorias)

# ==========================================
# ELIMINAR PRODUCTO
# ==========================================
@inventario_bp.route('/eliminar/<int:producto_id>', methods=['POST'])
@login_required
@economico_or_admin_required
def eliminar_producto(producto_id):
    producto = Producto.query.get_or_404(producto_id)
    if Movimiento.query.filter_by(producto_id=producto.id).first():
        flash('No se puede eliminar un producto con movimientos.', 'danger')
        return redirect(url_for('inventario.detalle_producto', producto_id=producto.id))
    if OrdenProducto.query.filter_by(producto_id=producto.id).first():
        flash('No se puede eliminar un producto asociado a órdenes.', 'danger')
        return redirect(url_for('inventario.detalle_producto', producto_id=producto.id))
    nombre = producto.nombre
    db.session.delete(producto)
    db.session.commit()
    flash(f'Producto "{nombre}" eliminado.', 'success')
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
    flash('Compra registrada.', 'success')
    return redirect(url_for('inventario.detalle_producto', producto_id=producto.id))

# ==========================================
# REGISTRAR AJUSTE
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
# OBTENER MOVIMIENTOS (AJAX)
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

# ==========================================
# EXPORTAR PRODUCTOS A EXCEL
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
            query = query.filter_by(categoria_id=categoria_id)
        productos = query.order_by(Producto.nombre).all()

        mapa_columnas = {
            'id': 'id',
            'nombre': 'nombre',
            'tipo': 'tipo',
            'ubicacion': 'ubicacion',
            'unidad': 'unidad',
            'costo': 'costo',
            'stock': 'stock',
            'stock_minimo': 'stock_minimo',
            'stock_comprometido': 'stock_comprometido',
            'fecha_vencimiento': 'fecha_vencimiento',
            'categoria': 'categoria.nombre',
            'ancho_rollo': 'ancho_rollo',
            'largo_rollo': 'largo_rollo',
            'created_at': 'created_at'
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
                        rel, field = attr.split('.')
                        obj = getattr(prod, rel)
                        valor = getattr(obj, field) if obj else None
                    else:
                        valor = getattr(prod, attr)
                    # CORRECCIÓN DE FECHAS
                    if isinstance(valor, datetime):
                        valor = valor.strftime('%Y-%m-%d %H:%M')
                    elif isinstance(valor, date):
                        valor = valor.strftime('%Y-%m-%d')
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

    categorias = Categoria.query.order_by(Categoria.nombre).all()
    columnas_disponibles = [
        {'id': 'id', 'label': 'ID'},
        {'id': 'nombre', 'label': 'Nombre'},
        {'id': 'tipo', 'label': 'Tipo'},
        {'id': 'ubicacion', 'label': 'Ubicación'},
        {'id': 'unidad', 'label': 'Unidad'},
        {'id': 'costo', 'label': 'Costo'},
        {'id': 'stock', 'label': 'Stock'},
        {'id': 'stock_minimo', 'label': 'Stock Mínimo'},
        {'id': 'stock_comprometido', 'label': 'Stock Comprometido'},
        {'id': 'fecha_vencimiento', 'label': 'Fecha Vencimiento'},
        {'id': 'categoria', 'label': 'Categoría'},
        {'id': 'ancho_rollo', 'label': 'Ancho Rollo (m)'},
        {'id': 'largo_rollo', 'label': 'Largo Rollo (m)'},
        {'id': 'created_at', 'label': 'Fecha Creación'}
    ]
    return render_template('exportar_productos.html', columnas=columnas_disponibles, categorias=categorias)

# ==========================================
# IMPORTAR PRODUCTOS DESDE EXCEL
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
                elif 'tipo' in h_clean:
                    col_map['tipo'] = idx
                elif 'ubicacion' in h_clean:
                    col_map['ubicacion'] = idx
                elif 'unidad' in h_clean:
                    col_map['unidad'] = idx
                elif 'costo' in h_clean:
                    col_map['costo'] = idx
                elif 'stock' in h_clean and 'minimo' not in h_clean and 'comprometido' not in h_clean:
                    col_map['stock'] = idx
                elif 'stock_minimo' in h_clean or 'minimo' in h_clean:
                    col_map['stock_minimo'] = idx
                elif 'stock_comprometido' in h_clean or 'comprometido' in h_clean:
                    col_map['stock_comprometido'] = idx
                elif 'vencimiento' in h_clean:
                    col_map['fecha_vencimiento'] = idx
                elif 'categoria' in h_clean:
                    col_map['categoria'] = idx
                elif 'ancho_rollo' in h_clean or 'ancho' in h_clean:
                    col_map['ancho_rollo'] = idx
                elif 'largo_rollo' in h_clean or 'largo' in h_clean:
                    col_map['largo_rollo'] = idx

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
                    if col_map.get('tipo') is not None and row[col_map['tipo']]:
                        producto.tipo = str(row[col_map['tipo']]).strip()
                    if col_map.get('ubicacion') is not None and row[col_map['ubicacion']]:
                        producto.ubicacion = str(row[col_map['ubicacion']]).strip()
                    if col_map.get('unidad') is not None and row[col_map['unidad']]:
                        producto.unidad = str(row[col_map['unidad']]).strip()
                    if col_map.get('costo') is not None and row[col_map['costo']]:
                        try:
                            producto.costo = float(str(row[col_map['costo']]).replace(',', ''))
                        except:
                            pass
                    if col_map.get('stock') is not None and row[col_map['stock']]:
                        try:
                            producto.stock = float(str(row[col_map['stock']]).replace(',', ''))
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
                    if col_map.get('fecha_vencimiento') is not None and row[col_map['fecha_vencimiento']]:
                        try:
                            val = row[col_map['fecha_vencimiento']]
                            if isinstance(val, datetime):
                                producto.fecha_vencimiento = val.date()
                            elif isinstance(val, (int, float)):
                                from datetime import date
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
                    if col_map.get('categoria') is not None and row[col_map['categoria']]:
                        cat_nombre = str(row[col_map['categoria']]).strip()
                        if cat_nombre:
                            cat = Categoria.query.filter_by(nombre=cat_nombre).first()
                            if not cat:
                                cat = Categoria(nombre=cat_nombre)
                                db.session.add(cat)
                                db.session.flush()
                            producto.categoria_id = cat.id
                    producto.updated_at = datetime.now()
                    actualizados += 1
                else:
                    nuevo = Producto(nombre=nombre)
                    if col_map.get('tipo') is not None and row[col_map['tipo']]:
                        nuevo.tipo = str(row[col_map['tipo']]).strip()
                    if col_map.get('ubicacion') is not None and row[col_map['ubicacion']]:
                        nuevo.ubicacion = str(row[col_map['ubicacion']]).strip()
                    if col_map.get('unidad') is not None and row[col_map['unidad']]:
                        nuevo.unidad = str(row[col_map['unidad']]).strip()
                    if col_map.get('costo') is not None and row[col_map['costo']]:
                        try:
                            nuevo.costo = float(str(row[col_map['costo']]).replace(',', ''))
                        except:
                            pass
                    if col_map.get('stock') is not None and row[col_map['stock']]:
                        try:
                            nuevo.stock = float(str(row[col_map['stock']]).replace(',', ''))
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
                    if col_map.get('fecha_vencimiento') is not None and row[col_map['fecha_vencimiento']]:
                        try:
                            val = row[col_map['fecha_vencimiento']]
                            if isinstance(val, datetime):
                                nuevo.fecha_vencimiento = val.date()
                            elif isinstance(val, (int, float)):
                                from datetime import date
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
                    if col_map.get('categoria') is not None and row[col_map['categoria']]:
                        cat_nombre = str(row[col_map['categoria']]).strip()
                        if cat_nombre:
                            cat = Categoria.query.filter_by(nombre=cat_nombre).first()
                            if not cat:
                                cat = Categoria(nombre=cat_nombre)
                                db.session.add(cat)
                                db.session.flush()
                            nuevo.categoria_id = cat.id
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
# EXPORTAR MOVIMIENTOS
# ==========================================
@inventario_bp.route('/exportar_movimientos', methods=['GET', 'POST'])
@login_required
@economico_or_admin_required
def exportar_movimientos():
    if request.method == 'POST':
        fecha_inicio = request.form.get('fecha_inicio')
        fecha_fin = request.form.get('fecha_fin')
        producto_id = request.form.get('producto_id', type=int)
        try:
            if fecha_inicio:
                fecha_inicio = datetime.strptime(fecha_inicio, '%Y-%m-%d')
            else:
                fecha_inicio = datetime.now() - timedelta(days=30)
            if fecha_fin:
                fecha_fin = datetime.strptime(fecha_fin, '%Y-%m-%d') + timedelta(days=1)
            else:
                fecha_fin = datetime.now() + timedelta(days=1)
        except:
            flash('Formato de fecha inválido.', 'danger')
            return redirect(url_for('inventario.exportar_movimientos'))

        query = Movimiento.query.filter(Movimiento.fecha >= fecha_inicio, Movimiento.fecha <= fecha_fin)
        if producto_id:
            query = query.filter_by(producto_id=producto_id)
        movimientos = query.order_by(Movimiento.fecha).all()

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Movimientos'

        headers = ['ID', 'Producto', 'Tipo', 'Cantidad', 'Fecha', 'Comentario', 'Orden']
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal='center')
            cell.fill = PatternFill(start_color='D3D3D3', end_color='D3D3D3', fill_type='solid')

        for row_idx, mov in enumerate(movimientos, 2):
            ws.cell(row=row_idx, column=1, value=mov.id)
            ws.cell(row=row_idx, column=2, value=mov.producto.nombre if mov.producto else '')
            ws.cell(row=row_idx, column=3, value=mov.tipo)
            ws.cell(row=row_idx, column=4, value=mov.cantidad)
            ws.cell(row=row_idx, column=5, value=mov.fecha.strftime('%Y-%m-%d %H:%M') if mov.fecha else '')
            ws.cell(row=row_idx, column=6, value=mov.comentario or '')
            ws.cell(row=row_idx, column=7, value=mov.orden.order_num if mov.orden else '')

        for col in range(1, len(headers)+1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 18

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return send_file(output,
                         as_attachment=True,
                         download_name=f'movimientos_{datetime.now().strftime("%Y%m%d")}.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    productos = Producto.query.order_by(Producto.nombre).all()
    fecha_inicio_defecto = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    fecha_fin_defecto = datetime.now().strftime('%Y-%m-%d')
    return render_template('exportar_movimientos.html', productos=productos,
                           fecha_inicio_defecto=fecha_inicio_defecto,
                           fecha_fin_defecto=fecha_fin_defecto)