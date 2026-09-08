"""allow null rtsp/hls/webrtc urls, for manually-registered cameras

Revision ID: 202608290104
Revises: 202608282221
Create Date: 2026-08-29

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "202608290104"
down_revision = "202608282221"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("cameras", "rtsp_url", existing_type=sa.Text(), nullable=True)
    op.alter_column("cameras", "hls_url", existing_type=sa.Text(), nullable=True)
    op.alter_column("cameras", "webrtc_url", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    op.alter_column("cameras", "rtsp_url", existing_type=sa.Text(), nullable=False)
    op.alter_column("cameras", "hls_url", existing_type=sa.Text(), nullable=False)
    op.alter_column("cameras", "webrtc_url", existing_type=sa.Text(), nullable=False)
