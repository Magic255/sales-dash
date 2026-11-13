"""Create company-isolated customer, product, sale, and line-item tables.

Revision ID: 0006_sales_domain
Revises: 0005_security_audit_logs
"""

# ruff: noqa: I001
from alembic import op


revision = "0006_sales_domain"
down_revision = "0005_security_audit_logs"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE customers (
            id UUID PRIMARY KEY,
            company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            name VARCHAR(160) NOT NULL,
            email VARCHAR(320),
            phone VARCHAR(40),
            organization VARCHAR(160),
            notes VARCHAR(2000),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by_user_id UUID NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_customers_company_id_id UNIQUE (company_id, id),
            CONSTRAINT uq_customers_company_email UNIQUE (company_id, email),
            CONSTRAINT ck_customers_name_not_empty CHECK (length(trim(name)) > 0),
            CONSTRAINT ck_customers_email_normalized
                CHECK (email IS NULL OR email = lower(trim(email))),
            CONSTRAINT fk_customers_creator_membership
                FOREIGN KEY (company_id, created_by_user_id)
                REFERENCES company_memberships(company_id, user_id)
                ON DELETE NO ACTION
        )
        """
    )
    op.execute(
        """
        CREATE TABLE products (
            id UUID PRIMARY KEY,
            company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            sku VARCHAR(64) NOT NULL,
            name VARCHAR(160) NOT NULL,
            description VARCHAR(2000),
            unit_price NUMERIC(12, 2) NOT NULL,
            currency VARCHAR(3) NOT NULL DEFAULT 'TZS',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by_user_id UUID NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_products_company_id_id UNIQUE (company_id, id),
            CONSTRAINT uq_products_company_sku UNIQUE (company_id, sku),
            CONSTRAINT ck_products_sku_not_empty CHECK (length(trim(sku)) > 0),
            CONSTRAINT ck_products_name_not_empty CHECK (length(trim(name)) > 0),
            CONSTRAINT ck_products_unit_price_nonnegative CHECK (unit_price >= 0),
            CONSTRAINT ck_products_currency_iso_code
                CHECK (currency = upper(currency) AND length(currency) = 3),
            CONSTRAINT fk_products_creator_membership
                FOREIGN KEY (company_id, created_by_user_id)
                REFERENCES company_memberships(company_id, user_id)
                ON DELETE NO ACTION
        )
        """
    )
    op.execute(
        """
        CREATE TABLE sales (
            id UUID PRIMARY KEY,
            company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            sale_number VARCHAR(40) NOT NULL,
            customer_id UUID NOT NULL,
            salesperson_user_id UUID NOT NULL,
            created_by_user_id UUID NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            sale_date DATE NOT NULL,
            currency VARCHAR(3) NOT NULL DEFAULT 'TZS',
            subtotal NUMERIC(14, 2) NOT NULL DEFAULT 0,
            discount_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
            tax_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
            total_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
            notes VARCHAR(2000),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_sales_company_id_id UNIQUE (company_id, id),
            CONSTRAINT uq_sales_company_sale_number UNIQUE (company_id, sale_number),
            CONSTRAINT ck_sales_sale_number_not_empty
                CHECK (length(trim(sale_number)) > 0),
            CONSTRAINT ck_sales_status_is_supported
                CHECK (status IN ('draft', 'completed', 'void')),
            CONSTRAINT ck_sales_currency_iso_code
                CHECK (length(currency) = 3 AND currency = upper(currency)),
            CONSTRAINT ck_sales_subtotal_nonnegative CHECK (subtotal >= 0),
            CONSTRAINT ck_sales_discount_nonnegative CHECK (discount_amount >= 0),
            CONSTRAINT ck_sales_tax_nonnegative CHECK (tax_amount >= 0),
            CONSTRAINT ck_sales_total_nonnegative CHECK (total_amount >= 0),
            CONSTRAINT fk_sales_customer_same_company
                FOREIGN KEY (company_id, customer_id)
                REFERENCES customers(company_id, id)
                ON DELETE NO ACTION,
            CONSTRAINT fk_sales_salesperson_membership
                FOREIGN KEY (company_id, salesperson_user_id)
                REFERENCES company_memberships(company_id, user_id)
                ON DELETE NO ACTION,
            CONSTRAINT fk_sales_creator_membership
                FOREIGN KEY (company_id, created_by_user_id)
                REFERENCES company_memberships(company_id, user_id)
                ON DELETE NO ACTION
        )
        """
    )
    op.execute(
        """
        CREATE TABLE sale_items (
            id UUID PRIMARY KEY,
            company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            sale_id UUID NOT NULL,
            product_id UUID NOT NULL,
            product_name VARCHAR(160) NOT NULL,
            sku_snapshot VARCHAR(64) NOT NULL,
            quantity NUMERIC(12, 3) NOT NULL,
            unit_price NUMERIC(12, 2) NOT NULL,
            discount_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
            line_total NUMERIC(14, 2) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_sale_items_product_name_not_empty
                CHECK (length(trim(product_name)) > 0),
            CONSTRAINT ck_sale_items_quantity_positive CHECK (quantity > 0),
            CONSTRAINT ck_sale_items_unit_price_nonnegative CHECK (unit_price >= 0),
            CONSTRAINT ck_sale_items_discount_nonnegative CHECK (discount_amount >= 0),
            CONSTRAINT ck_sale_items_line_total_nonnegative CHECK (line_total >= 0),
            CONSTRAINT fk_sale_items_sale_same_company
                FOREIGN KEY (company_id, sale_id)
                REFERENCES sales(company_id, id)
                ON DELETE CASCADE,
            CONSTRAINT fk_sale_items_product_same_company
                FOREIGN KEY (company_id, product_id)
                REFERENCES products(company_id, id)
                ON DELETE NO ACTION
        )
        """
    )

    op.execute(
        "CREATE INDEX ix_customers_company_name ON customers (company_id, name)"
    )
    op.execute(
        "CREATE INDEX ix_products_company_name ON products (company_id, name)"
    )
    op.execute(
        "CREATE INDEX ix_sales_company_date ON sales (company_id, sale_date)"
    )
    op.execute(
        "CREATE INDEX ix_sales_company_customer ON sales (company_id, customer_id)"
    )
    op.execute(
        "CREATE INDEX ix_sales_company_salesperson "
        "ON sales (company_id, salesperson_user_id)"
    )
    op.execute(
        "CREATE INDEX ix_sale_items_company_sale ON sale_items (company_id, sale_id)"
    )

    # The active transaction-local company is required for every read and write.
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

    op.execute("DROP TABLE sale_items")
    op.execute("DROP TABLE sales")
    op.execute("DROP TABLE products")
    op.execute("DROP TABLE customers")
