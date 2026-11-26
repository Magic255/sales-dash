"""Add expiry-dated inventory batches and FIFO batch references.

Revision ID: 0021_inventory_batches_expiry
Revises: 0020_inventory_stock_ledger
"""

# ruff: noqa: I001
from alembic import op
import sqlalchemy as sa


revision = "0021_inventory_batches_expiry"
down_revision = "0020_inventory_stock_ledger"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "stock_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("batch_code", sa.String(length=80), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "id", name="uq_stock_batches_company_id_id"),
        sa.UniqueConstraint(
            "company_id", "product_id", "batch_code",
            name="uq_stock_batches_company_product_code",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "product_id"], ["products.company_id", "products.id"],
            name="fk_stock_batches_product_same_company", ondelete="NO ACTION",
        ),
        sa.CheckConstraint("length(trim(batch_code)) > 0", name="batch_code_not_empty"),
    )
    op.create_index(
        "ix_stock_batches_company_product_expiry",
        "stock_batches", ["company_id", "product_id", "expiry_date"],
    )
    op.add_column("stock_movements", sa.Column("batch_id", sa.Uuid(), nullable=True))

    # Preserve existing stock history by grouping it into a non-expiring legacy batch.
    op.execute(
        """
        INSERT INTO stock_batches
            (id, company_id, product_id, batch_code, expiry_date, created_at)
        SELECT gen_random_uuid(), company_id, product_id,
               'LEGACY-' || replace(product_id::text, '-', ''),
               NULL, min(created_at)
        FROM stock_movements
        GROUP BY company_id, product_id
        """
    )
    op.execute(
        """
        UPDATE stock_movements AS movement
        SET batch_id = batch.id
        FROM stock_batches AS batch
        WHERE batch.company_id = movement.company_id
          AND batch.product_id = movement.product_id
          AND batch.batch_code =
              'LEGACY-' || replace(movement.product_id::text, '-', '')
        """
    )
    op.create_foreign_key(
        "fk_stock_movements_batch_same_company",
        "stock_movements", "stock_batches",
        ["company_id", "batch_id"], ["company_id", "id"],
        ondelete="NO ACTION",
    )
    op.execute("GRANT SELECT, INSERT ON stock_batches TO sales_dash_app")
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON stock_batches FROM sales_dash_app")
    op.execute("ALTER TABLE stock_batches ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE stock_batches FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY stock_batches_company_isolation
        ON stock_batches
        FOR ALL TO sales_dash_app
        USING (
            company_id =
            NULLIF(current_setting('app.current_company_id', true), '')::uuid
        )
        WITH CHECK (
            company_id =
            NULLIF(current_setting('app.current_company_id', true), '')::uuid
        )
        """
    )


def downgrade():
    op.execute("DROP POLICY IF EXISTS stock_batches_company_isolation ON stock_batches")
    op.execute("ALTER TABLE stock_batches NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE stock_batches DISABLE ROW LEVEL SECURITY")
    op.execute("REVOKE SELECT, INSERT ON stock_batches FROM sales_dash_app")
    op.drop_constraint(
        "fk_stock_movements_batch_same_company", "stock_movements", type_="foreignkey"
    )
    op.drop_column("stock_movements", "batch_id")
    op.drop_index("ix_stock_batches_company_product_expiry", table_name="stock_batches")
    op.drop_table("stock_batches")
