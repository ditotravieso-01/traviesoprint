"""orders: comercial_odoo_email y creado_por_odoo

Revision ID: b8f2c91a4d10
Revises: a7f3e91c4d28
Create Date: 2026-10-13 15:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b8f2c91a4d10'
down_revision = 'a7f3e91c4d28'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('comercial_odoo_email', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('creado_por_odoo', sa.String(length=100), nullable=True))
        batch_op.create_index(
            batch_op.f('ix_orders_comercial_odoo_email'),
            ['comercial_odoo_email'],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_orders_comercial_odoo_email'))
        batch_op.drop_column('creado_por_odoo')
        batch_op.drop_column('comercial_odoo_email')
