"""Add tenant-isolated product batches and append-only stock movements.

Revision ID: 0020_inventory_ledger
Revises: 0019_product_price_floor
"""

# ruff: noqa: I001
from alembic import op
import sqlalchemy as sa


revision = "0020_inventory_ledger"
down_revision = "0019_product_price_floor"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "products",
        sa.Column("track_inventory", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "products",
        sa.Column("reorder_level", sa.Numeric(12, 3), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "reorder_level_nonnegative", "products", "reorder_level >= 0"
    )

    op.create_table(
        "product_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("batch_code", sa.String(length=80), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id", "id", name="uq_product_batches_company_id_id"
        ),
        sa.UniqueConstraint(
            "company_id", "product_id", "batch_code",
            name="uq_product_batches_company_product_code",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["products.company_id", "products.id"],
            ondelete="NO ACTION",
            name="fk_product_batches_product_same_company",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "created_by_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            ondelete="NO ACTION",
            name="fk_product_batches_creator_membership",
        ),
        sa.CheckConstraint(
            "length(trim(batch_code)) > 0", name="batch_code_not_empty"
        ),
    )
    op.create_index(
        "ix_product_batches_company_product",
        "product_batches", ["company_id", "product_id"],
    )
    op.add_column(
        "sale_items",
        sa.Column("batch_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_sale_items_batch_same_company",
        "sale_items", "product_batches",
        ["company_id", "batch_id"], ["company_id", "id"],
        ondelete="NO ACTION",
    )

    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("sale_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("actor_label", sa.String(length=255), nullable=False),
        sa.Column("movement_type", sa.String(length=20), nullable=False),
        sa.Column(
            "quantity_delta", sa.Numeric(12, 3),
            server_default="0", nullable=False,
        ),
        sa.Column(
            "reserved_delta", sa.Numeric(12, 3),
            server_default="0", nullable=False,
        ),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id", "id", name="uq_stock_movements_company_id_id"
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["products.company_id", "products.id"],
            ondelete="NO ACTION",
            name="fk_stock_movements_product_same_company",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "batch_id"],
            ["product_batches.company_id", "product_batches.id"],
            ondelete="NO ACTION",
            name="fk_stock_movements_batch_same_company",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "actor_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            ondelete="NO ACTION",
            name="fk_stock_movements_actor_same_company",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "sale_id"],
            ["sales.company_id", "sales.id"],
            ondelete="NO ACTION",
            name="fk_stock_movements_sale_same_company",
        ),
        sa.CheckConstraint(
            "movement_type IN ('received', 'sold', 'returned', 'damaged', "
            "'adjusted', 'reserved', 'released')",
            name="stock_movement_type_supported",
        ),
        sa.CheckConstraint(
            "quantity_delta <> 0 OR reserved_delta <> 0",
            name="stock_movement_nonzero",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) > 0",
            name="stock_movement_reason_not_empty",
        ),
        sa.CheckConstraint(
            "(movement_type IN ('received', 'returned') AND quantity_delta > 0 "
            "AND reserved_delta = 0) OR "
            "(movement_type IN ('sold', 'damaged') AND quantity_delta < 0 "
            "AND reserved_delta = 0) OR "
            "(movement_type = 'adjusted' AND quantity_delta <> 0 "
            "AND reserved_delta = 0) OR "
            "(movement_type = 'reserved' AND quantity_delta = 0 "
            "AND reserved_delta > 0) OR "
            "(movement_type = 'released' AND quantity_delta = 0 "
            "AND reserved_delta < 0)",
            name="stock_movement_delta_matches_type",
        ),
    )
    op.create_index(
        "ix_stock_movements_company_batch",
        "stock_movements", ["company_id", "batch_id"],
    )
    op.create_index(
        "ix_stock_movements_company_product",
        "stock_movements", ["company_id", "product_id"],
    )
    op.create_index(
        "ix_stock_movements_company_created",
        "stock_movements", ["company_id", "created_at"],
    )

    for table in ("product_batches", "stock_movements"):
        op.execute(f"GRANT SELECT, INSERT ON {table} TO sales_dash_app")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_company_isolation
            ON {table}
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
    for table in ("stock_movements", "product_batches"):
        op.execute(f"DROP POLICY IF EXISTS {table}_company_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE SELECT, INSERT ON {table} FROM sales_dash_app")

    op.drop_index("ix_stock_movements_company_created", table_name="stock_movements")
    op.drop_index("ix_stock_movements_company_product", table_name="stock_movements")
    op.drop_index("ix_stock_movements_company_batch", table_name="stock_movements")
    op.drop_table("stock_movements")
    op.drop_constraint(
        "fk_sale_items_batch_same_company", "sale_items", type_="foreignkey"
    )
    op.drop_column("sale_items", "batch_id")
    op.drop_index("ix_product_batches_company_product", table_name="product_batches")
    op.drop_table("product_batches")
    op.drop_constraint("reorder_level_nonnegative", "products", type_="check")
    op.drop_column("products", "reorder_level")
    op.drop_column("products", "track_inventory")
