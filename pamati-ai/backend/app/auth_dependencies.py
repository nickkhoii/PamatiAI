"""Revocable bearer sessions and deny-by-default resource authorization."""

import hashlib
import secrets
from datetime import timedelta
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models import (
    AuditLog,
    AuthRateLimit,
    AuthSession,
    ConsentRecord,
    ReviewerAssignment,
    ReviewerProfile,
    User,
    identifier,
    utcnow,
)
from app.security import Principal, Role, permitted

DB = Annotated[Session, Depends(get_session)]
hasher = PasswordHasher()
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))
bearer = HTTPBearer(auto_error=False)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def verify(password: str, encoded: str) -> bool:
    try:
        return hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def audit(db, actor, action, resource_type="user", resource_id=None, outcome="success"):
    db.add(
        AuditLog(
            actor_id=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id if resource_id and len(resource_id) <= 36 else None,
            outcome=outcome,
        )
    )


def deny(db, actor, action, status=403, resource_id=None):
    audit(db, actor, action, resource_id=resource_id, outcome="denied")
    db.commit()
    raise HTTPException(
        status, "Access denied" if status == 403 else "Invalid credentials or token"
    )


def throttle(db, request: Request, action: str, subject: str = "", *, ip_limit=30, subject_limit=8):
    # Persistent counters are shared by all workers. Do not trust forwarded IP headers.
    keys = [f"{action}:ip:{request.client.host if request.client else 'unknown'}"]
    if subject:
        keys.append(f"{action}:subject:{subject}")
    for raw in keys:
        key = digest(raw)
        values = {"key": key, "window_start": utcnow(), "attempts": 0}
        if db.bind.dialect.name == "mysql":
            from sqlalchemy.dialects.mysql import insert

            stmt = insert(AuthRateLimit).values(**values)
            db.execute(stmt.on_duplicate_key_update(key=stmt.inserted.key))
        else:
            from sqlalchemy.dialects.sqlite import insert

            db.execute(insert(AuthRateLimit).values(**values).on_conflict_do_nothing())
        row = db.scalar(select(AuthRateLimit).where(AuthRateLimit.key == key).with_for_update())
        if row.window_start < utcnow() - timedelta(minutes=15):
            row.window_start, row.attempts = utcnow(), 0
        row.attempts += 1
        limit = ip_limit if ":ip:" in raw else subject_limit
        if row.attempts > limit:
            audit(db, None, "auth.rate_limited", outcome="denied")
            db.commit()
            raise HTTPException(429, "Too many attempts", headers={"Retry-After": "900"})
    db.commit()


def lock_user(db, user_id):
    return db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def revoke_sessions(db, user_id):
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


def issue_session(db, user, *, family_id=None, expires_at=None):
    settings = get_settings()
    access, refresh = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
    row = AuthSession(
        user_id=user.id,
        family_id=family_id or identifier(),
        access_hash=digest(access),
        refresh_hash=digest(refresh),
        access_expires_at=utcnow() + timedelta(minutes=settings.access_token_minutes),
        expires_at=expires_at or utcnow() + timedelta(days=settings.session_days),
    )
    db.add(row)
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": settings.access_token_minutes * 60,
    }


def authenticated_user(
    request: Request,
    db: DB,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if credentials is None:
        deny(db, None, "auth.missing", 401)
    auth = db.scalar(
        select(AuthSession).where(AuthSession.access_hash == digest(credentials.credentials))
    )
    if auth is None:
        deny(db, None, "auth.invalid", 401)
    # All credential and administrative changes serialize on the user row.
    user = lock_user(db, auth.user_id)
    db.refresh(auth, with_for_update=True)
    if (
        not user
        or not user.is_active
        or user.deleted_at
        or auth.revoked_at
        or auth.consumed_at
        or auth.access_expires_at <= utcnow()
        or auth.expires_at <= utcnow()
    ):
        deny(db, auth.user_id, "auth.expired", 401)
    request.state.auth_session = auth
    return user


CurrentUser = Annotated[User, Depends(authenticated_user)]


def require_role(*roles: str):
    def dependency(db: DB, user: CurrentUser):
        if not {r.code for r in user.roles}.intersection(roles):
            deny(db, user.id, "authorization.role")
        return user

    return dependency


def require_permission(permission: str):
    def dependency(db: DB, user: CurrentUser):
        if not any(permission in {p.code for p in r.permissions} for r in user.roles):
            deny(db, user.id, "authorization.permission")
        return user

    return dependency


def authorize_student(db, user, permission, student_id):
    from app.persistence import ConsentDenied, lock_student

    try:
        lock_student(db, student_id)
    except ConsentDenied:
        deny(db, user.id, "authorization.resource", resource_id=student_id)
    assigned = (
        db.scalar(
            select(ReviewerAssignment.id).where(
                ReviewerAssignment.student_id == student_id,
                ReviewerAssignment.reviewer_id == user.id,
                ReviewerAssignment.revoked_at.is_(None),
            )
            .with_for_update()
        )
        is not None
    )
    reviewer = db.get(ReviewerProfile, user.id, populate_existing=True)
    assigned = assigned and reviewer is not None and reviewer.deleted_at is None
    consent = db.scalar(
        select(ConsentRecord)
        .where(ConsentRecord.student_id == student_id)
        .order_by(ConsentRecord.version.desc())
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    active = bool(consent and not consent.withdrawn_at and consent.reviewer_access)
    for role in user.roles:
        if permission not in {p.code for p in role.permissions}:
            continue
        try:
            code = Role(role.code)
        except ValueError:
            continue
        if permitted(
            Principal(user.id, code),
            permission,
            student_id=student_id,
            assigned=assigned,
            consent_active=active,
        ):
            return
    deny(db, user.id, "authorization.resource", resource_id=student_id)
