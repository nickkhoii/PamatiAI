import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.main import app
from app.security import Principal, Role, permitted


def test_liveness():
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "pamati-api"}


def test_readiness_failure_does_not_leak_credentials(monkeypatch):
    def fail():
        raise OperationalError("secret SQL", {}, Exception("secret password"))
    monkeypatch.setattr("app.main.engine.connect", fail)
    with TestClient(app) as client:
        response = client.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "service": "pamati-api"}


def test_readiness_success(monkeypatch):
    from unittest.mock import MagicMock
    connection = MagicMock()
    monkeypatch.setattr("app.main.engine.connect", lambda: connection)
    with TestClient(app) as client:
        response = client.get("/api/v1/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "service": "pamati-api"}
    connection.__enter__.return_value.execute.assert_called_once()


@pytest.mark.parametrize("role", list(Role))
def test_unknown_permissions_deny(role):
    assert not permitted(Principal("alice", role), "unknown", student_id="alice", assigned=True, consent_active=True)


def test_student_cannot_read_other_student():
    student = Principal("alice", Role.STUDENT)
    assert permitted(student, "history:read", student_id="alice")
    assert not permitted(student, "history:read", student_id="bob")


@pytest.mark.parametrize("assigned,consent", [(False, False), (True, False), (False, True)])
def test_reviewer_requires_assignment_and_consent(assigned, consent):
    assert not permitted(Principal("reviewer", Role.COUNSELOR), "history:read", student_id="alice", assigned=assigned, consent_active=consent)


def test_reviewer_and_admin_boundaries():
    assert permitted(Principal("reviewer", Role.COUNSELOR), "review:manage", student_id="alice", assigned=True, consent_active=True)
    admin = Principal("admin", Role.SYSTEM_ADMINISTRATOR)
    assert permitted(admin, "accounts:manage")
    assert not permitted(admin, "history:read", student_id="alice", assigned=True, consent_active=True)


def test_disallowed_host():
    with TestClient(app) as client:
        assert client.get("/api/v1/health", headers={"host": "attacker.example"}).status_code == 400
