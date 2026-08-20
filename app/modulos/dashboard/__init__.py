from flask import Blueprint, render_template, jsonify
from flask_login import login_required, current_user
from app.models import Order, Client, Producto, User
from app import db
from datetime import datetime, timedelta
from collections import defaultdict

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard', template_folder='templates')


def get_dashboard_data():
    """Recopila todos los datos necesarios para el dashboard."""
    ahora = datetime.now()
    hace_30d = ahora - timedelta(days=30)
    hace_7d = ahora - timedelta(days=7)
    inicio_mes = ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    inicio_mes_anterior = (inicio_mes - timedelta(days=1)).replace(day=1)

    # ===== ÓRDENES =====
    orders = Order.query.all()
    total_ordenes = len(orders)

    # Pendientes (sin entrada o en columnas iniciales)
    pendientes = sum(1 for o in orders if not o.entrada_ok or o.column in ['pendiente', 'por-preparar'])

    # Completadas (entregadas o listas)
    completadas = sum(1 for o in orders if o.column in ['entregados', 'listo'])

    # Facturación total (si existe el campo)
    facturacion_total = sum(getattr(o, 'total_facturado', 0) or 0 for o in orders)

    # ===== WORKFLOW =====
    columnas = ['pendiente', 'por-preparar', 'preparados', 'imprimir-hoy', 'impreso-corte', 'listo', 'entregados']
    workflow_values = []
    for col in columnas:
        workflow_values.append(sum(1 for o in orders if o.column == col))

    wf_pendientes = workflow_values[0] + workflow_values[1]
    wf_proceso = workflow_values[2] + workflow_values[3]
    wf_listo = workflow_values[4] + workflow_values[5]
    wf_entregados = workflow_values[6]

    # ===== CLIENTES =====
    clientes = Client.query.all()
    total_clientes = len(clientes)
    clientes_nuevos = sum(1 for c in clientes if c.created_at and c.created_at >= hace_30d)
    active_client_ids = db.session.query(Order.client_id).filter(Order.date >= hace_30d.date()).distinct().all()
    clientes_activos = len(active_client_ids)

    # Top cliente
    top_cliente = None
    if orders:
        cliente_facturacion = {}
        for o in orders:
            if o.client_id:
                cliente_facturacion[o.client_id] = cliente_facturacion.get(o.client_id, 0) + (getattr(o, 'total_facturado', 0) or 0)
        if cliente_facturacion:
            top_id = max(cliente_facturacion, key=cliente_facturacion.get)
            top_cliente_obj = Client.query.get(top_id)
            top_cliente = top_cliente_obj.nombre if top_cliente_obj else '—'

    # ===== INVENTARIO =====
    productos = Producto.query.filter(Producto.es_material_impresion == True).all()
    total_productos = len(productos)
    sin_stock = 0
    bajo_stock = 0
    valor_estimado = 0.0
    for p in productos:
        stock_m = p.stock_metros or 0
        stock_u = p.stock or 0
        if stock_m <= 0 and stock_u <= 0:
            sin_stock += 1
        elif stock_m < 5 or stock_u < 5:
            bajo_stock += 1
        if hasattr(p, 'precio_venta') and p.precio_venta and p.stock_metros:
            valor_estimado += p.precio_venta * p.stock_metros

    # ===== STOCK CRÍTICO =====
    stock_critico_items = []
    for p in productos:
        stock_m = p.stock_metros or 0
        stock_u = p.stock or 0
        if stock_m < 5 or stock_u < 5:
            stock_critico_items.append({
                'nombre': p.nombre,
                'stock': stock_m if stock_m > 0 else stock_u,
                'unidad': 'm' if stock_m > 0 else 'unidades'
            })
    stock_critico_items = sorted(stock_critico_items, key=lambda x: x['stock'])[:5]

    # ===== TIPOS DE PROYECTO =====
    tipos = {}
    for o in orders:
        t = o.tipo_proyecto or 'otros'
        tipos[t] = tipos.get(t, 0) + 1
    tipos_labels = list(tipos.keys())
    tipos_values = list(tipos.values())

    # ===== EVOLUCIÓN DIARIA (7 días) =====
    evolucion_labels = []
    evolucion_values = []
    for i in range(6, -1, -1):
        dia = ahora - timedelta(days=i)
        fecha_inicio = dia.replace(hour=0, minute=0, second=0, microsecond=0)
        fecha_fin = fecha_inicio + timedelta(days=1)
        count = sum(1 for o in orders if o.created_at and fecha_inicio <= o.created_at < fecha_fin)
        evolucion_labels.append(dia.strftime('%a'))
        evolucion_values.append(count)

    # ===== COMPARATIVA MENSUAL (últimos 6 meses) =====
    comp_labels = []
    comp_values = []
    for i in range(5, -1, -1):
        mes = ahora.replace(day=1) - timedelta(days=30 * i)
        nombre_mes = mes.strftime('%b')
        comp_labels.append(nombre_mes)
        inicio = mes.replace(day=1)
        fin = (inicio + timedelta(days=32)).replace(day=1)
        count = sum(1 for o in orders if o.created_at and inicio <= o.created_at < fin)
        comp_values.append(count)

    # ===== CALENDARIO: ENTREGAS DEL MES ACTUAL =====
    entregas = defaultdict(list)
    for o in orders:
        if o.fecha_entregado:
            dia = o.fecha_entregado.day
            entregas[dia].append({
                'orden': o.order_num or 'Sin número',
                'cliente': o.client.nombre if o.client else 'Sin cliente'
            })

    # ===== ACTIVIDAD RECIENTE =====
    actividad = []
    for o in orders[:10]:
        if o.created_at and (ahora - o.created_at).days < 1:
            actividad.append({
                'tipo': 'orden_nueva',
                'orden': o.order_num or 'Sin número',
                'cliente': o.client.nombre if o.client else 'Sin cliente',
                'tiempo': 'Hoy'
            })
    # Clientes nuevos hoy
    for c in clientes[:5]:
        if c.created_at and c.created_at.date() == ahora.date():
            actividad.append({
                'tipo': 'cliente_nuevo',
                'cliente': c.nombre,
                'tiempo': 'Hoy'
            })
    actividad = actividad[:8]

    # ===== ALERTAS =====
    alertas = []
    for o in orders:
        if o.column and o.column not in ['entregados', 'listo']:
            if hasattr(o, 'get_history') and o.get_history():
                historial = o.get_history()
                if historial:
                    ultimo = historial[-1]
                    if isinstance(ultimo, dict):
                        fecha_ult = ultimo.get('fecha')
                        if fecha_ult:
                            try:
                                fecha_dt = datetime.fromisoformat(fecha_ult) if isinstance(fecha_ult, str) else fecha_ult
                                if (ahora - fecha_dt).days > 3:
                                    alertas.append({
                                        'tipo': 'orden_atrasada',
                                        'orden': o.order_num or 'Sin número',
                                        'cliente': o.client.nombre if o.client else 'Sin cliente',
                                        'columna': o.column,
                                        'dias': (ahora - fecha_dt).days
                                    })
                            except:
                                pass
    for item in stock_critico_items[:2]:
        if item['stock'] == 0:
            alertas.append({
                'tipo': 'sin_stock',
                'producto': item['nombre']
            })
    alertas = sorted(alertas, key=lambda x: x.get('dias', 0), reverse=True)[:5]

    # ===== ÓRDENES RECIENTES =====
    recientes = []
    for o in sorted(orders, key=lambda x: x.created_at or datetime.min, reverse=True)[:5]:
        recientes.append({
            'num': o.order_num or 'Sin número',
            'cliente': o.client.nombre if o.client else 'Sin cliente',
            'estado': o.column or 'pendiente',
            'fecha': o.created_at.strftime('%d/%m') if o.created_at else '—'
        })

    return {
        'kpis': {
            'total': total_ordenes,
            'pendientes': pendientes,
            'completadas': completadas,
            'stock_critico': sin_stock + bajo_stock,
            'clientes_activos': clientes_activos,
            'facturacion': round(facturacion_total, 2)
        },
        'workflow': {
            'labels': ['Pendiente', 'Por preparar', 'Preparados', 'Imprimir hoy', 'Impreso y corte', 'Listo', 'Entregados'],
            'values': workflow_values
        },
        'tipos': {
            'labels': tipos_labels,
            'values': tipos_values
        },
        'evolucion': {
            'labels': evolucion_labels,
            'values': evolucion_values
        },
        'recientes': recientes,
        'stock_critico_items': stock_critico_items,
        'modulos': {
            'workflow': {
                'pendientes': wf_pendientes,
                'proceso': wf_proceso,
                'listo': wf_listo,
                'entregados': wf_entregados
            },
            'clientes': {
                'total': total_clientes,
                'nuevos': clientes_nuevos,
                'activos': clientes_activos,
                'top': top_cliente or '—'
            },
            'inventario': {
                'total': total_productos,
                'sin_stock': sin_stock,
                'bajo_stock': bajo_stock,
                'valor': round(valor_estimado, 2)
            },
            'ordenes': {
                'total': total_ordenes,
                'pend_entrada': sum(1 for o in orders if not o.entrada_ok),
                'facturacion': round(facturacion_total, 2),
                'ultima': orders[0].order_num if orders else '—'
            }
        },
        'entregas': dict(entregas),
        'comparativa': {
            'labels': comp_labels,
            'values': comp_values
        },
        'actividad': actividad,
        'alertas': alertas
    }


@dashboard_bp.route('/')
@login_required
def index():
    """Renderiza el dashboard principal."""
    return render_template('dashboard.html', now=datetime.now())


@dashboard_bp.route('/data')
@login_required
def data():
    """Endpoint API para obtener datos en JSON."""
    return jsonify(get_dashboard_data())