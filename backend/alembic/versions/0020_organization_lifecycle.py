"""Track organization closure and resumable purge progress."""
from alembic import op
import sqlalchemy as sa

revision = '0020_organization_lifecycle'
down_revision = '0019_intent_delete'
branch_labels = depends_on = None


def upgrade():
    op.create_table('organization_lifecycle',
        sa.Column('org_id', sa.String(255), primary_key=True),
        sa.Column('status', sa.String(16), nullable=False, server_default='active'),
        sa.Column('closure_requested_at', sa.DateTime(timezone=True)),
        sa.Column('purge_after', sa.DateTime(timezone=True)),
        sa.Column('requested_by_hash', sa.String(64)),
        sa.Column('purge_step', sa.String(32)),
        sa.Column('purge_attempts', sa.Integer, nullable=False, server_default='0'),
        sa.Column('last_purge_error', sa.Text),
        sa.CheckConstraint("status IN ('active', 'closing', 'purged')"),
        sa.CheckConstraint('purge_attempts >= 0'),
        sa.CheckConstraint("status = 'active' OR (closure_requested_at IS NOT NULL AND purge_after IS NOT NULL AND requested_by_hash IS NOT NULL)"))
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reink_app') THEN
            GRANT SELECT, INSERT, UPDATE ON organization_lifecycle TO reink_app;
        END IF;
    END $$""")


def downgrade():
    op.drop_table('organization_lifecycle')
