from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from test_auth import api as shared_api
from test_auth import headers

from app.consent_policy import POLICY_VERSION, policy_document
from app.models import Message, ModelInference, utcnow
from app.persistence import record_consent, withdraw_consent
from services.conversation.providers import (
    CompatibleHTTPProvider,
    LocalSupportProvider,
    Reply,
    safe_reply,
)

fixture_api = shared_api


@pytest.fixture
def api(fixture_api):
    _, db, users, _, _ = fixture_api
    for name in ("alice", "bob"):
        record_consent(
            db,
            users[name].id,
            policy_version=POLICY_VERSION,
            disclosure_snapshot=policy_document(),
            text_processing=True,
        )
    db.commit()
    return fixture_api


def send(api, name="alice", conversation="alice", **changes):
    client, _, _, records, _ = api
    body = {"request_id": str(uuid4()), "text": "I am stressed about my exams", **changes}
    return client.post(
        f"/api/v1/conversations/{records[conversation].id}/messages",
        headers=headers(api, name),
        json=body,
    )


@pytest.mark.parametrize("actor", ["bob", "counselor", "other_counselor", "admin"])
def test_only_owner_can_send(api, actor):
    with patch("services.conversation.providers.get_provider") as provider:
        assert send(api, actor).status_code == 403
        provider.assert_not_called()


def test_text_only_turn_provenance_and_replay(api):
    _, db, users, _, _ = api
    record_consent(
        db,
        users["alice"].id,
        policy_version=POLICY_VERSION,
        disclosure_snapshot=policy_document(),
        text_processing=True,
    )
    db.commit()
    request = str(uuid4())
    with patch(
        "services.conversation.providers.get_provider", return_value=LocalSupportProvider()
    ) as provider:
        first = send(api, request_id=request)
        again = send(api, request_id=request)
        assert first.status_code == 200, first.text
        assert first.json() == again.json()
        assert provider.call_count == 1
    messages = first.json()["messages"]
    assert [m["sender"] for m in messages] == ["student", "assistant"]
    metadata = messages[-1]["generation"]
    assert metadata["provider"] == "local-support"
    assert (
        metadata["model"]
        and metadata["version"]
        and metadata["prompt_version"]
        and metadata["consent_id"]
    )
    assert "study" in messages[-1]["text"].lower()
    assert db.scalar(select(func.count()).select_from(ModelInference)) == 0
    assert send(api, request_id=request, text="different").status_code == 409


def test_disabled_text_never_calls_provider_or_saves_input(api):
    _, db, users, _, _ = api
    record_consent(db, users["alice"].id, policy_version="test", text_processing=False)
    db.commit()
    count = db.scalar(select(func.count()).select_from(Message))
    with patch("services.conversation.providers.get_provider") as provider:
        assert send(api).status_code == 409
        provider.assert_not_called()
    assert db.scalar(select(func.count()).select_from(Message)) == count


def test_changed_provider_requires_new_disclosure_before_processing(api):
    from app.config import Settings

    with (
        patch(
            "app.config.get_settings",
            return_value=Settings(
                conversation_provider="compatible-http",
                conversation_endpoint="https://model.example/chat",
                conversation_model="new-model",
            ),
        ),
        patch("services.conversation.providers.get_provider") as provider,
    ):
        result = send(api)
        assert result.status_code == 409
        provider.assert_not_called()


def test_latest_messages_and_older_pagination(api):
    client, _, _, records, _ = api
    send(api)
    send(api, text="How do I get support?")
    path = f"/api/v1/conversations/{records['alice'].id}"
    auth = headers(api, "alice")
    latest = client.get(path + "?limit=2", headers=auth).json()
    assert latest["messages"][0]["text"] == "How do I get support?"
    assert latest["next_offset"] == 2
    older = client.get(path + "?limit=2&offset=2", headers=auth).json()
    assert older["messages"][0]["text"] == "I am stressed about my exams"
    assert {m["id"] for m in older["messages"]}.isdisjoint(m["id"] for m in latest["messages"])
    assert client.get(path + "?offset=-1", headers=auth).status_code == 422


@pytest.mark.parametrize("change", ["withdraw", "new-receipt", "deactivate", "hide", "processor"])
def test_consent_or_availability_changed_during_generation_discards_response(
    api, change, monkeypatch
):
    _, db, users, records, _ = api

    class Provider:
        def generate(self, messages):
            if change == "withdraw":
                withdraw_consent(db, users["alice"].id)
            elif change == "new-receipt":
                record_consent(db, users["alice"].id, policy_version="new", text_processing=True)
            elif change == "deactivate":
                users["alice"].is_active = False
            elif change == "hide":
                records["alice"].deleted_at = utcnow()
            else:
                from app.config import Settings

                monkeypatch.setattr(
                    "app.config.get_settings",
                    lambda: Settings(
                        conversation_provider="compatible-http",
                        conversation_endpoint="https://changed.example/chat",
                        conversation_model="changed",
                    ),
                )
            db.commit()
            return Reply("DO NOT STORE THIS RESPONSE", "mock", "mock", "1")

    with patch("services.conversation.providers.get_provider", return_value=Provider()):
        assert send(api).status_code == 409
    assistant = db.scalar(select(Message).where(Message.sender == "assistant"))
    assert assistant.text_content is None
    assert assistant.generation["status"] == "discarded"


def test_provider_error_is_safe_persisted_fallback(api):
    with patch(
        "services.conversation.providers.get_provider",
        side_effect=RuntimeError("secret-provider-error"),
    ):
        result = send(api)
    assert result.status_code == 200
    assert "secret-provider-error" not in result.text
    assert result.json()["messages"][-1]["generation"]["status"] == "fallback"


def test_pending_replay_does_not_generate_twice_and_stale_turn_recovers(api):
    _, db, _, _, _ = api
    request = str(uuid4())
    response = send(api, request_id=request)
    assistant = db.get(Message, response.json()["messages"][-1]["id"])
    assistant.text_content = None
    assistant.generation = {**assistant.generation, "status": "pending"}
    db.commit()
    with patch("services.conversation.providers.get_provider") as provider:
        assert send(api, request_id=request).status_code == 409
        assert send(api, text="Another message while pending").status_code == 409
        assistant.created_at = utcnow() - timedelta(seconds=61)
        db.commit()
        recovered = send(api, request_id=request)
        assert recovered.status_code == 200
        assert recovered.json()["messages"][-1]["generation"]["status"] == "fallback"
        provider.assert_not_called()


@pytest.mark.parametrize("text", ["", "   ", "a" * 4001])
def test_invalid_input(api, text):
    assert send(api, text=text).status_code == 422


@pytest.mark.parametrize(
    "unsafe",
    [
        "I know exactly how you feel.",
        "As a human, I understand.",
        "You have depression.",
        "I diagnose you.",
    ],
)
def test_unsafe_provider_output_replaced(unsafe):
    class Provider:
        def generate(self, messages):
            return Reply(unsafe, "mock", "mock", "1")

    with patch("services.conversation.providers.get_provider", return_value=Provider()):
        assert safe_reply([{"role": "user", "content": "hello"}]).fallback


def test_immediate_safety_response_bypasses_provider():
    with patch("services.conversation.providers.get_provider") as provider:
        reply = safe_reply([{"role": "user", "content": "I might kill myself"}])
        provider.assert_not_called()
    assert "emergency" in reply.text and "cannot dispatch" in reply.text


@pytest.mark.parametrize("kind", ["success", "timeout", "malformed", "oversized", "unsafe"])
def test_http_provider_contract_and_failures(kind):
    import json

    import httpx

    from services.conversation.prompt import SYSTEM_PROMPT

    settings = SimpleNamespace(
        conversation_endpoint="https://model.example/v1/chat/completions",
        conversation_api_key="test-secret",
        conversation_model="requested-model",
        conversation_model_version="pinned-revision-42",
    )
    original = httpx.Client
    seen = []

    def transport(request):
        seen.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer test-secret"
        if kind == "timeout":
            raise httpx.ReadTimeout("private provider error")
        if kind == "malformed":
            return httpx.Response(200, content=b"not json")
        if kind == "oversized":
            return httpx.Response(200, content=b"a" * 65537)
        return httpx.Response(
            200,
            json={
                "model": "reported-model",
                "choices": [
                    {
                        "message": {
                            "content": "I know exactly how you feel."
                            if kind == "unsafe"
                            else "We can explore a small next step."
                        }
                    }
                ],
            },
        )

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(transport=httpx.MockTransport(transport), **kwargs)

    with (
        patch("httpx.Client", side_effect=client),
        patch(
            "services.conversation.providers.get_provider",
            return_value=CompatibleHTTPProvider(settings),
        ),
    ):
        reply = safe_reply([{"role": "user", "content": "Study pressure"}])
    assert seen[0]["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert seen[0]["messages"][1] == {"role": "user", "content": "Study pressure"}
    assert "test-secret" not in reply.text and "private provider error" not in reply.text
    assert reply.fallback == (kind != "success")
    if kind == "success":
        assert reply.model == "reported-model" and reply.version == "pinned-revision-42"


@pytest.mark.parametrize(
    "url",
    [
        "http://remote.example/chat",
        "https://secret@model.example/chat",
        "https://model.example/chat?key=secret",
    ],
)
def test_insecure_endpoint_rejected(url):
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError):
        Settings(conversation_endpoint=url)
