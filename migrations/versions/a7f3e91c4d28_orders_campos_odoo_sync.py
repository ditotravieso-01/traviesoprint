"""orders: campos de integracion con Odoo (sync de ventas)

Revision ID: a7f3e91c4d28
Revises: d06abacbf1fc
Create Date: 2026-10-12 14:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7f3e91c4d28'
down_revision = 'd06abacbf1fc'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('odoo_order_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column(
            'requiere_revision',
            sa.Boolean(),
            server_default='0',
            nullable=False,
        ))
        batch_op.add_column(sa.Column('comercial_odoo', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('fecha_entrega_odoo', sa.DateTime(), nullable=True))

        # Índice único sobre odoo_order_id (mismo patrón que clients.odoo_partner_id)
        batch_op.create_index(
            batch_op.f('ix_orders_odoo_order_id'),
            ['odoo_order_id'],
            unique=True,
        )
        # Índice no-único sobre requiere_revision (filtros frecuentes en listado/workflow)
        batch_op.create_index(
            batch_op.f('ix_orders_requiere_revision'),
            ['requiere_revision'],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_orders_requiere_revision'))
        batch_op.drop_index(batch_op.f('ix_orders_odoo_order_id'))
        batch_op.drop_column('fecha_entrega_odoo')
        batch_op.drop_column('comercial_odoo')
        batch_op.drop_column('requiere_revision')
        batch_op.drop_column('odoo_order_id')
