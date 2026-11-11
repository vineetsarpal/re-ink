"""Retain creator and work-domain trial claims independently of tenant data."""
from alembic import op
import sqlalchemy as sa

revision = '0017_trial_eligibility'
down_revision = '0016_cleanup_backoff'
branch_labels = depends_on = None


def upgrade():
    op.add_column('extraction_quota_org', sa.Column('trial_eligible', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_table('trial_users', sa.Column('user_hash', sa.String(64), primary_key=True),
                    sa.Column('org_id', sa.String(255), nullable=False))
    op.create_table('trial_domains', sa.Column('domain', sa.String(255), primary_key=True),
                    sa.Column('org_id', sa.String(255), nullable=False))
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reink_app') THEN
            GRANT SELECT, INSERT ON trial_users, trial_domains TO reink_app;
        END IF;
    END $$""")
    op.alter_column('extraction_quota_org', 'trial_eligible', server_default=sa.false())


def downgrade():
    op.drop_table('trial_domains')
    op.drop_table('trial_users')
    op.drop_column('extraction_quota_org', 'trial_eligible')
