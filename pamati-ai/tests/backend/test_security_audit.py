"""Adversarial HTTP regressions; fixtures contain synthetic data only."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import StatementError
from test_auth import api as api_fixture
from test_auth import headers

from app.auth_dependencies import digest
from app.config import Settings
from app.http_security import BodyLimitMiddleware
from app.models import AuditLog, AuthRateLimit, Role, User, utcnow
from app.retention import retained

api = api_fixture


def test_validation_does_not_echo_password_token_or_conversation(api, caplog):
    client, db, _users, records, _ = api
    sentinel = "PRIVATE-SENTINEL-" + "x" * 140
    response = client.post("/api/v1/auth/login", json={"email": "bad", "password": sentinel})
    assert response.status_code == 422
    assert sentinel not in response.text
    response = client.post("/api/v1/auth/reset-password", json={"token": sentinel * 4, "password": sentinel})
    assert response.status_code == 422
    assert sentinel not in response.text
    response = client.post(f"/api/v1/conversations/{records['alice'].id}/messages",
                           headers=headers(api, "alice"),
                           json={"request_id": str(uuid4()), "text": sentinel * 40})
    assert response.status_code == 422
    assert sentinel not in response.text
    assert sentinel not in caplog.text
    assert all(sentinel not in str(r.__dict__) for r in db.scalars(select(AuditLog)))


def test_headers_cors_and_early_oversized_requests(api):
    client = api[0]
    for path in ["/api/v1/health", "/api/v1/me"]:
        response = client.get(path)
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert response.headers["referrer-policy"] == "no-referrer"
    response = client.post("/api/v1/auth/login", content=b"x" * 32769)
    assert response.status_code == 413
    response = client.options("/api/v1/me", headers={"Origin": "https://attacker.example",
                              "Access-Control-Request-Method": "GET"})
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_chunked_body_limit():
    # Exercise receive accounting without Content-Length or buffering the whole body.
    chunks = iter([{"type": "http.request", "body": b"x" * 20000, "more_body": True},
                   {"type": "http.request", "body": b"x" * 20000, "more_body": True}])
    async def receive():
        return next(chunks)
    async def send(message):
        pass
    async def downstream(scope, receive, send):
        await receive()
        await receive()
    with pytest.raises(HTTPException) as failure:
        asyncio.run(BodyLimitMiddleware(downstream)({"type": "http", "path": "/api/v1/auth/login", "headers": []}, receive, send))
    assert failure.value.status_code == 413


def test_api_budget_includes_invalid_tokens_and_mutations(api):
    client, db, *_ = api
    key = digest("api.requests:ip:testclient")
    client.get("/api/v1/me", headers={"Authorization": "Bearer invalid-token"})
    row = db.get(AuthRateLimit, key)
    assert row is not None
    row.attempts = 600
    db.commit()
    for method, path in [("get", "/api/v1/me"), ("post", "/api/v1/auth/login")]:
        response = getattr(client, method)(path, **({"json": {"email": "alice@test.example", "password": "wrong"}} if method == "post" else {}))
        assert response.status_code == 429
        assert response.headers["retry-after"] == "900"


@pytest.mark.parametrize("actor", ["alice", "counselor", "admin"])
def test_expired_conversation_cannot_be_read_or_processed(api, actor):
    client, db, _users, records, _ = api
    conversation = records["alice"]
    conversation.created_at = utcnow() - timedelta(days=181)
    db.commit()
    assert not retained(db, conversation, "conversations")
    response = client.get(f"/api/v1/conversations/{conversation.id}", headers=headers(api, actor))
    assert response.status_code == 404
    response = client.post(f"/api/v1/conversations/{conversation.id}/messages", headers=headers(api, actor),
                           json={"request_id": str(uuid4()), "text": "Do not process expired records"})
    assert response.status_code == 404
    listing = client.get("/api/v1/dashboard/STUDENT/conversations", headers=headers(api, "alice"))
    assert listing.json()["total"] == 0


def test_unrecognized_research_role_does_not_grant_identifiable_access(api):
    client, db, users, records, _ = api
    researcher = User(email="researcher@test.example", display_name="Researcher",
                      password_hash=users["alice"].password_hash, email_verified_at=utcnow(),
                      roles=[Role(code="RESEARCHER", description="No content privileges")])
    db.add(researcher)
    db.commit()
    response = client.get(f"/api/v1/conversations/{records['alice'].id}", headers=headers(api, "researcher"))
    assert response.status_code == 403
    assert "PRIVATE CONTENT" not in response.text


def test_role_removal_does_not_resurrect_assignments(api):
    client, _db, users, records, _ = api
    admin = headers(api, "admin")
    path = f"/api/v1/admin/users/{users['counselor'].id}/role"
    assert client.patch(path, headers=admin, json={"role": "STUDENT"}).status_code == 200
    assert client.patch(path, headers=admin, json={"role": "COUNSELOR"}).status_code == 200
    response = client.get(f"/api/v1/conversations/{records['alice'].id}", headers=headers(api, "counselor"))
    assert response.status_code == 403


def test_cached_consent_cannot_grant_review_after_withdrawal(api):
    from app.auth_dependencies import authorize_student
    from app.models import ConsentRecord

    _, db, users, _, _ = api
    receipt = db.scalar(select(ConsentRecord).where(ConsentRecord.student_id == users["alice"].id))
    db.execute(update(ConsentRecord).where(ConsentRecord.id == receipt.id)
               .values(withdrawn_at=utcnow()).execution_options(synchronize_session=False))
    db.commit()
    assert receipt.withdrawn_at is None
    with pytest.raises(HTTPException) as failure:
        authorize_student(db, users["counselor"], "history:read", users["alice"].id)
    assert failure.value.status_code == 403


def test_sql_injection_search_does_not_expand_student_scope(api):
    response = api[0].get("/api/v1/dashboard/STUDENT/conversations",
                          headers=headers(api, "alice"), params={"q": "' OR 1=1 --"})
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total"] == 0


def test_expired_text_analysis_is_not_returned_with_live_conversation(api, monkeypatch):
    from test_research_export import populate

    from app.models import SystemSetting
    from app.retention import retention_policy

    _, _, inference, _, conversation = populate(api)[0]
    client, db, *_ = api
    endpoint = f"/api/v1/conversations/{conversation.id}/messages/{inference.message_id}/analyses"
    auth = headers(api, "alice")
    assert len(client.get(endpoint, headers=auth).json()["analyses"]) == 1
    policy = retention_policy(db).model_dump()
    policy["analysis_days"] = 1
    db.get(SystemSetting, "data_retention").value = policy
    db.commit()
    future = utcnow() + timedelta(days=2)
    monkeypatch.setattr("app.retention.utcnow", lambda: future)
    response = client.get(endpoint, headers=auth)
    assert response.status_code == 200
    assert response.json()["analyses"] == []


def test_cached_retention_policy_cannot_extend_record_availability(api):
    from app.models import SystemSetting
    from app.retention import retention_policy

    _, db, _, records, _ = api
    setting = db.get(SystemSetting, "data_retention")
    previous = setting.value.copy()
    changed = previous | {"conversation_days": 1}
    db.execute(update(SystemSetting).where(SystemSetting.key == "data_retention")
               .values(value=changed).execution_options(synchronize_session=False))
    db.commit()
    assert setting.value == previous
    assert retention_policy(db).conversation_days == 1
    conversation = records["alice"]
    conversation.created_at = utcnow() - timedelta(days=2)
    assert not retained(db, conversation, "conversations")


@pytest.mark.parametrize("modality", ["audio", "visual"])
def test_http_upload_limits_and_active_content_are_rejected(api, monkeypatch, tmp_path, modality):
    if modality == "audio":
        from test_audio_analysis import configure, session_id
        content_type = "audio/wav"
    else:
        from test_visual_analysis import configure, session_id
        content_type = "image/bmp"
    configure(api, monkeypatch, tmp_path)
    endpoint = f"/api/v1/sessions/{session_id(api)}/{modality}-analyses"
    auth = headers(api, "alice")
    response = api[0].post(endpoint, headers=auth | {"Content-Type": content_type}, content=b"x" * 3_000_001)
    assert response.status_code == 413
    response = api[0].post(endpoint, headers=auth | {"Content-Type": "image/svg+xml"},
                           content=b'<svg onload="alert(1)"/>')
    assert response.status_code == 415
    response = api[0].post(endpoint, headers=auth | {"Content-Type": content_type}, content=b"PK\x03\x04malicious-archive")
    assert response.status_code == 422
    assert not list(tmp_path.rglob("*.wav"))
    assert not list(tmp_path.rglob("*.bmp"))


def test_database_exception_is_redacted_in_response_and_logs(api, monkeypatch, caplog):
    import app.resource_routes as routes
    sentinel = "PRIVATE-CONVERSATION-SECRET"
    def broken(*args, **kwargs):
        raise StatementError(sentinel, "INSERT", {"text": sentinel}, ValueError(sentinel))
    monkeypatch.setattr(routes, "authorize_student", broken)
    response = api[0].get(f"/api/v1/conversations/{api[3]['alice'].id}", headers=headers(api, "alice"))
    assert response.status_code == 500
    assert sentinel not in response.text
    assert sentinel not in caplog.text
    assert "StatementError" in caplog.text


@pytest.mark.parametrize("configuration", [
    {"auth_public_url": "http://school.example"}, {"cors_origins": ["*"]},
    {"allowed_hosts": ["*"]}, {"database_url": "mysql+pymysql://pamati:local-only@localhost/pamati?charset=utf8mb4"},
])
def test_production_rejects_insecure_development_configuration(configuration):
    base = {"environment": "production", "auth_public_url": "https://school.example",
            "cors_origins": ["https://school.example"], "allowed_hosts": ["school.example"],
            "database_url": "mysql+pymysql://pamati:synthetic-test-password@localhost/pamati?charset=utf8mb4"}
    with pytest.raises(ValidationError):
        Settings(**(base | configuration))
