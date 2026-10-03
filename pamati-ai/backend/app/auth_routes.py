"""Authentication lifecycle. Recovery secrets are delivered only through an encrypted outbox."""

import json
import re
import secrets
from datetime import timedelta
from typing import Annotated, Literal
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.auth_dependencies import (
    DB,
    DUMMY_HASH,
    CurrentUser,
    audit,
    deny,
    digest,
    hasher,
    issue_session,
    lock_user,
    require_permission,
    require_role,
    revoke_sessions,
    throttle,
    verify,
)
from app.config import get_settings
from app.models import (
    AuthChallenge,
    AuthDelivery,
    AuthSession,
    ReviewerProfile,
    Role,
    StudentProfile,
    User,
    utcnow,
)

router = APIRouter(prefix="/api/v1", tags=["authentication"])
Admin = Annotated[User, Depends(require_role("ADMIN"))]
AccountManager = Annotated[User, Depends(require_permission("accounts:manage"))]
GENERIC = {"message": "If eligible, instructions will be sent to the registered email address."}


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmailInput(Input):
    email: str = Field(max_length=254)

    @field_validator("email")
    @classmethod
    def email_valid(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value) or any(c in value for c in "\r\n"):
            raise ValueError("Invalid email")
        return value


class LoginInput(EmailInput):
    password: str = Field(min_length=1, max_length=128)


class Registration(EmailInput):
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=15, max_length=128)
    invitation_token: str | None = Field(default=None, max_length=256)


class TokenInput(Input):
    token: str = Field(min_length=32, max_length=256)


class ResetInput(TokenInput):
    password: str = Field(min_length=15, max_length=128)


class ChangePassword(Input):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=15, max_length=128)


class ProfileInput(Input):
    display_name: str = Field(min_length=1, max_length=120)


class InvitationInput(EmailInput):
    role: Literal["STUDENT", "COUNSELOR", "ADMIN"]


class AccountState(Input):
    is_active: bool


def public_profile(user):
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "roles": sorted(r.code for r in user.roles),
        "is_active": user.is_active,
    }


def delivery_cipher():
    settings = get_settings()
    try:
        cipher = Fernet(settings.auth_delivery_key.encode())
    except (ValueError, TypeError):
        raise HTTPException(503, "Authentication email delivery is not configured") from None
    url = urlparse(settings.auth_public_url)
    if not url.netloc or (settings.environment != "development" and url.scheme != "https"):
        raise HTTPException(503, "Authentication delivery URL is not configured")
    if not settings.smtp_host or not settings.smtp_from:
        raise HTTPException(503, "Authentication email delivery is not configured")
    return cipher


def queue_challenge(db, email, purpose, *, user_id=None, role=None):
    cipher = delivery_cipher()
    token = secrets.token_urlsafe(48)
    # A new request invalidates previous links of the same type.
    db.execute(
        update(AuthChallenge)
        .where(
            AuthChallenge.email == email,
            AuthChallenge.purpose == purpose,
            AuthChallenge.consumed_at.is_(None),
        )
        .values(consumed_at=utcnow())
    )
    challenge = AuthChallenge(
        email=email,
        user_id=user_id,
        purpose=purpose,
        role_code=role,
        token_hash=digest(token),
        expires_at=utcnow() + timedelta(minutes=30 if purpose == "reset" else 1440),
    )
    db.add(challenge)
    db.flush()
    payload = json.dumps({"email": email, "purpose": purpose, "token": token})
    db.add(
        AuthDelivery(
            challenge_id=challenge.id, encrypted_payload=cipher.encrypt(payload.encode()).decode()
        )
    )
    return challenge


def find_challenge(db, token, purpose):
    row = db.scalar(
        select(AuthChallenge)
        .where(AuthChallenge.token_hash == digest(token), AuthChallenge.purpose == purpose)
        .with_for_update()
    )
    if not row or row.consumed_at or row.expires_at <= utcnow():
        deny(db, None, "auth.challenge_invalid", 400)
    return row


@router.post("/auth/register", status_code=202)
def register(body: Registration, request: Request, db: DB):
    throttle(db, request, "register", body.email)
    delivery_cipher()
    settings = get_settings()
    role_code = "STUDENT"
    invitation = None
    if body.invitation_token:
        invitation = find_challenge(db, body.invitation_token, "invite")
        if invitation.email != body.email:
            deny(db, None, "auth.invitation_mismatch", 400)
        role_code = invitation.role_code
    elif not settings.public_registration_enabled:
        raise HTTPException(403, "Institutional invitation is required")
    elif (
        settings.institutional_domains
        and body.email.split("@")[1] not in settings.institutional_domains
    ):
        raise HTTPException(403, "Institutional email is required")
    encoded = hasher.hash(body.password)
    if db.scalar(select(User).where(User.email == body.email)):
        audit(db, None, "auth.registration_duplicate", outcome="denied")
        db.commit()
        return GENERIC
    role = db.scalar(select(Role).where(Role.code == role_code))
    if not role:
        raise HTTPException(503, "Institutional roles have not been provisioned")
    user = User(
        email=body.email,
        display_name=body.display_name,
        password_hash=encoded,
        is_active=bool(invitation),
        email_verified_at=utcnow() if invitation else None,
    )
    user.roles = [role]
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return GENERIC
    if role_code == "STUDENT":
        db.add(StudentProfile(user_id=user.id))
    elif role_code == "COUNSELOR":
        db.add(ReviewerProfile(user_id=user.id))
    if invitation:
        invitation.consumed_at = utcnow()
    else:
        queue_challenge(db, user.email, "activate", user_id=user.id)
    audit(db, user.id, "auth.register", resource_id=user.id)
    db.commit()
    return GENERIC


@router.post("/auth/login")
def login(body: LoginInput, request: Request, db: DB, response: Response):
    throttle(db, request, "login", body.email)
    found = db.scalar(select(User.id).where(User.email == body.email))
    user = lock_user(db, found) if found else None
    valid = verify(body.password, user.password_hash if user else DUMMY_HASH)
    if not valid or not user or not user.is_active or user.deleted_at:
        deny(db, user.id if user else None, "auth.login", 401)
    if hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hasher.hash(body.password)
    tokens = issue_session(db, user)
    audit(db, user.id, "auth.login", resource_id=user.id)
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return tokens


@router.post("/auth/refresh")
def refresh(body: TokenInput, request: Request, db: DB, response: Response):
    throttle(db, request, "refresh")
    row = db.scalar(select(AuthSession).where(AuthSession.refresh_hash == digest(body.token)))
    if not row:
        deny(db, None, "auth.refresh_invalid", 401)
    user = lock_user(db, row.user_id)
    db.refresh(row, with_for_update=True)
    if row.consumed_at:
        db.execute(
            update(AuthSession)
            .where(AuthSession.family_id == row.family_id)
            .values(revoked_at=utcnow())
        )
        deny(db, row.user_id, "auth.refresh_replay", 401)
    if row.revoked_at or row.expires_at <= utcnow() or not user.is_active or user.deleted_at:
        deny(db, row.user_id, "auth.refresh_invalid", 401)
    row.consumed_at = utcnow()
    tokens = issue_session(db, user, family_id=row.family_id, expires_at=row.expires_at)
    audit(db, user.id, "auth.refresh")
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return tokens


@router.post("/auth/logout", status_code=204)
def logout(request: Request, db: DB, user: CurrentUser):
    family = request.state.auth_session.family_id
    db.execute(
        update(AuthSession).where(AuthSession.family_id == family).values(revoked_at=utcnow())
    )
    audit(db, user.id, "auth.logout")
    db.commit()


@router.post("/auth/logout-all", status_code=204)
def logout_all(db: DB, user: CurrentUser):
    revoke_sessions(db, user.id)
    audit(db, user.id, "auth.logout_all")
    db.commit()


@router.post("/auth/forgot-password", status_code=202)
def forgot_password(body: EmailInput, request: Request, db: DB):
    throttle(db, request, "forgot", body.email)
    delivery_cipher()
    user = db.scalar(select(User).where(User.email == body.email))
    if user and user.is_active and not user.deleted_at:
        queue_challenge(db, user.email, "reset", user_id=user.id)
    audit(db, None, "auth.recovery_requested")
    db.commit()
    return GENERIC


@router.post("/auth/reset-password", status_code=204)
def reset_password(body: ResetInput, request: Request, db: DB):
    throttle(db, request, "reset")
    # Read user ID first; lock user before challenge to keep consistent lock ordering.
    candidate = db.scalar(
        select(AuthChallenge).where(
            AuthChallenge.token_hash == digest(body.token), AuthChallenge.purpose == "reset"
        )
    )
    if not candidate:
        deny(db, None, "auth.reset_invalid", 400)
    user = lock_user(db, candidate.user_id)
    db.expire(candidate)
    challenge = find_challenge(db, body.token, "reset")
    if not user or not user.is_active or user.deleted_at:
        deny(db, None, "auth.reset_invalid", 400)
    user.password_hash = hasher.hash(body.password)
    challenge.consumed_at = utcnow()
    revoke_sessions(db, user.id)
    audit(db, user.id, "auth.password_reset")
    db.commit()


@router.post("/auth/activate", status_code=204)
def activate(body: TokenInput, request: Request, db: DB):
    throttle(db, request, "activate")
    candidate = db.scalar(
        select(AuthChallenge).where(
            AuthChallenge.token_hash == digest(body.token), AuthChallenge.purpose == "activate"
        )
    )
    if not candidate:
        deny(db, None, "auth.activation_invalid", 400)
    user = lock_user(db, candidate.user_id)
    db.expire(candidate)
    challenge = find_challenge(db, body.token, "activate")
    if not user or user.deleted_at or user.email_verified_at:
        deny(db, None, "auth.activation_invalid", 400)
    user.is_active, user.email_verified_at = True, utcnow()
    challenge.consumed_at = utcnow()
    audit(db, user.id, "auth.activate")
    db.commit()


@router.post("/auth/change-password", status_code=204)
def change_password(body: ChangePassword, request: Request, db: DB, user: CurrentUser):
    # Throttle commits release the dependency's lock; acquire it again before mutation.
    throttle(db, request, "change_password", user.id)
    user = lock_user(db, user.id)
    db.refresh(user)
    if not user.is_active or not verify(body.current_password, user.password_hash):
        deny(db, user.id, "auth.password_change", 401)
    user.password_hash = hasher.hash(body.new_password)
    revoke_sessions(db, user.id)
    db.execute(
        update(AuthChallenge)
        .where(AuthChallenge.user_id == user.id, AuthChallenge.purpose == "reset")
        .values(consumed_at=utcnow())
    )
    audit(db, user.id, "auth.password_change")
    db.commit()


@router.get("/me")
def profile(user: CurrentUser):
    return public_profile(user)


@router.patch("/me")
def update_profile(body: ProfileInput, db: DB, user: CurrentUser):
    user.display_name = body.display_name
    audit(db, user.id, "account.profile_updated", resource_id=user.id)
    db.commit()
    return public_profile(user)


@router.post("/admin/invitations", status_code=202)
def invite(body: InvitationInput, db: DB, admin: Admin, manager: AccountManager):
    if db.scalar(select(User.id).where(User.email == body.email)):
        raise HTTPException(409, "Account already exists")
    row = queue_challenge(db, body.email, "invite", role=body.role)
    audit(db, admin.id, "account.invited", "invitation", row.id)
    db.commit()
    return {"id": row.id, "email": row.email, "role": row.role_code}


@router.get("/admin/users")
def users(db: DB, admin: Admin, manager: AccountManager, offset: int = 0):
    return [
        public_profile(u)
        for u in db.scalars(
            select(User)
            .where(User.deleted_at.is_(None))
            .order_by(User.id)
            .offset(max(0, offset))
            .limit(100)
        )
    ]


@router.patch("/admin/users/{user_id}/activation")
def account_state(user_id: str, body: AccountState, db: DB, admin: Admin, manager: AccountManager):
    user = lock_user(db, user_id)
    if not user or user.deleted_at:
        raise HTTPException(404, "Account not found")
    if body.is_active and not user.email_verified_at and not user.is_development_account:
        raise HTTPException(409, "Email verification is required")
    if user.id == admin.id and not body.is_active:
        raise HTTPException(409, "Cannot deactivate your own administrative account")
    user.is_active = body.is_active
    revoke_sessions(db, user.id)
    db.execute(
        update(AuthChallenge).where(AuthChallenge.user_id == user.id).values(consumed_at=utcnow())
    )
    audit(
        db,
        admin.id,
        "account.activated" if body.is_active else "account.deactivated",
        resource_id=user.id,
    )
    db.commit()
    return public_profile(user)


class RoleInput(Input):
    role: Literal["STUDENT", "COUNSELOR", "ADMIN"]


@router.patch("/admin/users/{user_id}/role")
def account_role(user_id: str, body: RoleInput, db: DB, admin: Admin, manager: AccountManager):
    if user_id == admin.id:
        raise HTTPException(409, "Use another administrator to change your role")
    user = lock_user(db, user_id)
    if not user or user.deleted_at:
        raise HTTPException(404, "Account not found")
    role = db.scalar(select(Role).where(Role.code == body.role))
    if not role:
        raise HTTPException(503, "Institutional roles have not been provisioned")
    user.roles = [role]
    if body.role == "STUDENT" and not user.student_profile:
        db.add(StudentProfile(user_id=user.id))
    if body.role == "COUNSELOR" and not user.reviewer_profile:
        db.add(ReviewerProfile(user_id=user.id))
    revoke_sessions(db, user.id)
    db.execute(
        update(AuthChallenge).where(AuthChallenge.user_id == user.id).values(consumed_at=utcnow())
    )
    audit(db, admin.id, "account.role_changed", resource_id=user.id)
    db.commit()
    return public_profile(user)


@router.post("/auth/logout-session", status_code=204)
def logout_session(body: TokenInput, request: Request, db: DB):
    """Allow a browser to end a session even after its short access token expires."""
    throttle(db, request, "logout_session")
    row = db.scalar(select(AuthSession).where(AuthSession.refresh_hash == digest(body.token)))
    if row:
        lock_user(db, row.user_id)
        db.execute(
            update(AuthSession)
            .where(AuthSession.family_id == row.family_id)
            .values(revoked_at=utcnow())
        )
        audit(db, row.user_id, "auth.logout")
        db.commit()
