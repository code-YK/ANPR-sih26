"""named, credentialed catalogue sources for multi-source camera onboarding

Revision ID: 202608311200
Revises: 202608301800
Create Date: 2026-08-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202608311200"
down_revision = "202608301800"
branch_labels = None
depends_on = None

# Only the one catalogue shape this project has actually seen. A registry
# in app/pipeline/catalogue_sources.py validates against this same set at
# the application layer too; the CHECK constraint is the DB-level backstop.
_ADAPTERS = ("sentinel_default",)


def upgrade() -> None:
    op.create_table(
        "catalogue_sources",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("adapter", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("browser_base_url", sa.Text(), nullable=True),
        sa.Column("auth_header_name", sa.Text(), nullable=True),
        # Never returned by any GET/list response -- see CatalogueSourceOut.
        sa.Column("auth_secret", sa.Text(), nullable=True),
        sa.Column("allow_private_host", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            onupdate=sa.text("now()"), nullable=False,
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_result", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_catalogue_sources_name_not_blank"),
        sa.CheckConstraint(
            "adapter IN (" + ", ".join(f"'{a}'" for a in _ADAPTERS) + ")", name="ck_catalogue_sources_adapter"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_catalogue_sources_created_by", ondelete="SET NULL"),
    )
    op.create_index("uq_catalogue_sources_name_lower", "catalogue_sources", [sa.text("lower(name)")], unique=True)

    op.add_column("cameras", sa.Column("source_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_cameras_source_id", "cameras", "catalogue_sources", ["source_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_index("ix_cameras_source_id", "cameras", ["source_id"])


def downgrade() -> None:
    op.drop_index("ix_cameras_source_id", table_name="cameras")
    op.drop_constraint("fk_cameras_source_id", "cameras", type_="foreignkey")
    op.drop_column("cameras", "source_id")

    op.drop_index("uq_catalogue_sources_name_lower", table_name="catalogue_sources")
    op.drop_table("catalogue_sources")
