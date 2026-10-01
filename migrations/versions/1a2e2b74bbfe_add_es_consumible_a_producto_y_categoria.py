"""add es_consumible a producto y categoria

Revision ID: 1a2e2b74bbfe
Revises: 1383c5cb3e70
Create Date: 2026-10-01 11:54:15.546633

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1a2e2b74bbfe'
down_revision = '1383c5cb3e70'
branch_labels = None
depends_on = None


def upgrade():
    # ---------------------------------------------------------
    # 1. Rellenar posibles NULLs en es_material_impresion
    #    (evita que falle el ALTER a NOT NULL)
    # ---------------------------------------------------------
    op.execute("UPDATE categorias SET es_material_impresion = 0 WHERE es_material_impresion IS NULL")

    # ---------------------------------------------------------
    # 2. Categorías: añadir es_consumible + forzar NOT NULL
    #    en es_material_impresion
    # ---------------------------------------------------------
    with op.batch_alter_table('categorias', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'es_consumible',
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),      # ← CLAVE: rellena filas existentes
            )
        )
        batch_op.alter_column(
            'es_material_impresion',
            existing_type=sa.BOOLEAN(),
            nullable=False,
        )

    # ---------------------------------------------------------
    # 3. Productos: añadir es_consumible
    # ---------------------------------------------------------
    with op.batch_alter_table('productos', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'es_consumible',
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),      # ← CLAVE
            )
        )


def downgrade():
    with op.batch_alter_table('productos', schema=None) as batch_op:
        batch_op.drop_column('es_consumible')

    with op.batch_alter_table('categorias', schema=None) as batch_op:
        batch_op.alter_column(
            'es_material_impresion',
            existing_type=sa.BOOLEAN(),
            nullable=True,
        )
        batch_op.drop_column('es_consumible')