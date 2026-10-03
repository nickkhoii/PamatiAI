"""Authentication sessions, institutional onboarding and request queues."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "0005_authentication"
down_revision = "0004_evidence_integrity"
branch_labels = None
depends_on = None

OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}
DT = sa.DateTime().with_variant(DATETIME(fsp=6), "mysql")


def entity():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", DT, nullable=False),
    ]


def ref(name, target, nullable=False):
    return sa.Column(
        name,
        sa.String(36),
        sa.ForeignKey(target, ondelete="RESTRICT"),
        nullable=nullable,
    )


def upgrade():
    op.add_column("users", sa.Column("email_verified_at", DT, nullable=True))
    # Existing provisioned accounts are trusted by the previous institutional seed process.
    op.execute("UPDATE users SET email_verified_at = created_at")
    op.create_table(
        "auth_sessions",
        *entity(),
        ref("user_id", "users.id"),
        sa.Column("family_id", sa.String(36), nullable=False),
        sa.Column("access_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("refresh_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("access_expires_at", DT, nullable=False),
        sa.Column("expires_at", DT, nullable=False),
        sa.Column("consumed_at", DT),
        sa.Column("revoked_at", DT),
        **OPTIONS,
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_family_id", "auth_sessions", ["family_id"])
    op.create_table(
        "auth_challenges",
        *entity(),
        ref("user_id", "users.id", True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("role_code", sa.String(40)),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", DT, nullable=False),
        sa.Column("consumed_at", DT),
        **OPTIONS,
    )
    op.create_index("ix_auth_challenges_user_id", "auth_challenges", ["user_id"])
    op.create_table(
        "auth_deliveries",
        *entity(),
        ref("challenge_id", "auth_challenges.id"),
        sa.Column("encrypted_payload", sa.Text),
        sa.Column("sent_at", DT),
        sa.Column("attempts", sa.Integer, nullable=False),
        **OPTIONS,
    )
    op.create_index(
        "ix_auth_deliveries_challenge_id", "auth_deliveries", ["challenge_id"]
    )
    op.create_table(
        "auth_rate_limits",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("window_start", DT, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        **OPTIONS,
    )
    op.create_table(
        "support_requests",
        *entity(),
        ref("student_id", "student_profiles.user_id"),
        sa.Column("status", sa.String(20), nullable=False),
        **OPTIONS,
    )
    op.create_index(
        "ix_support_requests_student_id", "support_requests", ["student_id"]
    )
    op.create_table(
        "data_control_requests",
        *entity(),
        ref("student_id", "student_profiles.user_id"),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        **OPTIONS,
    )
    op.create_index(
        "ix_data_control_requests_student_id", "data_control_requests", ["student_id"]
    )
    op.execute("UPDATE roles SET code = 'ADMIN' WHERE code = 'SYSTEM_ADMINISTRATOR'")
    op.execute(
        "INSERT INTO permissions (id, created_at, code, description) "
        "SELECT '651f7d75-4410-4d51-a220-b756634af0f9', CURRENT_TIMESTAMP, "
        "'support:request', 'Request human support' WHERE NOT EXISTS "
        "(SELECT 1 FROM permissions WHERE code = 'support:request')"
    )
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code = 'support:request' "
        "WHERE r.code = 'STUDENT' AND NOT EXISTS (SELECT 1 FROM role_permissions rp "
        "WHERE rp.role_id = r.id AND rp.permission_id = p.id)"
    )


def downgrade():
    op.execute(
        "DELETE rp FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id "
        "WHERE p.code = 'support:request'"
    )
    op.execute("DELETE FROM permissions WHERE code = 'support:request'")
    op.execute("UPDATE roles SET code = 'SYSTEM_ADMINISTRATOR' WHERE code = 'ADMIN'")
    for table in [
        "data_control_requests",
        "support_requests",
        "auth_rate_limits",
        "auth_deliveries",
        "auth_challenges",
        "auth_sessions",
    ]:
        op.drop_table(table)
    op.drop_column("users", "email_verified_at")
