"""Optional student self-reported check-ins."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0009_dashboards"
down_revision = "0008_safety_workflow"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "wellbeing_check_ins",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")),
        sa.Column(
            "student_id",
            sa.String(36),
            sa.ForeignKey("student_profiles.user_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("retention_snapshot", sa.JSON(), nullable=True),
        sa.Column(
            "feeling",
            sa.Enum(
                "comfortable",
                "mixed",
                "difficult",
                "prefer_not_to_say",
                name="check_in_feeling",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index("ix_wellbeing_check_ins_student_id", "wellbeing_check_ins", ["student_id"])
    op.create_index("ix_wellbeing_check_ins_deleted_at", "wellbeing_check_ins", ["deleted_at"])


def downgrade():
    op.drop_table("wellbeing_check_ins")
