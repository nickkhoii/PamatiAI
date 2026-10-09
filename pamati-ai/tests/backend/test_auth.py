import json
import os
from datetime import timedelta
from functools import lru_cache
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth_dependencies import digest, hasher
from app.config import Settings
from app.consent_policy import POLICY_VERSION
from app.database_commands import seed
from app.db import Base, get_session
from app.main import app
from app.models import (
    AuditLog,
    AuthChallenge,
    AuthDelivery,
    AuthSession,
    ConsentRecord,
    Conversation,
    InteractionSession,
    Message,
    ReviewerAssignment,
    ReviewerProfile,
    Role,
    StudentProfile,
    User,
    utcnow,
)

PASSWORD = "a-long-test-passphrase-123"


@lru_cache
def migrate_test_database(url):
    """Exercise migrations before MySQL fixtures, never create unversioned production tables."""
    from alembic import command
    from alembic.config import Config

    from app.config import get_settings
    old_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        command.upgrade(Config("alembic.ini"), "head")
    finally:
        if old_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_url
        get_settings.cache_clear()


@pytest.fixture(params=["sqlite"] + (["mysql"] if os.environ.get("TEST_DATABASE_URL") else []))
def api(request):
    mysql = request.param == "mysql"
    if mysql:
        url = make_url(os.environ["TEST_DATABASE_URL"])
        if url.drivername != "mysql+pymysql" or not (url.database or "").endswith("_test"):
            pytest.fail("Authentication tests require an isolated MySQL _test database")
        migrate_test_database(os.environ["TEST_DATABASE_URL"])
        engine = create_engine(url)
    else:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        if not mysql:
            connection.execute("PRAGMA foreign_keys=ON")

    if not mysql:
        Base.metadata.create_all(engine)
    settings = Settings(
        auth_delivery_key=Fernet.generate_key().decode(),
        smtp_host="smtp.test.example",
        smtp_from="auth@test.example",
    )
    connection = engine.connect()
    transaction = connection.begin()
    with Session(
        connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    ) as db:
        seed(db)
        roles = {r.code: r for r in db.scalars(select(Role))}
        users, records = {}, {}
        encoded = hasher.hash(PASSWORD)
        for name, role in [
            ("alice", "STUDENT"),
            ("bob", "STUDENT"),
            ("counselor", "COUNSELOR"),
            ("other_counselor", "COUNSELOR"),
            ("admin", "ADMIN"),
        ]:
            user = User(
                email=f"{name}@test.example",
                display_name=name,
                password_hash=encoded,
                email_verified_at=utcnow(),
                roles=[roles[role]],
            )
            db.add(user)
            db.flush()
            users[name] = user
            if role == "STUDENT":
                db.add(StudentProfile(user_id=user.id))
            elif role == "COUNSELOR":
                db.add(ReviewerProfile(user_id=user.id))
        db.flush()
        for name in ["alice", "bob"]:
            student = users[name]
            consent = ConsentRecord(
                student_id=student.id,
                version=1,
                policy_version="v1",
                reviewer_access=True,
                longitudinal_tracking=True,
                text_processing=True,
            )
            conversation = Conversation(student_id=student.id)
            db.add_all([consent, conversation])
            db.flush()
            interaction = InteractionSession(student_id=student.id, conversation_id=conversation.id)
            db.add(interaction)
            db.flush()
            db.add(
                Message(
                    student_id=student.id,
                    session_id=interaction.id,
                    sender="student",
                    sequence_number=0,
                    text_content=f"{name} PRIVATE CONTENT",
                )
            )
            records[name] = conversation
        db.add(
            ReviewerAssignment(
                student_id=users["alice"].id,
                reviewer_id=users["counselor"].id,
                assigned_by=users["admin"].id,
            )
        )
        db.commit()

        def session_override():
            yield db

        app.dependency_overrides[get_session] = session_override
        with (
            patch("app.auth_dependencies.get_settings", return_value=settings),
            patch("app.auth_routes.get_settings", return_value=settings),
            TestClient(app) as client,
        ):
            yield client, db, users, records, settings
        app.dependency_overrides.clear()
    transaction.rollback()
    connection.close()
    engine.dispose()


def login(api, name):
    response = api[0].post(
        "/api/v1/auth/login",
        json={"email": f"{name}@test.example", "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def headers(api, name):
    return {"Authorization": "Bearer " + login(api, name)["access_token"]}


def challenge_token(api, purpose):
    row = api[1].scalar(
        select(AuthDelivery)
        .join(AuthChallenge)
        .where(AuthChallenge.purpose == purpose)
        .order_by(AuthDelivery.created_at.desc())
    )
    return json.loads(
        Fernet(api[4].auth_delivery_key.encode()).decrypt(row.encrypted_payload.encode())
    )["token"]


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/students/{student}/conversations", None),
        ("get", "/conversations/{conversation}", None),
        ("delete", "/conversations/{conversation}", None),
        ("post", "/students/{student}/conversations", None),
        ("get", "/students/{student}/consent", None),
        ("put", "/students/{student}/consent", {"policy_version": "v2"}),
        ("delete", "/students/{student}/consent", None),
        ("get", "/students/{student}/trends", None),
        ("post", "/students/{student}/support-requests", None),
        ("get", "/students/{student}/support-requests", None),
        ("post", "/students/{student}/data-controls", {"kind": "export"}),
        ("get", "/students/{student}/data-controls", None),
        ("get", "/students/{student}/safety-signals", None),
        ("get", "/students/{student}/reviews", None),
        ("get", "/students/{student}/referrals", None),
    ],
)
def test_cross_student_records_are_denied(api, method, path, body):
    client, db, users, records, _ = api
    path = "/api/v1" + path.format(student=users["bob"].id, conversation=records["bob"].id)
    response = client.request(method.upper(), path, json=body, headers=headers(api, "alice"))
    assert response.status_code == 403
    assert "PRIVATE CONTENT" not in response.text
    assert (
        db.scalar(select(AuditLog).where(AuditLog.action == "authorization.resource")).outcome
        == "denied"
    )


@pytest.mark.parametrize("actor", ["other_counselor", "admin"])
@pytest.mark.parametrize(
    "resource", ["conversations", "trends", "safety-signals", "reviews", "referrals"]
)
def test_unassigned_counselor_and_admin_cannot_read_sensitive_data(api, actor, resource):
    response = api[0].get(
        f"/api/v1/students/{api[2]['alice'].id}/{resource}", headers=headers(api, actor)
    )
    assert response.status_code == 403


def test_assignment_consent_and_live_permissions(api):
    client, db, users, records, _ = api
    auth = headers(api, "counselor")
    path = f"/api/v1/conversations/{records['alice'].id}"
    assert client.get(path, headers=auth).json()["messages"][0]["text"] == "alice PRIVATE CONTENT"
    assert client.get(f"/api/v1/conversations/{records['bob'].id}", headers=auth).status_code == 403
    db.add(
        ConsentRecord(
            student_id=users["alice"].id,
            version=2,
            policy_version="v2",
            reviewer_access=False,
        )
    )
    db.commit()
    assert client.get(path, headers=auth).status_code == 403
    db.add(
        ConsentRecord(
            student_id=users["alice"].id,
            version=3,
            policy_version="v3",
            reviewer_access=True,
        )
    )
    db.commit()
    assert client.get(path, headers=auth).status_code == 200
    assignment = db.scalar(select(ReviewerAssignment))
    assignment.revoked_at = utcnow()
    db.commit()
    assert client.get(path, headers=auth).status_code == 403
    assignment.revoked_at = None
    role = users["counselor"].roles[0]
    role.permissions = [p for p in role.permissions if p.code != "history:read"]
    db.commit()
    assert client.get(path, headers=auth).status_code == 403


@pytest.mark.parametrize(
    "path",
    ["/me", "/admin/users", "/admin/settings", "/students/unknown/conversations"],
)
def test_missing_and_forged_credentials(api, path):
    for auth in [{}, {"Authorization": "Bearer forged"}]:
        assert api[0].get("/api/v1" + path, headers=auth).status_code == 401


def test_refresh_rotation_replay_logout_and_expiration(api):
    client, db, _, _, _ = api
    original = login(api, "alice")
    new = client.post("/api/v1/auth/refresh", json={"token": original["refresh_token"]}).json()
    assert (
        client.get(
            "/api/v1/me",
            headers={"Authorization": "Bearer " + original["access_token"]},
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/v1/me", headers={"Authorization": "Bearer " + new["access_token"]}
        ).status_code
        == 200
    )
    assert (
        client.post("/api/v1/auth/refresh", json={"token": original["refresh_token"]}).status_code
        == 401
    )
    assert (
        client.get(
            "/api/v1/me", headers={"Authorization": "Bearer " + new["access_token"]}
        ).status_code
        == 401
    )
    tokens = login(api, "alice")
    auth = {"Authorization": "Bearer " + tokens["access_token"]}
    assert client.post("/api/v1/auth/logout", headers=auth).status_code == 204
    assert (
        client.post("/api/v1/auth/refresh", json={"token": tokens["refresh_token"]}).status_code
        == 401
    )
    tokens = login(api, "alice")
    row = db.scalar(
        select(AuthSession).where(AuthSession.access_hash == digest(tokens["access_token"]))
    )
    row.access_expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert (
        client.get(
            "/api/v1/me", headers={"Authorization": "Bearer " + tokens["access_token"]}
        ).status_code
        == 401
    )


def test_password_recovery_single_use_and_change_revokes_sessions(api):
    client, _, _, _, _ = api
    auth = headers(api, "alice")
    known = client.post("/api/v1/auth/forgot-password", json={"email": "alice@test.example"})
    unknown = client.post("/api/v1/auth/forgot-password", json={"email": "unknown@test.example"})
    assert known.status_code == unknown.status_code == 202 and known.json() == unknown.json()
    token = challenge_token(api, "reset")
    body = {"token": token, "password": "new-long-password-12345"}
    assert client.post("/api/v1/auth/reset-password", json=body).status_code == 204
    assert client.post("/api/v1/auth/reset-password", json=body).status_code == 400
    assert client.get("/api/v1/me", headers=auth).status_code == 401
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "alice@test.example", "password": body["password"]},
    )
    auth = {"Authorization": "Bearer " + response.json()["access_token"]}
    assert (
        client.post(
            "/api/v1/auth/change-password",
            headers=auth,
            json={"current_password": "wrong", "new_password": PASSWORD},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/change-password",
            headers=auth,
            json={"current_password": body["password"], "new_password": PASSWORD},
        ).status_code
        == 204
    )
    assert client.get("/api/v1/me", headers=auth).status_code == 401


def test_onboarding_no_self_selected_roles_and_activation(api):
    client, db, _, _, settings = api
    body = {
        "email": "new@test.example",
        "display_name": "New user",
        "password": PASSWORD,
    }
    assert client.post("/api/v1/auth/register", json=body).status_code == 403
    settings.public_registration_enabled = True
    assert client.post("/api/v1/auth/register", json={**body, "role": "ADMIN"}).status_code == 422
    assert client.post("/api/v1/auth/register", json=body).status_code == 202
    login_body = {"email": body["email"], "password": PASSWORD}
    assert client.post("/api/v1/auth/login", json=login_body).status_code == 401
    token = challenge_token(api, "activate")
    assert client.post("/api/v1/auth/activate", json={"token": token}).status_code == 204
    assert client.post("/api/v1/auth/activate", json={"token": token}).status_code == 400
    assert client.post("/api/v1/auth/login", json=login_body).status_code == 200
    user = db.scalar(select(User).where(User.email == body["email"]))
    assert [r.code for r in user.roles] == ["STUDENT"]
    assert user.password_hash.startswith("$argon2id$")


def test_admin_invitation_and_account_deactivation(api):
    client, db, users, _, _ = api
    admin = headers(api, "admin")
    alice = headers(api, "alice")
    invitation = {"email": "new.counselor@test.example", "role": "COUNSELOR"}
    assert (
        client.post("/api/v1/admin/invitations", headers=alice, json=invitation).status_code == 403
    )
    assert (
        client.post("/api/v1/admin/invitations", headers=admin, json=invitation).status_code == 202
    )
    token = challenge_token(api, "invite")
    registration = {
        "email": invitation["email"],
        "display_name": "Counselor",
        "password": PASSWORD,
        "invitation_token": token,
    }
    assert client.post("/api/v1/auth/register", json=registration).status_code == 202
    assert client.post("/api/v1/auth/register", json=registration).status_code == 400
    user = db.scalar(select(User).where(User.email == invitation["email"]))
    assert [r.code for r in user.roles] == ["COUNSELOR"] and user.reviewer_profile
    path = f"/api/v1/admin/users/{users['alice'].id}/activation"
    assert client.patch(path, headers=admin, json={"is_active": False}).status_code == 200
    assert client.get("/api/v1/me", headers=alice).status_code == 401
    assert client.patch(path, headers=admin, json={"is_active": True}).status_code == 200
    assert client.get("/api/v1/me", headers=alice).status_code == 401


def test_profile_admin_permissions_and_student_own_resources(api):
    client, _, users, _, _ = api
    alice = headers(api, "alice")
    base = f"/api/v1/students/{users['alice'].id}"
    assert client.get(base + "/conversations", headers=alice).status_code == 200
    assert (
        client.put(
            base + "/consent",
            headers=alice,
            json={"policy_version": POLICY_VERSION, "acknowledged": True, "retention_version": 1},
        ).status_code
        == 200
    )
    assert client.post(base + "/support-requests", headers=alice).status_code == 201
    assert (
        client.post(base + "/data-controls", headers=alice, json={"kind": "erasure"}).status_code
        == 202
    )
    assert (
        client.patch("/api/v1/me", headers=alice, json={"display_name": "Updated"}).json()[
            "display_name"
        ]
        == "Updated"
    )
    assert client.patch("/api/v1/me", headers=alice, json={"roles": ["ADMIN"]}).status_code == 422
    assert client.get("/api/v1/admin/users", headers=alice).status_code == 403
    admin = headers(api, "admin")
    assert client.get("/api/v1/admin/users", headers=admin).status_code == 200
    assert (
        client.put(
            "/api/v1/admin/assignments",
            headers=admin,
            json={"student_id": users["bob"].id, "counselor_id": users["counselor"].id},
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/api/v1/admin/settings/raw_media_retention",
            headers=admin,
            json={"value": {"enabled": True}},
        ).status_code
        == 200
    )


def test_login_rate_limit_and_no_secret_audits(api):
    client, db, _, _, _ = api
    for _ in range(8):
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"email": "alice@test.example", "password": "wrong"},
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "alice@test.example", "password": PASSWORD},
        ).status_code
        == 429
    )
    assert all(
        "wrong" not in str(row.__dict__) and PASSWORD not in str(row.__dict__)
        for row in db.scalars(select(AuditLog))
    )


def test_role_change_revokes_sessions_and_does_not_preserve_student_access(api):
    client, _, users, records, _ = api
    alice = headers(api, "alice")
    admin = headers(api, "admin")
    path = f"/api/v1/admin/users/{users['alice'].id}/role"
    assert client.patch(path, headers=alice, json={"role": "ADMIN"}).status_code == 403
    assert client.patch(path, headers=admin, json={"role": "ADMIN"}).status_code == 200
    assert client.get("/api/v1/me", headers=alice).status_code == 401
    new = headers(api, "alice")
    assert (
        client.get(f"/api/v1/conversations/{records['alice'].id}", headers=new).status_code == 403
    )


def test_invalid_expired_tokens_and_reset_cannot_reactivate_disabled_user(api):
    client, db, users, _, _ = api
    client.post("/api/v1/auth/forgot-password", json={"email": "alice@test.example"})
    token = challenge_token(api, "reset")
    row = db.scalar(select(AuthChallenge).where(AuthChallenge.token_hash == digest(token)))
    row.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert (
        client.post(
            "/api/v1/auth/reset-password", json={"token": token, "password": PASSWORD}
        ).status_code
        == 400
    )
    client.post("/api/v1/auth/forgot-password", json={"email": "alice@test.example"})
    token = challenge_token(api, "reset")
    admin = headers(api, "admin")
    client.patch(
        f"/api/v1/admin/users/{users['alice'].id}/activation",
        headers=admin,
        json={"is_active": False},
    )
    assert (
        client.post(
            "/api/v1/auth/reset-password", json={"token": token, "password": PASSWORD}
        ).status_code
        == 400
    )
    assert not users["alice"].is_active


def test_bootstrap_has_no_default_password_and_is_one_time(api):
    from app.bootstrap_admin import bootstrap

    with pytest.raises(ValueError, match="administrator exists"):
        bootstrap(api[1], "first.admin@test.example", PASSWORD, "Institutional admin")
    with pytest.raises(ValueError, match="strong password"):
        bootstrap(api[1], "first.admin@test.example", "short", "Institutional admin")


def test_counselor_review_and_referral_routes_check_actual_record_owner(api):
    from app.models import ModelInference, ModelVersion, RiskSignal

    client, db, users, _, _ = api
    signals = {}
    for name in ["alice", "bob"]:
        student_id = users[name].id
        consent = db.scalar(select(ConsentRecord).where(ConsentRecord.student_id == student_id))
        interaction = db.scalar(
            select(InteractionSession).where(InteractionSession.student_id == student_id)
        )
        model = ModelVersion(model_identifier=name, version="1", modality="text")
        db.add(model)
        db.flush()
        start = utcnow()
        inference = ModelInference(
            student_id=student_id,
            session_id=interaction.id,
            consent_record_id=consent.id,
            model_version_id=model.id,
            modality="text",
            preprocessing_version="1",
            adapter_version="1",
            processing_status="completed",
            created_at=start,
            started_at=start,
            completed_at=start + timedelta(microseconds=1),
        )
        db.add(inference)
        db.flush()
        signal = RiskSignal(
            student_id=student_id,
            inference_id=inference.id,
            signal_code="test",
            priority="routine",
            explanation={"fixture": True},
            rule_version="1",
        )
        db.add(signal)
        db.flush()
        signals[name] = signal
    db.commit()
    auth = headers(api, "counselor")
    path = f"/api/v1/safety-signals/{signals['alice'].id}/reviews"
    response = client.post(
        path, headers=auth, json={"decision": "refer", "notes": "private review"}
    )
    assert response.status_code == 201, response.text
    review_id = response.json()["id"]
    assert (
        client.post(
            f"/api/v1/safety-signals/{signals['bob'].id}/reviews",
            headers=auth,
            json={"decision": "refer"},
        ).status_code
        == 403
    )
    assert (
        client.post(path, headers=headers(api, "admin"), json={"decision": "refer"}).status_code
        == 403
    )
    body = {"human_review_id": review_id, "service_reference": "institutional support"}
    response = client.post(
        f"/api/v1/students/{users['alice'].id}/referrals", headers=auth, json=body
    )
    assert response.status_code == 201
    referral_id = response.json()["id"]
    assert (
        client.patch(
            f"/api/v1/referrals/{referral_id}",
            headers=headers(api, "other_counselor"),
            json={"status": "closed"},
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/referrals/{referral_id}",
            headers=headers(api, "bob"),
            json={"status": "closed"},
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/referrals/{referral_id}", headers=auth, json={"status": "closed"}
        ).status_code
        == 200
    )


def test_refresh_secret_can_end_session_after_access_expiration(api):
    client, db, _, _, _ = api
    tokens = login(api, "alice")
    row = db.scalar(
        select(AuthSession).where(AuthSession.access_hash == digest(tokens["access_token"]))
    )
    row.access_expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert (
        client.post(
            "/api/v1/auth/logout-session", json={"token": tokens["refresh_token"]}
        ).status_code
        == 204
    )
    assert (
        client.post("/api/v1/auth/refresh", json={"token": tokens["refresh_token"]}).status_code
        == 401
    )


def test_delivery_is_encrypted_and_never_discloses_recovery_secrets(api):
    client, db, users, _, _ = api
    response = client.post("/api/v1/auth/forgot-password", json={"email": users["alice"].email})
    token = challenge_token(api, "reset")
    row = db.scalar(select(AuthChallenge).where(AuthChallenge.token_hash == digest(token)))
    delivery = db.scalar(select(AuthDelivery).where(AuthDelivery.challenge_id == row.id))
    assert token not in response.text and token not in delivery.encrypted_payload
    assert row.token_hash == digest(token) and token not in str(row.__dict__)
