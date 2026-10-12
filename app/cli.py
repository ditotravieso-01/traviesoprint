"""
Comandos CLI personalizados de TraviesoPrint.

Se registran en create_app() con app.cli.add_command(...).

Uso:
    flask sync-odoo      # Sincroniza clientes desde Odoo
"""
import click
from flask.cli import with_appcontext

from app import db
from app.models import Client, Order, Configuracion, User
from app.services.odoo_service import OdooService


@click.command('sync-odoo')
@with_appcontext
def sync_odoo_command():
    """
    Sincroniza clientes desde Odoo hacia TraviesoPrint.

    Escribe bloques delimitados al log para que el script
    scripts/show_sync_log.sh los pueda parsear.
    """
    from datetime import datetime as _dt
    start = _dt.now()
    click.echo(f"=== SYNC START {start.strftime('%Y-%m-%d %H:%M:%S')} ===")

    service = OdooService()
    clientes = service.get_clientes()

    nuevos_list = []
    actualizados_list = []
    errores_list = []
    sin_cambios = 0

    for c in clientes:
        try:
            odoo_id = c['id']
            ref = (c.get('ref') or '').strip() or f'ODOO-{odoo_id}'
            new_nombre = c['name']
            new_email = c.get('email') or None
            new_telefono = c.get('phone') or None
            new_direccion = c.get('street') or None

            existente = Client.query.filter_by(odoo_partner_id=odoo_id).first()

            if existente:
                # Solo marcar como actualizado si algo cambió de verdad
                cambios = []
                if existente.nombre != new_nombre:
                    cambios.append('nombre')
                    existente.nombre = new_nombre
                if existente.email != new_email:
                    cambios.append('email')
                    existente.email = new_email
                if existente.telefono != new_telefono:
                    cambios.append('telefono')
                    existente.telefono = new_telefono
                if existente.direccion != new_direccion:
                    cambios.append('direccion')
                    existente.direccion = new_direccion

                if cambios:
                    actualizados_list.append(
                        f"{new_nombre} ({', '.join(cambios)})"
                    )
                else:
                    sin_cambios += 1
            else:
                if Client.query.filter_by(referencia=ref).first():
                    ref = f'ODOO-{odoo_id}'

                nuevo = Client(
                    odoo_partner_id=odoo_id,
                    referencia=ref,
                    nombre=new_nombre,
                    email=new_email,
                    telefono=new_telefono,
                    direccion=new_direccion,
                )
                db.session.add(nuevo)
                nuevos_list.append(new_nombre)

        except Exception as e:
            errores_list.append(f"odoo_id={c.get('id')} · {e}")

    db.session.commit()

    # ---- Detalle del bloque ----
    click.echo(f"Total procesados: {len(clientes)}")
    click.echo(f"Nuevos: {len(nuevos_list)}")
    for nombre in nuevos_list[:50]:
        click.echo(f"  + {nombre}")
    if len(nuevos_list) > 50:
        click.echo(f"  ... y {len(nuevos_list) - 50} más")

    click.echo(f"Actualizados: {len(actualizados_list)}")
    for item in actualizados_list[:20]:
        click.echo(f"  ~ {item}")
    if len(actualizados_list) > 20:
        click.echo(f"  ... y {len(actualizados_list) - 20} más")

    click.echo(f"Sin cambios: {sin_cambios}")
    click.echo(f"Errores: {len(errores_list)}")
    for err in errores_list[:10]:
        click.echo(f"  ! {err}", err=True)

    end = _dt.now()
    elapsed = (end - start).total_seconds()
    click.echo(f"=== SYNC END {end.strftime('%Y-%m-%d %H:%M:%S')} ({elapsed:.1f}s) ===")
    click.echo(f"Sync OK: {len(nuevos_list)} nuevos, {len(actualizados_list)} actualizados, {len(errores_list)} errores")

@click.command('sync-odoo-orders')
@with_appcontext
def sync_odoo_orders_command():
    """
    Sincroniza ventas confirmadas (sale.order state='sale') de Odoo
    hacia órdenes de TraviesoPrint.

    - Lee 'odoo_orders_sync_since' de Configuracion.
    - Si no existe, la inicializa a now() y termina sin importar historia.
    - Deduplica por Order.odoo_order_id.
    - Crea con requiere_revision=True.
    - Al final, actualiza 'odoo_orders_sync_since' = hora de inicio de este ciclo.
    """
    from datetime import datetime, timezone
    from app.services.notification_service import crear_notificacion

    def _utcnow():
        return datetime.now(timezone.utc).replace(tzinfo=None)

    start = _utcnow()
    click.echo(f"=== ORDERS SYNC START {start.strftime('%Y-%m-%d %H:%M:%S')} ===")

    # 1. Marca de agua
    since_str = Configuracion.get_config('odoo_orders_sync_since')
    if not since_str:
        now_iso = start.isoformat(timespec='seconds')
        Configuracion.set_config('odoo_orders_sync_since', now_iso)
        click.echo(f"Primera ejecucion. Marca inicializada a {now_iso}. No se importa historia.")
        click.echo(f"=== ORDERS SYNC END {_utcnow().strftime('%Y-%m-%d %H:%M:%S')} (0.0s) ===")
        click.echo("Sync OK: 0 nuevas, 0 enlazadas, 0 errores")
        return

    try:
        since = datetime.fromisoformat(since_str)
    except ValueError:
        click.echo(f"ERROR: odoo_orders_sync_since invalida: {since_str!r}", err=True)
        click.echo(f"=== ORDERS SYNC END {_utcnow().strftime('%Y-%m-%d %H:%M:%S')} (0.0s) ===")
        return

    click.echo(f"Buscando ventas confirmadas desde: {since.isoformat(timespec='seconds')}")

    # 2. Fetch Odoo
    try:
        service = OdooService()
        ventas = service.get_ventas_confirmadas(desde=since)
    except Exception as e:
        click.echo(f"ERROR: no se pudo consultar Odoo: {e}", err=True)
        click.echo(f"=== ORDERS SYNC END {_utcnow().strftime('%Y-%m-%d %H:%M:%S')} (0.0s) ===")
        return  # NO actualizamos marca → reintenta el proximo minuto

    click.echo(f"Ventas recibidas: {len(ventas)}")

    nuevas_list, enlazadas_list, skipped_list, errores_list = [], [], [], []

    # 3. Procesar
    for venta in ventas:
        try:
            odoo_order_id = venta['id']
            order_num = venta.get('name') or f'ODOO-{odoo_order_id}'

            # 3a. Dedup por odoo_order_id
            if Order.query.filter_by(odoo_order_id=odoo_order_id).first():
                continue

            # 3b. Cliente
            partner = venta.get('partner_id') or []
            if not isinstance(partner, (list, tuple)) or not partner:
                skipped_list.append(f"{order_num}: sin partner_id")
                continue
            cliente = Client.query.filter_by(odoo_partner_id=partner[0]).first()
            if not cliente:
                skipped_list.append(f"{order_num}: cliente odoo_id={partner[0]} no existe local")
                continue

            # 3c. Enlazar por order_num si ya existe sin odoo_order_id
            existente = Order.query.filter_by(order_num=order_num).first()
            if existente and not existente.odoo_order_id:
                existente.odoo_order_id = odoo_order_id
                existente.requiere_revision = True
                enlazadas_list.append(f"{order_num} -> id local {existente.id}")
                continue

            # 3d. Fechas
            try:
                fecha_order = datetime.strptime(venta['date_order'], '%Y-%m-%d %H:%M:%S').date()
            except (KeyError, ValueError):
                fecha_order = start.date()

            fecha_entrega = None
            commitment = venta.get('commitment_date')
            if commitment and commitment is not False:
                try:
                    fecha_entrega = datetime.strptime(commitment, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    fecha_entrega = None

            # 3e. Vendedor Odoo
            user_data = venta.get('user_id') or []
            comercial_odoo = (
                user_data[1]
                if isinstance(user_data, (list, tuple)) and len(user_data) > 1
                else None
            )

            # 3f. Mapear a usuario local (por username normalizado)
            created_by_id = None
            if comercial_odoo:
                norm = comercial_odoo.strip().lower().replace(' ', '')
                local_user = User.query.filter(
                    db.func.lower(User.username) == norm
                ).first()
                if local_user:
                    created_by_id = local_user.id

            # 3g. Crear Order
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

            nuevas_list.append(f"{order_num} . {cliente.nombre}")

            # 3h. Notificacion al creador (si se pudo mapear)
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
                    click.echo(f"  ! No se pudo notificar: {e}", err=True)

        except Exception as e:
            errores_list.append(f"odoo_id={venta.get('id')} . {e}")

    # 4. Commit + marca de agua
    try:
        db.session.commit()
        Configuracion.set_config('odoo_orders_sync_since', start.isoformat(timespec='seconds'))
    except Exception as e:
        db.session.rollback()
        click.echo(f"ERROR al commitear: {e}", err=True)
        click.echo(f"=== ORDERS SYNC END {_utcnow().strftime('%Y-%m-%d %H:%M:%S')} (0.0s) ===")
        return

    # 5. Detalle
    click.echo(f"Nuevas: {len(nuevas_list)}")
    for item in nuevas_list[:50]:
        click.echo(f"  + {item}")
    if len(nuevas_list) > 50:
        click.echo(f"  ... y {len(nuevas_list) - 50} mas")

    click.echo(f"Enlazadas: {len(enlazadas_list)}")
    for item in enlazadas_list[:20]:
        click.echo(f"  ~ {item}")

    click.echo(f"Saltadas: {len(skipped_list)}")
    for item in skipped_list[:20]:
        click.echo(f"  - {item}")

    click.echo(f"Errores: {len(errores_list)}")
    for err in errores_list[:10]:
        click.echo(f"  ! {err}", err=True)

    end = _utcnow()
    elapsed = (end - start).total_seconds()
    click.echo(f"=== ORDERS SYNC END {end.strftime('%Y-%m-%d %H:%M:%S')} ({elapsed:.1f}s) ===")
    click.echo(f"Sync OK: {len(nuevas_list)} nuevas, {len(enlazadas_list)} enlazadas, {len(errores_list)} errores")