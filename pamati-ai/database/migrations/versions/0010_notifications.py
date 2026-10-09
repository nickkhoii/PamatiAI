"""Owner-scoped in-app notification receipts; content remains in its original records."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0010_notifications"
down_revision = "0009_dashboards"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("notification_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_key", sa.String(100), nullable=False),
        sa.UniqueConstraint("user_id", "event_key"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4", mysql_collate="utf8mb4_0900_ai_ci")
    op.create_index("ix_notification_receipts_user_id", "notification_receipts", ["user_id"])


def downgrade():
    op.drop_table("notification_receipts")
