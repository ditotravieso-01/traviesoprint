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
# CONSTANTES DE COLUMNAS
# ==========================================
COLUMNAS_NOMBRES = {
    'pendiente': 'Pendiente',
    'por-preparar': 'Por preparar',
    'preparados': 'Preparados',
    'imprimir-hoy': 'Imprimir hoy',
    'impreso-corte': 'Impreso y corte',
    'listo': 'Listo',
    'entregados': 'Entregados'
}

# ==========================================
# CONSTANTES DE IMPRESIÓN
# ==========================================
MARGEN_MESA_M = 0.002       # 2 mm por etiqueta (margen de mesa)
CUT_LARGO_M = 0.04          # 4 cm de cut mark de alto (por cada paño)
GAP_PAÑOS_DEFAULT_CM = 6.5  # cm de gap entre paños por defecto

# ==========================================
# DECORADORES DE PERMISOS
# ==========================================

def comercial_or_admin_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if current_user.role not in ['comercial', 'admin']:
            flash('No tienes permiso.', 'danger')
            return redirect(url_for('home.index'))
        return func(*args, **kwargs)
    return wrapper

def view_orders_or_admin_comercial_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if current_user.role not in ['comercial', 'admin', 'economico']:
            flash('No tienes permiso.', 'danger')
            return redirect(url_for('home.index'))
        return func(*args, **kwargs)
    return wrapper

# ==========================================
# FUNCIÓN AUXILIAR: CÁLCULO DE MERMA OPERATIVA
# ==========================================
def calcular_merma_operativa(area_facturada, ancho_util_efectivo, ancho_real,
                              gap_panno_cm, alto_cell_m, columnas,
                              filas_minimas=None):
    """
    Fórmula Opción C (por paño con acumulación de aire).

    Modo m² (filas_minimas=None):
        - n_paños = ceil(area_facturada)
        - Cada paño toma 1 m² (el último puede ser menor)
        - Se imprimen tantas filas como caben

    Modo unidades (filas_minimas=int):
        - Se imprimen AL MENOS filas_minimas filas (completar última línea)
        - n_paños = ceil(filas_minimas / filas_por_paño_max)
        - El último paño se ajusta exactamente a las filas restantes
        - area_facturada final se recalcula basándose en las filas reales

    Retorna dict con parámetros de merma y desglose.
    """
    gap_m = (gap_panno_cm if gap_panno_cm is not None else GAP_PAÑOS_DEFAULT_CM) / 100.0
    ancho_util = ancho_util_efectivo if ancho_util_efectivo and ancho_util_efectivo > 0 else 1.30
    ancho_r = ancho_real or 1.34

    # Filas máximas que caben en 1 paño (1 m²)
    filas_por_paño_max = int((1.0 / ancho_util) / alto_cell_m) if alto_cell_m > 0 else 0
    if filas_por_paño_max <= 0:
        filas_por_paño_max = 1

    if filas_minimas is not None:
        # MODO UNIDADES
        modo = 'unidades'
        filas_minimas = max(1, int(filas_minimas))
        n_paños = max(1, math.ceil(filas_minimas / filas_por_paño_max))

        # Recalcular área facturada basándose en filas_minimas
        paños_completos = filas_minimas // filas_por_paño_max
        filas_restantes = filas_minimas % filas_por_paño_max
        area_facturada_calc = float(paños_completos)
        if filas_restantes > 0:
            # Área del último paño: justo lo necesario para las filas restantes
            area_ultimo = filas_restantes * alto_cell_m * ancho_util
            area_facturada_calc += area_ultimo
        area_facturada = area_facturada_calc
    else:
        # MODO m²
        modo = 'm2'
        n_paños = max(1, math.ceil(area_facturada))
        filas_minimas = None

    filas_totales = 0
    largo_etiquetas_total = 0.0
    material_total = 0.0
    area_restante = area_facturada
    area_facturada_real = 0.0
    sobrante_acumulado = 0.0
    desglose_paños = []

    for i in range(n_paños):
        if modo == 'unidades':
            filas_restantes_ahora = filas_minimas - filas_totales
            if filas_restantes_ahora <= 0:
                break
            if filas_restantes_ahora <= filas_por_paño_max:
                # Último paño: área justa para las filas restantes
                area_paño = filas_restantes_ahora * alto_cell_m * ancho_util
            else:
                area_paño = 1.0
        else:
            area_paño = min(1.0, area_restante)
            area_restante -= area_paño

        area_facturada_real += area_paño

        largo_nominal_paño = area_paño / ancho_util if ancho_util > 0 else 0
        filas_paño = int(largo_nominal_paño / alto_cell_m) if alto_cell_m > 0 else 0

        # En modo unidades: forzar que el último paño tenga exactamente las filas restantes
        if modo == 'unidades':
            filas_restantes_antes = filas_minimas - filas_totales
            if filas_paño > filas_restantes_antes:
                filas_paño = filas_restantes_antes

        largo_etiq_paño = filas_paño * alto_cell_m
        aire_paño = max(0.0, largo_nominal_paño - largo_etiq_paño)
        aire_total_paño = aire_paño + sobrante_acumulado

        gap_efectivo_paño = max(0.0, gap_m - aire_total_paño)
        sobrante_acumulado = max(0.0, aire_total_paño - gap_m)

        largo_avance_paño = largo_etiq_paño + CUT_LARGO_M + gap_efectivo_paño
        material_paño = largo_avance_paño * ancho_r

        filas_totales += filas_paño
        largo_etiquetas_total += largo_etiq_paño
        material_total += material_paño

        desglose_paños.append({
            'n': i + 1,
            'area_m2': round(area_paño, 4),
            'filas': filas_paño,
            'largo_nominal_m': round(largo_nominal_paño, 4),
            'largo_etiquetas_m': round(largo_etiq_paño, 4),
            'aire_paño_mm': round(aire_paño * 1000, 1),
            'sobrante_entrada_mm': round((aire_total_paño - aire_paño) * 1000, 1),
            'aire_total_mm': round(aire_total_paño * 1000, 1),
            'gap_original_mm': round(gap_m * 1000, 1),
            'gap_efectivo_mm': round(gap_efectivo_paño * 1000, 1),
            'cut_mm': round(CUT_LARGO_M * 1000, 1),
            'largo_avance_m': round(largo_avance_paño, 4),
            'material_paño_m2': round(material_paño, 4),
            'sobrante_salida_mm': round(sobrante_acumulado * 1000, 1),
        })

        if modo == 'unidades' and filas_totales >= filas_minimas:
            break

    # Área facturada final (para modo unidades, la suma real; para modo m², la original)
    if modo == 'unidades':
        area_facturada_final = area_facturada_real
    else:
        area_facturada_final = area_facturada

    largo_gaps_total = n_paños * gap_m
    largo_cut_total = n_paños * CUT_LARGO_M
    largo_total = material_total / ancho_r
    largo_sin_aire = largo_etiquetas_total + largo_gaps_total + largo_cut_total

    merma_m2 = material_total - area_facturada_final
    merma_pct = (merma_m2 / area_facturada_final * 100) if area_facturada_final > 0 else 0

    return {
        'modo': modo,
        'gap_usado_cm': round(gap_m * 100, 2),
        'gap_m': round(gap_m, 4),
        'cut_largo_m': CUT_LARGO_M,
        'n_paños': len(desglose_paños),
        'largo_gaps_m': round(largo_gaps_total, 4),
        'largo_cut_m': round(largo_cut_total, 4),
        'largo_sin_aire_m': round(largo_sin_aire, 4),
        'largo_nominal_m': round(area_facturada_final / ancho_util, 4),
        'filas': filas_totales,
        'filas_por_paño_max': filas_por_paño_max,
        'columnas': columnas,
        'n_etiquetas': filas_totales * columnas,
        'largo_etiquetas_m': round(largo_etiquetas_total, 4),
        'largo_total_m': round(largo_total, 4),
        'area_facturada_m2': round(area_facturada_final, 4),
        'material_consumido_m2': round(material_total, 4),
        'merma_operativa_m2': round(merma_m2, 4),
        'merma_operativa_pct': round(merma_pct, 2),
        'desglose_paños': desglose_paños,
    }

# ==========================================
# CONTEXTO DEL FORMULARIO
# ==========================================
def _get_form_context(form_data=None, edit=False, order=None):
    servicios_disponibles = ['Diseño', 'Rúter', 'Láser', 'Montaje', 'Herrería']
    clients_list = Client.query.order_by(Client.nombre).all()
    clients_data = [{'id': c.id, 'nombre': c.nombre, 'referencia': c.referencia, 'telefono': c.telefono} for c in clients_list]
    todos_usuarios = User.query.filter_by(is_active=True).order_by(User.username).all()
    productos = Producto.query.filter(
        Producto.stock > 0,
        Producto.es_material_impresion == True,
        Producto.largo_rollo > 0
    ).order_by(Producto.nombre).all()
    productos_data = [
        {
            'id': p.id,
            'nombre': p.nombre,
            'unidad': p.unidad,
            'stock': round(p.stock, 2) if p.stock else 0,
            'stock_metros': round(p.stock_metros, 2) if p.stock_metros else 0,
            'ancho_rollo': p.ancho_rollo,
            'largo_rollo': p.largo_rollo,
            'gap_panno_cm': p.gap_panno_cm if p.gap_panno_cm is not None else GAP_PAÑOS_DEFAULT_CM,
            'es_material_impresion': p.es_material_impresion
        }
        for p in productos
    ]
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
    estado = request.args.get('estado', '').strip()
    search = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 20

    query = Order.query

    if estado and estado in COLUMNAS_NOMBRES:
        query = query.filter_by(column=estado)
    if search:
        search_like = f'%{search}%'
        query = query.filter(
            db.or_(
                Order.order_num.ilike(search_like),
                Order.proyecto.ilike(search_like),
                Order.client.has(Client.nombre.ilike(search_like))
            )
        )

    paginated = query.order_by(Order.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    orders = paginated.items
    total = paginated.total
    total_pages = paginated.pages

    all_orders = query.all()
    total_ordenes = len(all_orders)
    pendientes = sum(1 for o in all_orders if not o.entrada_ok or o.column in ['pendiente', 'por-preparar', 'preparados'])
    completadas = sum(1 for o in all_orders if o.column in ['entregados', 'listo'])
    facturacion_total = sum(getattr(o, 'total_facturado', 0) or 0 for o in all_orders)
    inicio_mes = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    nuevas_ordenes_mes = sum(1 for o in all_orders if o.created_at and o.created_at >= inicio_mes)

    return render_template('list_ordenes.html',
                           orders=orders,
                           columnas_nombres=COLUMNAS_NOMBRES,
                           total_ordenes=total_ordenes,
                           pendientes=pendientes,
                           completadas=completadas,
                           facturacion_total=facturacion_total,
                           nuevas_ordenes_mes=nuevas_ordenes_mes,
                           page=page,
                           per_page=per_page,
                           total=total,
                           total_pages=total_pages,
                           search=search,
                           estado=estado)

# ==========================================
# DETALLE DE ORDEN
# ==========================================
@ordenes_bp.route('/detalle/<int:order_id>')
@login_required
def detalle_order(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template('detalle_orden.html',
                           order=order,
                           now=datetime.now(),
                           columnas_nombres=COLUMNAS_NOMBRES)

# ==========================================
# GUARDAR ARCHIVO
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
# CONSUMIR MATERIALES
# ==========================================
def consumir_materiales(orden_id):
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

        producto.stock = producto.stock or 0.0
        producto.stock_metros = producto.stock_metros or 0.0
        producto.stock_comprometido = producto.stock_comprometido or 0.0
        producto.stock_comprometido_metros = producto.stock_comprometido_metros or 0.0

        if producto.largo_rollo and producto.largo_rollo > 0:
            consumo_metros = item.cantidad_estimada or 0.0
            if consumo_metros <= 0:
                return False, f"Consumo estimado cero para {producto.nombre}"
            consumo_unidades = consumo_metros / producto.largo_rollo
            if producto.stock_metros < consumo_metros:
                return False, f"Stock insuficiente en metros para {producto.nombre} (disponible: {producto.stock_metros:.2f}, necesario: {consumo_metros:.2f})"
            producto.stock_metros -= consumo_metros
            producto.stock_comprometido_metros = max(0.0, producto.stock_comprometido_metros - consumo_metros)
            producto.stock -= consumo_unidades
            producto.stock_comprometido = max(0.0, producto.stock_comprometido - consumo_unidades)
        else:
            consumo_unidades = item.cantidad_estimada or 0.0
            if consumo_unidades <= 0:
                return False, f"Consumo estimado cero para {producto.nombre}"
            if producto.stock < consumo_unidades:
                return False, f"Stock insuficiente para {producto.nombre} (disponible: {producto.stock:.2f}, necesario: {consumo_unidades:.2f})"
            producto.stock -= consumo_unidades
            producto.stock_comprometido = max(0.0, producto.stock_comprometido - consumo_unidades)
            consumo_metros = 0.0

        movimiento = Movimiento(
            producto_id=producto.id,
            tipo='consumo',
            cantidad=consumo_unidades,
            cantidad_metros=consumo_metros,
            comentario=f'Consumo para orden {order.order_num or "sin número"}',
            orden_id=order.id,
            usuario_id=current_user.id if hasattr(current_user, 'id') else None
        )
        db.session.add(movimiento)
        item.cantidad_real = consumo_unidades

    db.session.commit()
    return True, "Materiales consumidos correctamente"

# ==========================================
# PROCESAR LÍNEA DE ETIQUETAS (helper común)
# ==========================================
def _procesar_linea_etiqueta(
    order, producto, ancho_cm, alto_cm, precio, mesa, girar, auto_girar,
    unidad, cantidad_original, ancho_util_override, nombre_visible,
    order_num_para_comentario
):
    """
    Calcula layout + merma, crea ArchivoAdjunto, OrdenProducto y Movimiento de reserva.
    Retorna (adjunto, op, mov, error_msg). Si error_msg no es None, no se guardó nada.
    """
    ancho_real = producto.ancho_rollo or 1.34
    ancho_util_efectivo = ancho_util_override if ancho_util_override else ancho_real

    if ancho_util_efectivo > ancho_real + 0.001:
        return None, None, None, (
            f'El ancho útil ({ancho_util_efectivo:.2f} m) no puede ser mayor '
            f'que el ancho real del rollo ({ancho_real:.2f} m).'
        )

    from app.modulos.etiquetas import calcular_datos
    if unidad == 'unidades':
        cantidad_str_calc = str(cantidad_original) if cantidad_original else '0'
        area_str_calc = ''
    else:
        area_str_calc = str(cantidad_original) if cantidad_original else ''
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
        ancho_rollo_m=ancho_util_efectivo
    )
    if calculo['error']:
        return None, None, None, calculo['error']

    simData = calculo['simData']
    columnas = simData.get('columnas', 1)

    # ═══════════════════════════════════════════════════════════
    # DETECCIÓN DE ROTACIÓN
    # ═══════════════════════════════════════════════════════════
    ancho_columna_efectivo = ancho_util_efectivo / columnas if columnas > 0 else 0
    diff_unrotado = abs(ancho_columna_efectivo - (ancho_cm / 100.0))
    diff_rotado = abs(ancho_columna_efectivo - (alto_cm / 100.0))
    es_rotado = diff_rotado < diff_unrotado

    if es_rotado:
        alto_cell_m = (ancho_cm / 100.0) + MARGEN_MESA_M
    else:
        alto_cell_m = (alto_cm / 100.0) + MARGEN_MESA_M

    gap_cm = producto.gap_panno_cm if producto.gap_panno_cm is not None else GAP_PAÑOS_DEFAULT_CM

    # ═══════════════════════════════════════════════════════════
    # CÁLCULO DE FILAS MÍNIMAS (solo en modo unidades)
    # ═══════════════════════════════════════════════════════════
    filas_minimas = None
    if unidad == 'unidades' and cantidad_original and columnas > 0:
        filas_minimas = math.ceil(cantidad_original / columnas)

    # Área facturada inicial
    area_total_inicial = simData['areaTotal']

    merma_data = calcular_merma_operativa(
        area_facturada=area_total_inicial,
        ancho_util_efectivo=ancho_util_efectivo,
        ancho_real=ancho_real,
        gap_panno_cm=gap_cm,
        alto_cell_m=alto_cell_m,
        columnas=columnas,
        filas_minimas=filas_minimas
    )

    area_total = merma_data['area_facturada_m2']
    consumo_reserva = merma_data['largo_total_m']

    if consumo_reserva <= 0:
        return None, None, None, 'El consumo estimado es cero.'

    disponible_metros = producto.get_stock_metros_disponible()
    if consumo_reserva > disponible_metros:
        return None, None, None, (
            f'Stock insuficiente para "{producto.nombre}". '
            f'Disponible: {disponible_metros:.2f} m lineales, '
            f'requerido (con cut + gap): {consumo_reserva:.2f} m'
        )

    # Metadata del layout
    etiquetas_por_m2 = columnas * merma_data['filas']
    metros_completos = 0
    resto_etiquetas = 0
    if unidad == 'unidades' and cantidad_original and etiquetas_por_m2 > 0:
        metros_completos = int(cantidad_original // etiquetas_por_m2)
        resto = cantidad_original % etiquetas_por_m2
        if resto > 0:
            filas_extra = math.ceil(resto / columnas)
            resto_etiquetas = int(filas_extra * columnas)

    if ancho_util_efectivo == int(ancho_util_efectivo):
        tipo_rollo = f'{int(ancho_util_efectivo)}m'
    else:
        tipo_rollo = f'{ancho_util_efectivo:.2f}'.rstrip('0').rstrip('.') + 'm'

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
            'es_rotado': es_rotado,
            'filas_minimas': filas_minimas,
            'area_m2': area_total,
            'etiquetas_por_m2': etiquetas_por_m2,
            'costo_estimado': round(area_total, 2) * precio,
            'metros_completos': metros_completos,
            'resto_etiquetas': resto_etiquetas,
            'columnas': columnas,
            'filas': merma_data['filas'],
            'n_etiquetas': merma_data['n_etiquetas'],
            'consumo_lineal': merma_data['largo_total_m'],
            'consumo_base': merma_data['largo_nominal_m'],
            'ancho_util_usado': ancho_util_efectivo,
            'ancho_real_usado': ancho_real,
            # ===== MERMA OPERATIVA =====
            'gap_usado_cm': merma_data['gap_usado_cm'],
            'cut_largo_m': merma_data['cut_largo_m'],
            'n_paños': merma_data['n_paños'],
            'largo_gaps_m': merma_data['largo_gaps_m'],
            'largo_cut_m': merma_data['largo_cut_m'],
            'largo_etiquetas_m': merma_data['largo_etiquetas_m'],
            'largo_total_m': merma_data['largo_total_m'],
            'material_consumido_m2': merma_data['material_consumido_m2'],
            'merma_operativa_m2': merma_data['merma_operativa_m2'],
            'merma_operativa_pct': merma_data['merma_operativa_pct'],
        })
    )

    # Reserva de stock
    producto.stock_comprometido_metros = (producto.stock_comprometido_metros or 0) + consumo_reserva
    if producto.largo_rollo and producto.largo_rollo > 0:
        unidades_a_reservar = consumo_reserva / producto.largo_rollo
    else:
        unidades_a_reservar = consumo_reserva
    producto.stock_comprometido = (producto.stock_comprometido or 0) + unidades_a_reservar

    op = OrdenProducto(
        orden_id=order.id,
        producto_id=producto.id,
        cantidad_estimada=consumo_reserva
    )

    mov = Movimiento(
        producto_id=producto.id,
        tipo='reserva',
        cantidad=unidades_a_reservar,
        cantidad_metros=consumo_reserva,
        comentario=(
            f'Reserva para {order_num_para_comentario or "sin número"} — '
            f'{merma_data["n_paños"]} paño(s) · {merma_data["filas"]} filas × {columnas} col '
            f'= {merma_data["n_etiquetas"]} etiq · '
            f'largo etiq {merma_data["largo_etiquetas_m"]:.2f}m + '
            f'{merma_data["n_paños"]} gaps × {merma_data["gap_usado_cm"]}cm ({merma_data["largo_gaps_m"]:.2f}m) + '
            f'{merma_data["n_paños"]} cuts × 4cm ({merma_data["largo_cut_m"]:.2f}m) '
            f'→ {merma_data["largo_total_m"]:.2f}m · ancho útil {ancho_util_efectivo}m'
        ),
        orden_id=order.id,
        usuario_id=current_user.id
    )

    return adjunto, op, mov, None

# ==========================================
# LIBERAR RESERVA DE PRODUCTO
# ==========================================
def _liberar_reserva(producto, cantidad_metros):
    """Libera la reserva de stock de un producto."""
    if not producto or not cantidad_metros:
        return
    producto.stock_comprometido_metros = max(0, (producto.stock_comprometido_metros or 0) - cantidad_metros)
    if producto.largo_rollo and producto.largo_rollo > 0:
        unidades_a_liberar = cantidad_metros / producto.largo_rollo
    else:
        unidades_a_liberar = cantidad_metros
    producto.stock_comprometido = max(0, (producto.stock_comprometido or 0) - unidades_a_liberar)

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
                servicios.append(key[5:])
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
        ancho_util_override_list = request.form.getlist('ancho_util_override[]')

        for i, nombre_visible in enumerate(nombres_visibles):
            if not nombre_visible.strip():
                continue
            producto_id = int(productos_ids[i]) if i < len(productos_ids) and productos_ids[i] else None
            cantidad_str = cantidades[i] if i < len(cantidades) else ''
            unidad = unidades[i] if i < len(unidades) else 'm2'
            cantidad_original = None
            if cantidad_str.strip():
                try:
                    cantidad_original = float(cantidad_str)
                except ValueError:
                    cantidad_original = None
            proyecto_linea = proyectos_linea[i] if i < len(proyectos_linea) else 'otros'
            producto = Producto.query.get(producto_id) if producto_id else None

            ancho_util_override = None
            if i < len(ancho_util_override_list) and ancho_util_override_list[i].strip():
                try:
                    ancho_util_override = float(ancho_util_override_list[i].strip())
                except:
                    pass

            if proyecto_linea == 'etiquetas':
                if not producto:
                    flash(f'Línea {i+1}: Debes seleccionar un producto del inventario.', 'danger')
                    db.session.rollback()
                    context = _get_form_context(form_data=request.form, edit=False, order=None)
                    return render_template('form_orden.html', **context)
                if not producto.largo_rollo or producto.largo_rollo <= 0:
                    flash(f'Línea {i+1}: El producto "{producto.nombre}" no tiene largo de rollo definido.', 'danger')
                    db.session.rollback()
                    context = _get_form_context(form_data=request.form, edit=False, order=None)
                    return render_template('form_orden.html', **context)

                ancho_cm = float(ancho_etiqueta_list[i]) if i < len(ancho_etiqueta_list) and ancho_etiqueta_list[i] else 0
                alto_cm = float(alto_etiqueta_list[i]) if i < len(alto_etiqueta_list) and alto_etiqueta_list[i] else 0
                precio = float(precio_etiqueta_list[i]) if i < len(precio_etiqueta_list) and precio_etiqueta_list[i] else 10.0
                mesa = mesa_etiqueta_list[i] == '1' if i < len(mesa_etiqueta_list) else False
                girar = girar_etiqueta_list[i] == '1' if i < len(girar_etiqueta_list) else False
                auto_girar = auto_girar_etiqueta_list[i] == '1' if i < len(auto_girar_etiqueta_list) else False

                adjunto, op, mov, error = _procesar_linea_etiqueta(
                    order=order,
                    producto=producto,
                    ancho_cm=ancho_cm,
                    alto_cm=alto_cm,
                    precio=precio,
                    mesa=mesa,
                    girar=girar,
                    auto_girar=auto_girar,
                    unidad=unidad,
                    cantidad_original=cantidad_original,
                    ancho_util_override=ancho_util_override,
                    nombre_visible=nombre_visible,
                    order_num_para_comentario=order_num
                )
                if error:
                    flash(f'Línea {i+1}: {error}', 'danger')
                    db.session.rollback()
                    context = _get_form_context(form_data=request.form, edit=False, order=None)
                    return render_template('form_orden.html', **context)
                db.session.add(adjunto)
                db.session.add(op)
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
        enlace = url_for('ordenes.detalle_order', order_id=order.id, _external=True)
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
                servicios.append(key[5:])
        otros = request.form.get('servicios_otros', '').strip()
        if otros:
            servicios.append(f'Otros: {otros}')
        order.set_servicios(servicios)

        existing_ids = request.form.getlist('archivo_ids[]')
        ids_a_eliminar = request.form.getlist('eliminar_archivos[]')
        ancho_util_override_edit = request.form.getlist('ancho_util_override_edit[]')

        for archivo_id in ids_a_eliminar:
            archivo = ArchivoAdjunto.query.get(int(archivo_id))
            if archivo and archivo.orden_id == order.id:
                if archivo.producto_id and archivo.cantidad:
                    op = OrdenProducto.query.filter_by(orden_id=order.id, producto_id=archivo.producto_id).first()
                    producto = Producto.query.get(archivo.producto_id)
                    if op:
                        _liberar_reserva(producto, op.cantidad_estimada)
                        db.session.delete(op)
                    elif producto:
                        _liberar_reserva(producto, archivo.cantidad)
                db.session.delete(archivo)

        override_idx = 0
        for archivo_id in existing_ids:
            archivo = ArchivoAdjunto.query.get(int(archivo_id))
            if not archivo or archivo.orden_id != order.id:
                continue
            if str(archivo_id) in ids_a_eliminar:
                continue

            nombre_visible = request.form.get(f'nombre_visible_{archivo_id}', '').strip()
            cantidad_str = request.form.get(f'cantidad_{archivo_id}', '')
            unidad = request.form.get(f'unidad_{archivo_id}', 'm2')
            producto_id_nuevo = request.form.get(f'producto_{archivo_id}', type=int)
            producto_nuevo = Producto.query.get(producto_id_nuevo) if producto_id_nuevo else None
            cantidad_original = None
            if cantidad_str:
                try:
                    cantidad_original = float(cantidad_str)
                except ValueError:
                    cantidad_original = None

            ancho_util_override = None
            if override_idx < len(ancho_util_override_edit) and ancho_util_override_edit[override_idx].strip():
                try:
                    ancho_util_override = float(ancho_util_override_edit[override_idx].strip())
                except:
                    pass
            override_idx += 1

            producto_anterior = archivo.producto
            producto_anterior_id = archivo.producto_id
            params = archivo.get_parametros_etiqueta()
            is_etiqueta = params is not None

            if is_etiqueta:
                cambio_significativo = (
                    producto_id_nuevo != producto_anterior_id
                    or cantidad_original != archivo.cantidad
                )
                if cambio_significativo:
                    if producto_anterior and archivo.cantidad:
                        op_anterior = OrdenProducto.query.filter_by(orden_id=order.id, producto_id=producto_anterior_id).first()
                        if op_anterior:
                            _liberar_reserva(producto_anterior, op_anterior.cantidad_estimada)
                            db.session.delete(op_anterior)
                        else:
                            _liberar_reserva(producto_anterior, archivo.cantidad)

                    if not producto_nuevo:
                        db.session.delete(archivo)
                        continue

                    ancho_cm = params.get('ancho', 10)
                    alto_cm = params.get('alto', 10)
                    precio = params.get('precio', 10.0)
                    mesa = params.get('mesa', False)
                    girar = params.get('girar', False)
                    auto_girar = params.get('auto_girar', False)

                    adjunto_tmp, op_nuevo, mov, error = _procesar_linea_etiqueta(
                        order=order,
                        producto=producto_nuevo,
                        ancho_cm=ancho_cm,
                        alto_cm=alto_cm,
                        precio=precio,
                        mesa=mesa,
                        girar=girar,
                        auto_girar=auto_girar,
                        unidad=unidad,
                        cantidad_original=cantidad_original,
                        ancho_util_override=ancho_util_override,
                        nombre_visible=nombre_visible,
                        order_num_para_comentario=order_num
                    )
                    if error:
                        flash(error, 'danger')
                        db.session.rollback()
                        context = _get_form_context(form_data=request.form, edit=True, order=order)
                        return render_template('form_orden.html', **context)

                    archivo.nombre_visible = nombre_visible or archivo.nombre_visible
                    archivo.producto_id = producto_nuevo.id
                    archivo.material = producto_nuevo.nombre
                    archivo.cantidad = cantidad_original if cantidad_original else 0
                    archivo.unidad = unidad
                    archivo.parametros_etiqueta = adjunto_tmp.parametros_etiqueta
                    db.session.add(op_nuevo)
                    db.session.add(mov)
                else:
                    if nombre_visible:
                        archivo.nombre_visible = nombre_visible
            else:
                if nombre_visible:
                    archivo.nombre_visible = nombre_visible
                if cantidad_original is not None:
                    archivo.cantidad = cantidad_original
                if unidad:
                    archivo.unidad = unidad
                if producto_nuevo:
                    archivo.producto_id = producto_nuevo.id
                    archivo.material = producto_nuevo.nombre

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
        ancho_util_override_list = request.form.getlist('ancho_util_override[]')

        for i, nombre_visible in enumerate(nombres_visibles):
            if not nombre_visible.strip():
                continue
            producto_id = int(productos_ids[i]) if i < len(productos_ids) and productos_ids[i] else None
            cantidad_str = cantidades[i] if i < len(cantidades) else ''
            unidad = unidades[i] if i < len(unidades) else 'm2'
            cantidad_original = None
            if cantidad_str.strip():
                try:
                    cantidad_original = float(cantidad_str)
                except ValueError:
                    cantidad_original = None
            proyecto_linea = proyectos_linea[i] if i < len(proyectos_linea) else 'otros'
            producto = Producto.query.get(producto_id) if producto_id else None

            ancho_util_override = None
            if i < len(ancho_util_override_list) and ancho_util_override_list[i].strip():
                try:
                    ancho_util_override = float(ancho_util_override_list[i].strip())
                except:
                    pass

            if proyecto_linea == 'etiquetas':
                if not producto:
                    flash(f'Línea {i+1}: Debes seleccionar un producto del inventario.', 'danger')
                    db.session.rollback()
                    context = _get_form_context(form_data=request.form, edit=True, order=order)
                    return render_template('form_orden.html', **context)
                if not producto.largo_rollo or producto.largo_rollo <= 0:
                    flash(f'Línea {i+1}: El producto no tiene largo de rollo definido.', 'danger')
                    db.session.rollback()
                    context = _get_form_context(form_data=request.form, edit=True, order=order)
                    return render_template('form_orden.html', **context)

                ancho_cm = float(ancho_etiqueta_list[i]) if i < len(ancho_etiqueta_list) and ancho_etiqueta_list[i] else 0
                alto_cm = float(alto_etiqueta_list[i]) if i < len(alto_etiqueta_list) and alto_etiqueta_list[i] else 0
                precio = float(precio_etiqueta_list[i]) if i < len(precio_etiqueta_list) and precio_etiqueta_list[i] else 10.0
                mesa = mesa_etiqueta_list[i] == '1' if i < len(mesa_etiqueta_list) else False
                girar = girar_etiqueta_list[i] == '1' if i < len(girar_etiqueta_list) else False
                auto_girar = auto_girar_etiqueta_list[i] == '1' if i < len(auto_girar_etiqueta_list) else False

                adjunto, op, mov, error = _procesar_linea_etiqueta(
                    order=order,
                    producto=producto,
                    ancho_cm=ancho_cm,
                    alto_cm=alto_cm,
                    precio=precio,
                    mesa=mesa,
                    girar=girar,
                    auto_girar=auto_girar,
                    unidad=unidad,
                    cantidad_original=cantidad_original,
                    ancho_util_override=ancho_util_override,
                    nombre_visible=nombre_visible,
                    order_num_para_comentario=order_num
                )
                if error:
                    flash(f'Línea {i+1}: {error}', 'danger')
                    db.session.rollback()
                    context = _get_form_context(form_data=request.form, edit=True, order=order)
                    return render_template('form_orden.html', **context)
                db.session.add(adjunto)
                db.session.add(op)
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

        order.add_history(f'Editada por {current_user.username}')

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
        enlace = url_for('ordenes.detalle_order', order_id=order.id, _external=True)
        if usuarios_ids:
            notificar_usuarios(usuarios_ids, mensaje, 'orden_editada', order.id, enlace)
        order.set_usuarios_notificados(usuarios_ids)

        db.session.commit()
        flash('Orden actualizada correctamente.', 'success')
        return redirect(url_for('ordenes.edit_order', order_id=order.id))

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
# MARCAR ENTRADA
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
    existing = Order.query.filter(Order.order_num == odoo_order_num, Order.id != order_id).first()
    if existing:
        cliente_nombre = existing.client.nombre if existing.client else 'sin cliente'
        flash(f'El número "{odoo_order_num}" ya está asignado a la orden #{existing.id} (cliente: {cliente_nombre}).', 'danger')
        return redirect(url_for('ordenes.list_orders'))
    order.order_num = odoo_order_num
    order.entrada_ok = True
    order.add_history(f'Entrada al sistema marcada por {current_user.username} con número {odoo_order_num}')
    db.session.commit()

    movimientos_reserva = Movimiento.query.filter_by(orden_id=order.id, tipo='reserva').all()
    for mov in movimientos_reserva:
        if mov.comentario and 'sin número' in mov.comentario:
            mov.comentario = mov.comentario.replace('sin número', odoo_order_num)
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
    for op in OrdenProducto.query.filter_by(orden_id=order.id).all():
        producto = Producto.query.get(op.producto_id)
        if producto:
            _liberar_reserva(producto, op.cantidad_estimada)
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
    return send_file(temp_path, as_attachment=True,
                     download_name=f'Orden_{order.order_num or "sin_numero"}.pdf',
                     mimetype='application/pdf')

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