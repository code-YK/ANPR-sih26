"""cameras.analytics_enabled -- operator toggle for continuous ANPR monitoring

Revision ID: 202608292344
Revises: 202608292336
Create Date: 2026-08-29

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "202608292344"
down_revision = "202608292336"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column("analytics_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("cameras", "analytics_enabled")
