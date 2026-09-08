"""Polymorphic alerts: allow non-watchlist (suspicious-activity) alerts

Revision ID: 202608312000
Revises: 202608311900
Create Date: 2026-08-31

(Renumbered during the webrtc-whep-relay merge: this migration was
authored against 202608292336, a much earlier point in the chain, and
its original revision id 202608311200 collided with the already-merged
202608311200_catalogue_sources.py. Content is unchanged from what
merged into main; only revision/down_revision moved to make this the
new single head, chained after 202608311900_sighting_evidence.py.)

Adds an `alert_type` discriminator plus self-contained `label`/`severity`
columns, and relaxes `sighting_id`/`watchlist_entry_id` to nullable, so a
person-based suspicious-activity detection (best.pt) can raise an alert into
the same table and the same Alerts view as the ANPR watchlist path -- which
has neither a plate sighting nor a watchlist entry to point at. Existing
watchlist alerts are unaffected: alert_type defaults to 'watchlist' and both
FKs stay populated for them.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "202608312000"
down_revision = "202608311900"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "alerts",
        sa.Column("alert_type", sa.Text(), nullable=False, server_default="watchlist"),
    )
    op.add_column("alerts", sa.Column("label", sa.Text(), nullable=True))
    op.add_column("alerts", sa.Column("severity", sa.Text(), nullable=True))
    op.alter_column("alerts", "sighting_id", existing_type=sa.BigInteger(), nullable=True)
    op.alter_column("alerts", "watchlist_entry_id", existing_type=sa.Integer(), nullable=True)
    op.create_check_constraint(
        "ck_alerts_type", "alerts", "alert_type IN ('watchlist', 'suspicious')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_alerts_type", "alerts", type_="check")
    # Rows added by the suspicious path have null FKs, so restoring NOT NULL
    # would fail against real data -- clear them first. They are the only
    # rows this migration made possible, so dropping them is the honest
    # inverse of the upgrade.
    op.execute("DELETE FROM alerts WHERE alert_type <> 'watchlist'")
    op.alter_column("alerts", "watchlist_entry_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("alerts", "sighting_id", existing_type=sa.BigInteger(), nullable=False)
    op.drop_column("alerts", "severity")
    op.drop_column("alerts", "label")
    op.drop_column("alerts", "alert_type")
