"""database-enforced append-only audit events

Revision ID: 202608311800
Revises: 202608311700
Create Date: 2026-08-31
"""

from alembic import op

revision = "202608311800"
down_revision = "202608311700"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION reject_audit_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            -- The audit actor FK deliberately uses ON DELETE SET NULL so a
            -- removed account cannot block retention of its history. Permit
            -- precisely that database-managed reference cleanup, while
            -- rejecting every content change and all deletes.
            IF TG_OP = 'UPDATE'
               AND OLD.actor_user_id IS NOT NULL
               AND NEW.actor_user_id IS NULL
               AND NEW.actor_email IS NOT DISTINCT FROM OLD.actor_email
               AND NEW.action IS NOT DISTINCT FROM OLD.action
               AND NEW.target_type IS NOT DISTINCT FROM OLD.target_type
               AND NEW.target_id IS NOT DISTINCT FROM OLD.target_id
               AND NEW.department IS NOT DISTINCT FROM OLD.department
               AND NEW.result IS NOT DISTINCT FROM OLD.result
               AND NEW.details::jsonb IS NOT DISTINCT FROM OLD.details::jsonb
               AND NEW.occurred_at IS NOT DISTINCT FROM OLD.occurred_at
               AND NEW.id IS NOT DISTINCT FROM OLD.id THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'audit_events are append-only';
        END;
        $$;

        CREATE TRIGGER trg_audit_events_append_only
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION reject_audit_event_mutation()")
