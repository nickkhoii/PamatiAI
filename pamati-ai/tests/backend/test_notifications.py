"""Real database event inbox: identity minimization and current authorization."""
from sqlalchemy import select
from test_auth import api as api_fixture
from test_auth import headers

from app.models import ConsentRecord, NotificationReceipt, StudentProfile, SupportRequest, utcnow

api = api_fixture


def test_owned_receipts_and_current_counselor_consent(api):
    client, db, users, _, _ = api
    row = SupportRequest(student_id=users["alice"].id)
    db.add(row)
    db.commit()
    alice, bob, counselor, other, admin = [headers(api, name) for name in
                                         ("alice", "bob", "counselor", "other_counselor", "admin")]
    inbox = client.get("/api/v1/notifications", headers=alice).json()
    key = inbox["items"][0]["id"]
    assert inbox["unread_count"] == 1 and "student_id" not in inbox["items"][0]
    assert client.post(f"/api/v1/notifications/{key}/read", headers=bob).status_code == 404
    for _ in range(2):
        assert client.post(f"/api/v1/notifications/{key}/read", headers=alice).status_code == 204
    assert len(list(db.scalars(select(NotificationReceipt)))) == 1
    assert client.get("/api/v1/notifications?unread=true", headers=alice).json()["total"] == 0
    assert client.get("/api/v1/notifications", headers=counselor).json()["total"] == 1
    assert client.get("/api/v1/notifications", headers=other).json()["total"] == 0
    assert client.get("/api/v1/notifications", headers=admin).json()["total"] == 0
    db.add(ConsentRecord(student_id=users["alice"].id, version=2, policy_version="v2", reviewer_access=False))
    db.commit()
    assert client.get("/api/v1/notifications", headers=counselor).json()["total"] == 0
    assert client.get("/api/v1/notifications?start=2026-10-09&end=2026-10-01", headers=alice).status_code == 422
    assert client.get("/api/v1/notifications?q=absent", headers=alice).json()["total"] == 0
    assert client.get("/api/v1/notifications").status_code == 401
    db.get(StudentProfile, users["alice"].id).deleted_at = utcnow()
    db.commit()
    assert client.get("/api/v1/notifications", headers=alice).status_code == 403
