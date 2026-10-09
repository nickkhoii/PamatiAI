"""Run from backend: python -m app.database_commands init|seed [--development-accounts]."""

import argparse
import os
import re
from pathlib import Path

from alembic import command
from alembic.config import Config
from argon2 import PasswordHasher
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Permission, ReviewerProfile, Role, StudentProfile, SystemSetting, User
from app.retention import RetentionPolicy

ROLE_PERMISSIONS = {
    "STUDENT": {"consent:manage", "conversation:manage", "history:read", "privacy:manage", "support:request"},
    "COUNSELOR": {"history:read", "review:manage"},
    "ADMIN": {"accounts:manage", "configuration:manage"},
}
DEVELOPMENT_EMAILS = {
    "STUDENT": "dev.student@pamati.example",
    "COUNSELOR": "dev.reviewer@pamati.example",
    "ADMIN": "dev.admin@pamati.example",
}


def initialize_database():
    """Idempotent provisioning; use an administrative DATABASE_URL only for this command."""
    url = make_url(get_settings().database_url)
    database = url.database
    if not database or not re.fullmatch(r"[A-Za-z0-9_]{1,64}", database):
        raise ValueError("Database name must contain only letters, digits and underscores")
    admin_engine = create_engine(url.set(database=None), hide_parameters=True)
    try:
        with admin_engine.begin() as connection:
            connection.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{database}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
                )
            )
    finally:
        admin_engine.dispose()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")


def seed(session: Session, *, development_accounts=False, password=None, environment=None):
    environment = environment or get_settings().environment
    if development_accounts and environment != "development":
        raise ValueError("Development accounts are prohibited outside development")
    if development_accounts and (not password or len(password) < 16):
        raise ValueError("Set DEV_SEED_PASSWORD to at least 16 characters")
    permissions = {}
    for code in sorted(set.union(*ROLE_PERMISSIONS.values())):
        permission = session.scalar(select(Permission).where(Permission.code == code))
        if permission is None:
            permission = Permission(code=code, description=f"Resource-scoped {code}")
            session.add(permission)
        permissions[code] = permission
    session.flush()

    for code, grants in ROLE_PERMISSIONS.items():
        role = session.scalar(select(Role).where(Role.code == code))
        if role is None:
            role = Role(code=code, description=f"PamatiAI {code}")
            session.add(role)
            role.permissions = [permissions[permission] for permission in sorted(grants)]
        elif {permission.code for permission in role.permissions} != grants:
            raise ValueError("Existing role grants differ; reconcile them explicitly")
        session.flush()
        if not development_accounts:
            continue
        email = DEVELOPMENT_EMAILS[code]
        user = session.scalar(select(User).where(User.email == email))
        if user is not None:
            if not user.is_development_account:
                raise ValueError("Refusing to alter a non-development account")
            continue  # Never reset existing passwords, profiles or grants.
        user = User(
            email=email,
            display_name=f"[DEVELOPMENT ONLY] {code}",
            password_hash=PasswordHasher().hash(password),
            is_development_account=True,
        )
        user.roles = [role]
        session.add(user)
        session.flush()
        if code == "STUDENT":
            session.add(StudentProfile(user_id=user.id))
        elif code == "COUNSELOR":
            session.add(ReviewerProfile(user_id=user.id, professional_title="Development reviewer"))
    if session.get(SystemSetting, "raw_media_retention") is None:
        session.add(
            SystemSetting(
                key="raw_media_retention",
                value={"enabled": False},
                description="Raw media requires this gate, environment opt-in and consent",
            )
        )
    if session.get(SystemSetting, "data_retention") is None:
        session.add(SystemSetting(key="data_retention", value=RetentionPolicy().model_dump(),
            description="Configured retention limits; time-limited holds are separately documented"))
    session.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "seed"])
    parser.add_argument("--development-accounts", action="store_true")
    args = parser.parse_args()
    if args.action == "init":
        if args.development_accounts:
            parser.error("Use seed separately to create development accounts")
        initialize_database()
        print("Database initialized and migrations applied")
        return
    engine = create_engine(get_settings().database_url, hide_parameters=True)
    try:
        with Session(engine) as session, session.begin():
            seed(
                session,
                development_accounts=args.development_accounts,
                password=os.environ.get("DEV_SEED_PASSWORD"),
            )
        print(
            "Development accounts seeded"
            if args.development_accounts
            else "Roles and permissions seeded"
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
