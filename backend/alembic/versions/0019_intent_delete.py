"""Allow account deletion to remove provisioning intents."""
from alembic import op

revision = '0019_intent_delete'
down_revision = '0018_provisioning_intents'
branch_labels = depends_on = None


def upgrade():
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reink_app') THEN
            GRANT DELETE ON provisioning_intents TO reink_app;
        END IF;
    END $$""")


def downgrade():
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reink_app') THEN
            REVOKE DELETE ON provisioning_intents FROM reink_app;
        END IF;
    END $$""")
