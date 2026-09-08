"""evidence fields on sightings: raw OCR text, bbox, model version, evidence image reference

Revision ID: 202608311900
Revises: 202608311800
Create Date: 2026-08-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202608311900"
down_revision = "202608311800"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sightings", sa.Column("raw_ocr_text", sa.Text(), nullable=True))
    op.add_column("sightings", sa.Column("bbox", postgresql.JSONB(), nullable=True))
    op.add_column("sightings", sa.Column("model_version", sa.Text(), nullable=True))
    # Relative path under settings.evidence_dir -- the row is the durable
    # record even after the file itself is cleaned up by retention (see
    # app/pipeline/evidence.py); never null this out on expiry, only the
    # file disappears. Mirrors Track.thumb_path's same "reference survives,
    # bytes are retention-bounded" split in the Investigate feature.
    op.add_column("sightings", sa.Column("evidence_path", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("sightings", "evidence_path")
    op.drop_column("sightings", "model_version")
    op.drop_column("sightings", "bbox")
    op.drop_column("sightings", "raw_ocr_text")
