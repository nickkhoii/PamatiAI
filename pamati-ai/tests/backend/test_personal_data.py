"""Personal downloads use real owned records and never broaden staff access."""
from datetime import timedelta

from test_auth import api as api_fixture
from test_auth import headers

from app.models import Conversation, InteractionSession, Message, WellbeingCheckIn, utcnow

api = api_fixture


def owned_conversation(db, student_id, text, **values):
    conversation = Conversation(student_id=student_id, **values)
    db.add(conversation)
    db.flush()
    session = InteractionSession(student_id=student_id, conversation_id=conversation.id)
    db.add(session)
    db.flush()
    db.add(Message(student_id=student_id, session_id=session.id, sequence_number=0,
                   sender="student", text_content=text))
    return conversation


def test_personal_download_excludes_other_owners_hidden_expired_and_secrets(api):
    client, db, users, _, _ = api
    owned_conversation(db, users["alice"].id, "Visible personal export fixture")
    owned_conversation(db, users["bob"].id, "Other student private export fixture")
    owned_conversation(db, users["alice"].id, "Hidden export fixture", deleted_at=utcnow())
    owned_conversation(db, users["alice"].id, "Expired export fixture",
                       created_at=utcnow() - timedelta(days=4000))
    db.add(WellbeingCheckIn(student_id=users["alice"].id, feeling="mixed"))
    db.commit()
    path = f"/api/v1/students/{users['alice'].id}/data-download"
    response = client.get(path, headers=headers(api, "alice"))
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["cache-control"] == "no-store"
    assert "Visible personal export fixture" in response.text
    for secret in ["Other student private export fixture", "Hidden export fixture", "Expired export fixture",
                   "password_hash", "access_hash", "refresh_hash", users["bob"].email]:
        assert secret not in response.text
    assert response.json()["check_ins"][0]["feeling"] == "mixed"
    for actor in ["bob", "counselor", "admin", "other_counselor"]:
        assert client.get(path, headers=headers(api, actor)).status_code == 403
    assert client.get(path).status_code == 401


def test_download_after_withdrawal_never_reactivates_processing(api):
    client, db, users, _, _ = api
    owned_conversation(db, users["alice"].id, "Own historical text remains accessible")
    db.commit()
    auth = headers(api, "alice")
    assert client.delete(f"/api/v1/students/{users['alice'].id}/consent", headers=auth).status_code == 204
    assert client.get(f"/api/v1/students/{users['alice'].id}/data-download", headers=auth).status_code == 200
    receipt = client.get(f"/api/v1/students/{users['alice'].id}/consent", headers=auth).json()
    assert receipt["withdrawn_at"] is not None


def test_download_limit_fails_explicitly_instead_of_silently_truncating(api, monkeypatch):
    client, db, users, _, _ = api
    owned_conversation(db, users["alice"].id, "Bounded download fixture")
    db.commit()
    monkeypatch.setattr("app.personal_data_routes.MAX_DOWNLOAD_BYTES", 10)
    response = client.get(f"/api/v1/students/{users['alice'].id}/data-download", headers=headers(api, "alice"))
    assert response.status_code == 413 and "attachment" not in response.headers.get("content-disposition", "")


def test_analysis_list_is_owned_validated_and_paginated(api):
    client, _, users, _, _ = api
    path = f"/api/v1/students/{users['alice'].id}/analyses"
    auth = headers(api, "alice")
    assert client.get(path + "?modality=audio&limit=1", headers=auth).json() == {
        "items": [], "total": 0, "page": 1, "limit": 1}
    assert client.get(path + "?modality=unknown", headers=auth).status_code == 422
    assert client.get(path + "?page=0", headers=auth).status_code == 422
    for name in ["bob", "counselor", "admin"]:
        assert client.get(path, headers=headers(api, name)).status_code == 403
