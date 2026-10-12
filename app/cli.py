"""
Comandos CLI personalizados de TraviesoPrint.

Se registran en create_app() con app.cli.add_command(...).

Uso:
    flask sync-odoo      # Sincroniza clientes desde Odoo
"""
import click
from flask.cli import with_appcontext

from app import db
from app.models import Client
from app.services.odoo_service import OdooService


@click.command('sync-odoo')
@with_appcontext
def sync_odoo_command():
    """
    Sincroniza clientes desde Odoo hacia TraviesoPrint.

    Lee todos los partners con customer_rank > 0 en Odoo y los inserta
    o actualiza en la tabla local `clients` usando odoo_partner_id como
    clave de correlación.

    Pensado para ejecutarse desde cron cada minuto. Es idempotente: si
    ya existe un cliente con el mismo odoo_partner_id, lo actualiza en
    lugar de duplicarlo.
    """
    service = OdooService()
    clientes = service.get_clientes()

    nuevos = 0
    actualizados = 0
    errores = 0

    for c in clientes:
        try:
            odoo_id = c['id']
            ref = (c.get('ref') or '').strip() or f'ODOO-{odoo_id}'

            existente = Client.query.filter_by(odoo_partner_id=odoo_id).first()

            if existente:
                # Actualizar campos básicos
                existente.nombre = c['name']
                existente.email = c.get('email') or None
                existente.telefono = c.get('phone') or None
                existente.direccion = c.get('street') or None
                actualizados += 1
            else:
                # Evitar choque con una referencia ya existente en local
                if Client.query.filter_by(referencia=ref).first():
                    ref = f'ODOO-{odoo_id}'

                nuevo = Client(
                    odoo_partner_id=odoo_id,
                    referencia=ref,
                    nombre=c['name'],
                    email=c.get('email') or None,
                    telefono=c.get('phone') or None,
                    direccion=c.get('street') or None,
                )
                db.session.add(nuevo)
                nuevos += 1

        except Exception as e:
            errores += 1
            click.echo(f'Error con cliente Odoo id={c.get("id")}: {e}', err=True)

    db.session.commit()
    click.echo(f'Sync OK: {nuevos} nuevos, {actualizados} actualizados, {errores} errores')