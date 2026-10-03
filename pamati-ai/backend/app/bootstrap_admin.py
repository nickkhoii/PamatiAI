"""One-time institutional administrator bootstrap; never creates default credentials.

Set BOOTSTRAP_ADMIN_EMAIL, BOOTSTRAP_ADMIN_PASSWORD and BOOTSTRAP_ADMIN_NAME in
this process, then run python -m app.bootstrap_admin from backend.
"""

import os

from sqlalchemy import select

from app.auth_dependencies import audit, hasher
from app.auth_routes import EmailInput
from app.database_commands import seed
from app.db import SessionLocal
from app.models import Role, User, utcnow


def bootstrap(db, email, password, display_name):
    email = EmailInput(email=email).email
    if not 15 <= len(password) <= 128 or not 1 <= len(display_name) <= 120:
        raise ValueError("Provide a strong password and a display name")
    if db.scalar(select(User.id).where(User.email == email)):
        raise ValueError("Account exists; bootstrap never modifies existing accounts")
    if db.scalar(select(User.id).join(User.roles).where(Role.code == "ADMIN")):
        raise ValueError("An administrator exists; use institutional invitations")
    seed(db)
    role = db.scalar(select(Role).where(Role.code == "ADMIN"))
    user = User(
        email=email,
        display_name=display_name,
        password_hash=hasher.hash(password),
        email_verified_at=utcnow(),
        is_active=True,
        roles=[role],
    )
    db.add(user)
    db.flush()
    audit(db, user.id, "account.admin_bootstrapped", resource_id=user.id)
    return user


if __name__ == "__main__":
    with SessionLocal() as session, session.begin():
        bootstrap(
            session,
            os.environ["BOOTSTRAP_ADMIN_EMAIL"],
            os.environ["BOOTSTRAP_ADMIN_PASSWORD"],
            os.environ["BOOTSTRAP_ADMIN_NAME"],
        )
    print("Institutional administrator provisioned")
