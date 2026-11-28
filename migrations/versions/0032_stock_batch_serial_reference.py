"""Add unique supplier stock serial references.

Revision ID: 0032_batch_serial_ref
Revises: 0031_po_receipts
"""

# ruff: noqa: I001
from alembic import op
import sqlalchemy as sa


revision = "0032_batch_serial_ref"
down_revision = "0031_po_receipts"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "stock_batches", sa.Column("serial_reference", sa.String(length=160), nullable=True)
    )
    op.create_unique_constraint(
        "uq_stock_batches_company_serial_reference",
        "stock_batches",
        ["company_id", "serial_reference"],
    )


def downgrade():
    op.drop_constraint(
        "uq_stock_batches_company_serial_reference", "stock_batches", type_="unique"
    )
    op.drop_column("stock_batches", "serial_reference")
