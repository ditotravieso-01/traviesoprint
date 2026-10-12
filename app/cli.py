"""
Comandos CLI personalizados de TraviesoPrint.

Se registran en create_app() con app.cli.add_command(...).

Uso:
    flask sync-odoo          # Sincroniza clientes desde Odoo
    flask sync-odoo-orders   # Sincroniza ventas confirmadas (sale.order) -> Order
"""
import click
from flask.cli import with_appcontext

from app import db
from app.models import Client
from app.services.odoo_service import OdooService


# ==================================================================
# COMANDO 1: sync-odoo (clientes) — EXISTENTE EN PRODUCCION
# ==================================================================
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
    click.echo(
        f"Sync OK: {len(nuevos_list)} nuevos, "
        f"{len(actualizados_list)} actualizados, {len(errores_list)} errores"
    )


# ==================================================================
# COMANDO 2: sync-odoo-orders (ventas) — NUEVO EN PARTE 28
# ==================================================================
@click.command('sync-odoo-orders')
@with_appcontext
def sync_odoo_orders_command():
    """
    Sincroniza ventas confirmadas (sale.order state='sale') de Odoo
    hacia ordenes de TraviesoPrint.

    Delega en app.services.odoo_orders_sync.run_sync().

    Respeta el toggle 'odoo_orders_sync_enabled' (Configuracion).
    Si esta en 'false', no hace nada (el cron puede seguir latiendo).
    """
    from datetime import datetime as _dt
    from app.services.odoo_orders_sync import run_sync

    start = _dt.now()
    click.echo(f"=== ORDERS SYNC START {start.strftime('%Y-%m-%d %H:%M:%S')} ===")

    resultado = run_sync(force=False)

    # --- Salidas tempranas (toggle off o marca recien inicializada) ---
    if not resultado['ok']:
        motivo = resultado['motivo']
        if motivo == 'sync_disabled':
            click.echo("Sync deshabilitado (odoo_orders_sync_enabled=false). Nada que hacer.")
        elif motivo == 'inicializado_since':
            click.echo(
                f"Primera ejecucion. Marca inicializada a {resultado['since_nuevo']}. "
                "No se importa historia."
            )
        else:
            click.echo(f"ERROR: {motivo}", err=True)

        end = _dt.now()
        elapsed = (end - start).total_seconds()
        click.echo(f"=== ORDERS SYNC END {end.strftime('%Y-%m-%d %H:%M:%S')} ({elapsed:.1f}s) ===")
        click.echo("Sync OK: 0 nuevas, 0 enlazadas, 0 errores")
        return

    # --- Camino normal ---
    click.echo(f"Buscando ventas confirmadas desde: {resultado['since_usado']}")
    click.echo(f"Ventas recibidas: {resultado['ventas_total']}")

    click.echo(f"Nuevas: {resultado['nuevas']}")
    for item in resultado['detalle']['nuevas'][:50]:
        click.echo(f"  + {item}")
    if resultado['nuevas'] > 50:
        click.echo(f"  ... y {resultado['nuevas'] - 50} mas")

    click.echo(f"Enlazadas: {resultado['enlazadas']}")
    for item in resultado['detalle']['enlazadas'][:20]:
        click.echo(f"  ~ {item}")

    click.echo(f"Saltadas: {resultado['saltadas']}")
    for item in resultado['detalle']['saltadas'][:20]:
        click.echo(f"  - {item}")

    click.echo(f"Errores: {resultado['errores']}")
    for item in resultado['detalle']['errores'][:10]:
        click.echo(f"  ! {item}", err=True)

    end = _dt.now()
    elapsed = (end - start).total_seconds()
    click.echo(f"=== ORDERS SYNC END {end.strftime('%Y-%m-%d %H:%M:%S')} ({elapsed:.1f}s) ===")
    click.echo(
        f"Sync OK: {resultado['nuevas']} nuevas, "
        f"{resultado['enlazadas']} enlazadas, {resultado['errores']} errores"
    )