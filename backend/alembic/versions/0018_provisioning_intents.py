"""Persist resumable organization provisioning."""
from alembic import op
import sqlalchemy as sa

revision = '0018_provisioning_intents'
down_revision = '0017_trial_eligibility'
branch_labels = depends_on = None


def upgrade():
    op.create_table('provisioning_intents',
        sa.Column('user_id', sa.String(255), primary_key=True),
        sa.Column('intent_id', sa.String(36), nullable=False, unique=True),
        sa.Column('state', sa.String(16), nullable=False, server_default='pending'),
        sa.Column('org_id', sa.String(255)),
        sa.Column('organization_name', sa.String(320)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("state IN ('pending', 'org_created', 'completed')"),
        sa.CheckConstraint("state = 'pending' OR org_id IS NOT NULL"))
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reink_app') THEN
            GRANT SELECT, INSERT, UPDATE ON provisioning_intents TO reink_app;
        END IF;
    END $$""")


def downgrade():
    op.drop_table('provisioning_intents')
