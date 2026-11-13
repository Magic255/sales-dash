"""Create company-isolated customer, product, sale, and line-item tables.

Revision ID: 0006_sales_domain
Revises: 0005_security_audit_logs
"""

# ruff: noqa: I001
from alembic import op
import sqlalchemy as sa


revision = "0006_sales_domain"
down_revision = "0005_security_audit_logs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "customers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("organization", sa.String(length=160), nullable=True),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_customers_name_not_empty"),
        sa.CheckConstraint("email IS NULL OR email = lower(trim(email))", name="ck_customers_email_normalized"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE", name="fk_customers_company_id_companies"),
        sa.ForeignKeyConstraint(["company_id", "created_by_user_id"], ["company_memberships.company_id", "company_memberships.user_id"], ondelete="RESTRICT", name="fk_customers_creator_membership"),
        sa.PrimaryKeyConstraint("id", name="pk_customers"),
        sa.UniqueConstraint("company_id", "id", name="uq_customers_company_id_id"),
        sa.UniqueConstraint("company_id", "email", name="uq_customers_company_email"),
    )
    op.create_index("ix_customers_company_name", "customers", ["company_id", "name"])

    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="TZS", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(trim(sku)) > 0", name="ck_products_sku_not_empty"),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_products_name_not_empty"),
        sa.CheckConstraint("unit_price >= 0", name="ck_products_unit_price_nonnegative"),
        sa.CheckConstraint("currency = upper(currency) AND length(currency) = 3", name="ck_products_currency_iso_code"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE", name="fk_products_company_id_companies"),
        sa.ForeignKeyConstraint(["company_id", "created_by_user_id"], ["company_memberships.company_id", "company_memberships.user_id"], ondelete="RESTRICT", name="fk_products_creator_membership"),
        sa.PrimaryKeyConstraint("id", name="pk_products"),
        sa.UniqueConstraint("company_id", "id", name="uq_products_company_id_id"),
        sa.UniqueConstraint("company_id", "sku", name="uq_products_company_sku"),
    )
    op.create_index("ix_products_company_name", "products", ["company_id", "name"])

    op.create_table(
        "sales",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("sale_number", sa.String(length=40), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("salesperson_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("sale_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="TZS", nullable=False),
        sa.Column("subtotal", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("discount_amount", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("tax_amount", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("total_amount", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(trim(sale_number)) > 0", name="ck_sales_sale_number_not_empty"),
        sa.CheckConstraint("status IN ('draft', 'completed', 'void')", name="ck_sales_status_is_supported"),
        sa.CheckConstraint("length(currency) = 3 AND currency = upper(currency)", name="ck_sales_currency_iso_code"),
        sa.CheckConstraint("subtotal >= 0", name="ck_sales_subtotal_nonnegative"),
        sa.CheckConstraint("discount_amount >= 0", name="ck_sales_discount_nonnegative"),
        sa.CheckConstraint("tax_amount >= 0", name="ck_sales_tax_nonnegative"),
        sa.CheckConstraint("total_amount >= 0", name="ck_sales_total_nonnegative"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE", name="fk_sales_company_id_companies"),
        sa.ForeignKeyConstraint(["company_id", "customer_id"], ["customers.company_id", "customers.id"], ondelete="RESTRICT", name="fk_sales_customer_same_company"),
        sa.ForeignKeyConstraint(["company_id", "salesperson_user_id"], ["company_memberships.company_id", "company_memberships.user_id"], ondelete="RESTRICT", name="fk_sales_salesperson_membership"),
        sa.ForeignKeyConstraint(["company_id", "created_by_user_id"], ["company_memberships.company_id", "company_memberships.user_id"], ondelete="RESTRICT", name="fk_sales_creator_membership"),
        sa.PrimaryKeyConstraint("id", name="pk_sales"),
        sa.UniqueConstraint("company_id", "id", name="uq_sales_company_id_id"),
        sa.UniqueConstraint("company_id", "sale_number", name="uq_sales_company_sale_number"),
    )
    op.create_index("ix_sales_company_date", "sales", ["company_id", "sale_date"])
    op.create_index("ix_sales_company_customer", "sales", ["company_id", "customer_id"])
    op.create_index("ix_sales_company_salesperson", "sales", ["company_id", "salesperson_user_id"])

    op.create_table(
        "sale_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("sale_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("product_name", sa.String(length=160), nullable=False),
        sa.Column("sku_snapshot", sa.String(length=64), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("line_total", sa.Numeric(14, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(trim(product_name)) > 0", name="ck_sale_items_product_name_not_empty"),
        sa.CheckConstraint("quantity > 0", name="ck_sale_items_quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="ck_sale_items_unit_price_nonnegative"),
        sa.CheckConstraint("discount_amount >= 0", name="ck_sale_items_discount_nonnegative"),
        sa.CheckConstraint("line_total >= 0", name="ck_sale_items_line_total_nonnegative"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE", name="fk_sale_items_company_id_companies"),
        sa.ForeignKeyConstraint(["company_id", "sale_id"], ["sales.company_id", "sales.id"], ondelete="CASCADE", name="fk_sale_items_sale_same_company"),
        sa.ForeignKeyConstraint(["company_id", "product_id"], ["products.company_id", "products.id"], ondelete="RESTRICT", name="fk_sale_items_product_same_company"),
        sa.PrimaryKeyConstraint("id", name="pk_sale_items"),
    )
    op.create_index("ix_sale_items_company_sale", "sale_items", ["company_id", "sale_id"])

    # Every sales-domain table is isolated by the active transaction-local tenant.
    # The app role is restricted to the active company for reads and writes.
    for table in ("customers", "products", "sales", "sale_items"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO sales_dash_app")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_company_isolation ON {table}
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
    for table in ("sale_items", "sales", "products", "customers"):
        op.execute(f"DROP POLICY IF EXISTS {table}_company_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE SELECT, INSERT, UPDATE, DELETE ON {table} FROM sales_dash_app")

    op.drop_index("ix_sale_items_company_sale", table_name="sale_items")
    op.drop_table("sale_items")
    op.drop_index("ix_sales_company_salesperson", table_name="sales")
    op.drop_index("ix_sales_company_customer", table_name="sales")
    op.drop_index("ix_sales_company_date", table_name="sales")
    op.drop_table("sales")
    op.drop_index("ix_products_company_name", table_name="products")
    op.drop_table("products")
    op.drop_index("ix_customers_company_name", table_name="customers")
    op.drop_table("customers")
