"""Conversational turn idempotency and generated response provenance."""

import sqlalchemy as sa
from alembic import op

revision = "0007_conversation"
down_revision = "0006_consent_privacy"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("messages", sa.Column("request_id", sa.String(36), nullable=True))
    op.add_column("messages", sa.Column("generation", sa.JSON(), nullable=True))
    op.create_unique_constraint("uq_messages_request_id", "messages", ["request_id"])


def downgrade():
    op.drop_constraint("uq_messages_request_id", "messages", type_="unique")
    op.drop_column("messages", "generation")
    op.drop_column("messages", "request_id")
