"""Record official-source and scope checks for compliance approval.

Revision ID: 0027_verification_sources
Revises: 0026_private_evidence
"""

# ruff: noqa: I001
from alembic import op
import sqlalchemy as sa


revision = "0027_verification_sources"
down_revision = "0026_private_evidence"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("stock_batches", sa.Column("authority_role", sa.String(length=32)))
    op.add_column("stock_batches", sa.Column("verification_method", sa.String(length=32)))
    op.add_column("stock_batches", sa.Column("verification_source_url", sa.String(length=500)))
    op.add_column("stock_batches", sa.Column("verification_reference", sa.String(length=200)))
    op.add_column(
        "stock_batches",
        sa.Column("verified_product_identifier", sa.String(length=200)),
    )
    op.add_column("stock_batches", sa.Column("verified_scope", sa.String(length=300)))
    op.add_column(
        "stock_batches",
        sa.Column("accreditation_body_name", sa.String(length=160)),
    )
    op.create_check_constraint(
        "authority_role_supported",
        "stock_batches",
        "authority_role IS NULL OR authority_role IN "
        "('standards_body', 'regulator', 'certification_body', 'accreditation_body', "
        "'testing_lab', 'inspection_body', 'other')",
    )
    op.create_check_constraint(
        "verification_method_supported",
        "stock_batches",
        "verification_method IS NULL OR verification_method IN "
        "('official_registry', 'accreditation_scope', 'issuer_confirmation', 'document_review')",
    )
    op.create_check_constraint(
        "verification_source_https",
        "stock_batches",
        "verification_source_url IS NULL OR verification_source_url LIKE 'https://%'",
    )
    op.execute(
        "GRANT UPDATE (authority_role, verification_method, verification_source_url, "
        "verification_reference, verified_product_identifier, verified_scope, "
        "accreditation_body_name) ON stock_batches TO sales_dash_app"
    )


def downgrade():
    op.execute(
        "REVOKE UPDATE (authority_role, verification_method, verification_source_url, "
        "verification_reference, verified_product_identifier, verified_scope, "
        "accreditation_body_name) ON stock_batches FROM sales_dash_app"
    )
    op.drop_constraint("verification_source_https", "stock_batches", type_="check")
    op.drop_constraint("verification_method_supported", "stock_batches", type_="check")
    op.drop_constraint("authority_role_supported", "stock_batches", type_="check")
    for column in (
        "accreditation_body_name",
        "verified_scope",
        "verified_product_identifier",
        "verification_reference",
        "verification_source_url",
        "verification_method",
        "authority_role",
    ):
        op.drop_column("stock_batches", column)
