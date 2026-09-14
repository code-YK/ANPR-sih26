"""cameras.analytics_finetuned_enabled -- operator toggle for continuous
ANPR finetuned monitoring (fine-tuned veh5 checkpoint, mirrors
analytics_enabled)

Revision ID: 202609141500
Revises: 202608312000
Create Date: 2026-09-14

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "202609141500"
down_revision = "202608312000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column("analytics_finetuned_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("cameras", "analytics_finetuned_enabled")
