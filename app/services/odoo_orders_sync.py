"""
Servicio de sincronización de ventas confirmadas de Odoo -> Order.

Reutilizable desde:
    - CLI:  flask sync-odoo-orders
    - Web:  POST /ordenes/odoo-sync/run  (botón "Ejecutar ahora")

Lee de Configuracion:
    - odoo_orders_sync_enabled : 'true' / 'false'  (toggle global)
    - odoo_orders_sync_since   : ISO datetime       (marca de agua)

Nunca escribe en Odoo. Solo lee y escribe en la DB local.
No lanza excepción al caller salvo error de programación.
"""
from datetime import datetime, timezone

from app import db
from app.models import Order, Client, Configuracion, User
from app.services.odoo_service import OdooService


CLAVE_ENABLED = 'odoo_orders_sync_enabled'
CLAVE_SINCE = 'odoo_orders_sync_since'
BATCH_SIZE = 200


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _utcnow_naive():
    """UTC naive: coherente con lo que guardamos en Configuracion."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def is_enabled():
    valor = (Configuracion.get_config(CLAVE_ENABLED) or 'false').lower()
    return valor in ('true', '1', 'yes', 't')


def set_enabled(activo):
    Configuracion.set_config(CLAVE_ENABLED, 'true' if activo else 'false')


def get_since():
    raw = Configuracion.get_config(CLAVE_SINCE)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def set_since(dt):
    Configuracion.set_config(CLAVE_SINCE, dt.isoformat(timespec='seconds'))


# ------------------------------------------------------------------
# Núcleo
# ------------------------------------------------------------------
def run_sync(force=False):
    """
    Ejecuta un ciclo de sincronización.

    Args:
        force: si True ignora el toggle enabled. Se usa desde el endpoint
               web "Ejecutar ahora" cuando el admin lo pulsa explícitamente
               (aunque el toggle esté apagado, si lo pulsa es porque quiere).

    Returns:
        dict con:
            ok            bool
            motivo        str o None   (si ok=False)
            nuevas        int
            enlazadas     int
            saltadas      int
            errores       int
            detalle       dict {nuevas, enlazadas, saltadas, errores: [str]}
            since_usado   ISO str o None
            since_nuevo   ISO str o None
            ventas_total  int          (cuántas devolvió Odoo, útil para el log)
    """
    resultado = {
        'ok': True,
        'motivo': None,
        'nuevas': 0,
        'enlazadas': 0,
        'saltadas': 0,
        'errores': 0,
        'detalle': {'nuevas': [], 'enlazadas': [], 'saltadas': [], 'errores': []},
        'since_usado': None,
        'since_nuevo': None,
        'ventas_total': 0,
    }

    # 1. Toggle
    if not force and not is_enabled():
        resultado['ok'] = False
        resultado['motivo'] = 'sync_disabled'
        return resultado

    # 2. Marca de agua
    since = get_since()
    if not since:
        now = _utcnow_naive()
        set_since(now)
        resultado['ok'] = False
        resultado['motivo'] = 'inicializado_since'
        resultado['since_nuevo'] = now.isoformat(timespec='seconds')
        return resultado

    resultado['since_usado'] = since.isoformat(timespec='seconds')

    # 3. Fetch Odoo
    try:
        service = OdooService()
        ventas = service.get_ventas_confirmadas(desde=since, limit=BATCH_SIZE)
    except Exception as e:
        resultado['ok'] = False
        resultado['motivo'] = f'odoo_error: {e}'
        return resultado

    resultado['ventas_total'] = len(ventas)

    # 4. Procesar
    from app.services.notification_service import crear_notificacion
    ultima_fecha = None

    for venta in ventas:
        try:
            odoo_order_id = venta['id']
            order_num = venta.get('name') or f'ODOO-{odoo_order_id}'

            # 4a. Dedup
            if Order.query.filter_by(odoo_order_id=odoo_order_id).first():
                continue

            # 4b. Cliente
            partner = venta.get('partner_id') or []
            if not isinstance(partner, (list, tuple)) or not partner:
                resultado['saltadas'] += 1
                resultado['detalle']['saltadas'].append(f"{order_num}: sin partner_id")
                continue
            cliente = Client.query.filter_by(odoo_partner_id=partner[0]).first()
            if not cliente:
                resultado['saltadas'] += 1
                resultado['detalle']['saltadas'].append(
                    f"{order_num}: cliente odoo_id={partner[0]} no existe local"
                )
                continue

            # 4c. Enlazar por order_num si existe sin odoo_order_id
            existente = Order.query.filter_by(order_num=order_num).first()
            if existente and not existente.odoo_order_id:
                existente.odoo_order_id = odoo_order_id
                existente.requiere_revision = True
                resultado['enlazadas'] += 1
                resultado['detalle']['enlazadas'].append(
                    f"{order_num} -> id local {existente.id}"
                )
                if venta.get('date_order'):
                    ultima_fecha = venta['date_order']
                continue

            # 4d. Fechas
            try:
                fecha_order = datetime.strptime(
                    venta['date_order'], '%Y-%m-%d %H:%M:%S'
                ).date()
                ultima_fecha = venta['date_order']
            except (KeyError, ValueError):
                fecha_order = _utcnow_naive().date()

            fecha_entrega = None
            commitment = venta.get('commitment_date')
            if commitment and commitment is not False:
                try:
                    fecha_entrega = datetime.strptime(commitment, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    fecha_entrega = None

            # 4e. Vendedor Odoo
            user_data = venta.get('user_id') or []
            comercial_odoo = (
                user_data[1]
                if isinstance(user_data, (list, tuple)) and len(user_data) > 1
                else None
            )

            # 4f. Mapeo a usuario local
            created_by_id = None
            if comercial_odoo:
                norm = comercial_odoo.strip().lower().replace(' ', '')
                local_user = User.query.filter(
                    db.func.lower(User.username) == norm
                ).first()
                if local_user:
                    created_by_id = local_user.id

            # 4g. Crear Order
            nueva = Order(
                order_num=order_num,
                date=fecha_order,
                client_id=cliente.id,
                descripcion=venta.get('note') or '',
                entrada_ok=True,
                column='pendiente',
                ruta='impresion',
                priority='normal',
                tipo_proyecto='grafica',
                requiere_revision=True,
                odoo_order_id=odoo_order_id,
                comercial_odoo=comercial_odoo,
                fecha_entrega_odoo=fecha_entrega,
                created_by_id=created_by_id,
            )
            nueva.add_history(f"Importada desde Odoo ({order_num})")
            db.session.add(nueva)
            db.session.flush()

            resultado['nuevas'] += 1
            resultado['detalle']['nuevas'].append(f"{order_num} . {cliente.nombre}")

            if created_by_id:
                try:
                    crear_notificacion(
                        usuario_id=created_by_id,
                        mensaje=f"Orden {order_num} importada de Odoo. Requiere revision.",
                        tipo='orden_importada',
                        order_id=nueva.id,
                        enlace=f"/ordenes/{nueva.id}",
                    )
                except Exception as e:
                    # No abortamos la importación por una notificación fallida
                    resultado['detalle']['errores'].append(
                        f"{order_num}: notif falló . {e}"
                    )

        except Exception as e:
            resultado['errores'] += 1
            resultado['detalle']['errores'].append(f"odoo_id={venta.get('id')} . {e}")

    # 5. Commit + avanzar marca
    try:
        db.session.commit()

        # Lógica de avance:
        # - Si trajimos menos que el límite, ya no hay más pendientes → since = now()
        # - Si trajimos exactamente el límite, quedan por procesar → since = última date_order
        if len(ventas) < BATCH_SIZE:
            nuevo_since = _utcnow_naive()
        elif ultima_fecha:
            nuevo_since = datetime.strptime(ultima_fecha, '%Y-%m-%d %H:%M:%S')
        else:
            nuevo_since = _utcnow_naive()

        set_since(nuevo_since)
        resultado['since_nuevo'] = nuevo_since.isoformat(timespec='seconds')
    except Exception as e:
        db.session.rollback()
        resultado['ok'] = False
        resultado['motivo'] = f'commit_error: {e}'
        return resultado

    return resultado
