"""Add tenant-isolated append-only inventory movement ledger.

Revision ID: 0020_inventory_stock_ledger
Revises: 0019_product_price_floor
"""

from alembic import op
import sqlalchemy as sa


revision = "0020_inventory_stock_ledger"
down_revision = "0019_product_price_floor"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "products",
        sa.Column(
            "track_inventory", sa.Boolean(),
            nullable=False, server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "products",
        sa.Column(
            "low_stock_threshold", sa.Numeric(12, 3),
            nullable=False, server_default="0",
        ),
    )
    op.create_check_constraint(
        "low_stock_threshold_nonnegative", "products",
        "low_stock_threshold >= 0",
    )
    op.execute(
        """
        CREATE TABLE stock_movements (
            id UUID PRIMARY KEY,
            company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            product_id UUID NOT NULL,
            actor_user_id UUID NOT NULL,
            movement_type VARCHAR(24) NOT NULL,
            quantity NUMERIC(12, 3) NOT NULL,
            reason VARCHAR(1000) NOT NULL,
            reference VARCHAR(120),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT fk_stock_movements_product_same_company
                FOREIGN KEY (company_id, product_id)
                REFERENCES products(company_id, id) ON DELETE NO ACTION,
            CONSTRAINT fk_stock_movements_actor_membership
                FOREIGN KEY (company_id, actor_user_id)
                REFERENCES company_memberships(company_id, user_id) ON DELETE NO ACTION,
            CONSTRAINT ck_stock_movements_movement_type_is_supported
                CHECK (movement_type IN (
                    'received', 'sold', 'returned', 'damaged',
                    'adjustment_increase', 'adjustment_decrease',
                    'reserved', 'released'
                )),
            CONSTRAINT ck_stock_movements_quantity_positive CHECK (quantity > 0),
            CONSTRAINT ck_stock_movements_reason_not_empty
                CHECK (length(trim(reason)) > 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_stock_movements_company_product_time "
        "ON stock_movements (company_id, product_id, created_at)"
    )
    op.execute(
        "REVOKE UPDATE, DELETE, TRUNCATE ON stock_movements FROM sales_dash_app"
    )
    op.execute(
        "GRANT SELECT, INSERT ON stock_movements TO sales_dash_app"
    )
    op.execute("ALTER TABLE stock_movements ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE stock_movements FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY stock_movements_company_isolation
        ON stock_movements
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
    op.execute(
        "DROP POLICY IF EXISTS stock_movements_company_isolation ON stock_movements"
    )
    op.execute("ALTER TABLE stock_movements NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE stock_movements DISABLE ROW LEVEL SECURITY")
    op.execute("REVOKE SELECT, INSERT ON stock_movements FROM sales_dash_app")
    op.execute("DROP TABLE stock_movements")
    op.drop_constraint("low_stock_threshold_nonnegative", "products", type_="check")
    op.drop_column("products", "low_stock_threshold")
    op.drop_column("products", "track_inventory")
