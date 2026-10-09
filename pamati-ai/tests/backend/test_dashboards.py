"""Database-backed dashboard authorization, filters, pagination and writes."""

from datetime import timedelta

from sqlalchemy import select
from test_auth import api as api_fixture
from test_auth import headers

from app.models import ConsentRecord, Conversation, SystemSetting, WellbeingCheckIn, utcnow

api = api_fixture


def test_student_list_is_owned_searchable_and_paginated(api):
    client, db, users, _, _ = api
    db.add_all([Conversation(student_id=users["alice"].id, status="closed") for _ in range(3)])
    db.commit()
    auth = headers(api, "alice")
    response = client.get(
        "/api/v1/dashboard/STUDENT/conversations?limit=2&status=closed", headers=auth
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3 and len(data["items"]) == 2
    second = client.get(
        "/api/v1/dashboard/STUDENT/conversations?limit=2&status=closed&page=2", headers=auth
    ).json()
    assert len(second["items"]) == 1
    assert not {r["id"] for r in data["items"]} & {r["id"] for r in second["items"]}
    assert (
        client.get("/api/v1/dashboard/STUDENT/conversations?q=not-found", headers=auth).json()[
            "total"
        ]
        == 0
    )
    assert (
        client.get(
            f"/api/v1/dashboard/STUDENT/conversations?start={(utcnow() + timedelta(days=1)).date()}",
            headers=auth,
        ).json()["total"]
        == 0
    )
    assert (
        client.get(
            "/api/v1/dashboard/STUDENT/conversations?start=2026-10-09&end=2026-10-01", headers=auth
        ).status_code
        == 422
    )


def test_counselor_cases_respect_latest_consent(api):
    client, db, users, _, _ = api
    auth = headers(api, "counselor")
    data = client.get("/api/v1/dashboard/COUNSELOR/cases", headers=auth).json()
    assert [r["id"] for r in data["items"]] == [users["alice"].id]
    db.add(
        ConsentRecord(
            student_id=users["alice"].id, version=2, policy_version="v2", reviewer_access=False
        )
    )
    db.commit()
    assert client.get("/api/v1/dashboard/COUNSELOR/cases", headers=auth).json()["total"] == 0
    assert (
        client.get(
            f"/api/v1/dashboard/COUNSELOR/reviews?student={users['bob'].id}", headers=auth
        ).status_code
        == 403
    )


def test_checkin_does_not_require_ai_consent_and_is_private(api):
    client, db, users, _, _ = api
    auth = headers(api, "alice")
    receipt = db.scalar(select(ConsentRecord).where(ConsentRecord.student_id == users["alice"].id))
    receipt.withdrawn_at = utcnow()
    db.commit()
    response = client.post("/api/v1/dashboard/check-ins", headers=auth, json={"feeling": "mixed"})
    assert response.status_code == 201
    record = response.json()
    assert db.get(WellbeingCheckIn, record["id"]).feeling == "mixed"
    assert (
        client.get("/api/v1/dashboard/STUDENT/check-ins", headers=headers(api, "bob")).json()[
            "total"
        ]
        == 0
    )
    assert (
        client.delete(
            f"/api/v1/dashboard/check-ins/{record['id']}", headers=headers(api, "bob")
        ).status_code
        == 403
    )
    assert (
        client.delete(f"/api/v1/dashboard/check-ins/{record['id']}", headers=auth).status_code
        == 204
    )
    assert client.get("/api/v1/dashboard/STUDENT/check-ins", headers=auth).json()["total"] == 0


def test_admin_has_no_case_content_and_no_secret_fields(api):
    client = api[0]
    auth = headers(api, "admin")
    for role, collection in [("COUNSELOR", "cases"), ("STUDENT", "conversations")]:
        assert client.get(f"/api/v1/dashboard/{role}/{collection}", headers=auth).status_code == 403
    response = client.get("/api/v1/dashboard/ADMIN/users?status=STUDENT", headers=auth)
    assert response.status_code == 200 and response.json()["total"] == 2
    assert "password_hash" not in response.text and "PRIVATE CONTENT" not in response.text
    assert (
        client.get("/api/v1/dashboard/ADMIN/users", headers=headers(api, "alice")).status_code
        == 403
    )
    assert client.get("/api/v1/dashboard/ADMIN/users?page=0", headers=auth).status_code == 422


def test_database_resource_directory_and_validation(api):
    client, db, *_ = api
    auth = headers(api, "admin")
    body = {
        "resources": [
            {
                "id": "campus",
                "label": "Campus support",
                "description": "Appointments",
                "url": "https://institution.example/support",
            }
        ]
    }
    assert (
        client.put(
            "/api/v1/dashboard/resources", headers=headers(api, "alice"), json=body
        ).status_code
        == 403
    )
    assert client.put("/api/v1/dashboard/resources", headers=auth, json=body).status_code == 200
    assert db.get(SystemSetting, "institutional_resources").value["resources"][0]["id"] == "campus"
    assert (
        client.get("/api/v1/dashboard/STUDENT/resources", headers=headers(api, "alice")).json()[
            "total"
        ]
        == 1
    )
    body["resources"][0]["url"] = "javascript:alert(1)"
    assert client.put("/api/v1/dashboard/resources", headers=auth, json=body).status_code == 422


def test_observation_route_and_consent(api):
    client, _, users, *_ = api
    auth = headers(api, "alice")
    response = client.get(
        f"/api/v1/dashboard/observations/students/{users['alice'].id}", headers=auth
    )
    assert response.status_code == 200 and response.json()["items"] == []
    assert (
        client.get(
            f"/api/v1/dashboard/observations/students/{users['bob'].id}", headers=auth
        ).status_code
        == 403
    )
