"""Reserve turns atomically, release locks for providers, and recheck consent on publication."""

from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, field_validator
from sqlalchemy import func, select

from app.auth_dependencies import DB, CurrentUser, audit, authorize_student, throttle
from app.auth_routes import Input
from app.consent_policy import POLICY_VERSION, policy_document
from app.models import Conversation, InteractionSession, Message, utcnow
from app.persistence import ConsentDenied, current_consent
from app.retention import retained
from app.safety import record_signals, screen
from app.text_analysis import enqueue, execute, results
from services.conversation.prompt import PROMPT_VERSION
from services.conversation.providers import FALLBACK, safe_reply
from services.safety.resources import supportive_message

router = APIRouter(prefix="/api/v1", tags=["conversation"])


class TurnInput(Input):
    request_id: UUID
    text: str = Field(min_length=1, max_length=4000)

    @field_validator("text")
    @classmethod
    def meaningful(cls, value):
        if not value.strip() or "\x00" in value:
            raise ValueError("Enter a message")
        return value.strip()


def view(message):
    return {
        "id": message.id,
        "session_id": message.session_id,
        "sender": message.sender,
        "text": message.text_content,
        "created_at": message.created_at,
        "generation": message.generation,
    }


@router.post("/conversations/{conversation_id}/messages")
def send_message(
    conversation_id: str, body: TurnInput, request: Request, db: DB, user: CurrentUser
):
    conversation = db.get(Conversation, conversation_id)
    if not retained(db, conversation, "conversations"):
        raise HTTPException(404, "Conversation not found")
    authorize_student(db, user, "conversation:manage", conversation.student_id)
    throttle(db, request, "conversation.turn", user.id, ip_limit=120, subject_limit=60)
    try:
        consent = current_consent(db, conversation.student_id)
        if not consent.text_processing:
            raise ConsentDenied("Text consent is required to send messages")
        policy = policy_document()
        processing = policy["conversation_processing"]
        if (
            consent.policy_version != POLICY_VERSION
            or not consent.disclosure_snapshot
            or consent.disclosure_snapshot.get("conversation_processing") != processing
            or consent.disclosure_snapshot.get("text_analysis_processing", {"models": []})
            != policy["text_analysis_processing"]
            or consent.disclosure_snapshot.get("safety_processing") != policy["safety_processing"]
        ):
            raise ConsentDenied(
                "Review the current consent information and conversational processor before sending"
            )
    except ConsentDenied as exc:
        raise HTTPException(409, str(exc)) from None
    safety_observations, safety_policy, safety_resources = screen(body.text)
    conversation = db.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if conversation.deleted_at or conversation.status != "open":
        raise HTTPException(409, "Conversation is unavailable")
    previous = db.scalar(select(Message).where(Message.request_id == str(body.request_id)))
    if previous:
        session = db.get(InteractionSession, previous.session_id)
        if session.conversation_id != conversation_id or previous.text_content != body.text:
            raise HTTPException(409, "Request identifier already used")
        assistant = db.scalar(
            select(Message).where(
                Message.session_id == previous.session_id,
                Message.sequence_number == previous.sequence_number + 1,
            )
        )
        if assistant.generation["status"] == "pending":
            if assistant.created_at > utcnow() - timedelta(seconds=60):
                raise HTTPException(409, "Response is still being prepared. Reload shortly.")
            assistant.text_content = FALLBACK
            assistant.generation = {
                **assistant.generation,
                "status": "fallback",
                "provider": "local-fallback",
                "model": "support-fallback",
                "version": "1",
            }
        db.commit()
        return {"messages": [view(previous), view(assistant)]}
    session = db.scalar(
        select(InteractionSession)
        .where(
            InteractionSession.conversation_id == conversation_id,
            InteractionSession.deleted_at.is_(None),
            InteractionSession.ended_at.is_(None),
        )
        .order_by(InteractionSession.created_at.desc())
        .limit(1)
    )
    if session is None:
        session = InteractionSession(conversation_id=conversation_id, student_id=user.id)
        db.add(session)
        db.flush()
    pending = db.scalar(
        select(Message).where(
            Message.session_id == session.id,
            Message.sender == "assistant",
            Message.text_content.is_(None),
            Message.deleted_at.is_(None),
            Message.generation["status"].as_string() == "pending",
        )
    )
    if pending and pending.generation and pending.generation.get("status") == "pending":
        if not safety_observations and pending.created_at > utcnow() - timedelta(seconds=60):
            raise HTTPException(409, "Wait for the current response before sending another message")
        pending.text_content = FALLBACK
        pending.generation = {
            **pending.generation,
            "status": "fallback",
            "provider": "local-fallback",
            "model": "support-fallback",
            "version": "1",
        }
    sequence = (
        db.scalar(select(func.max(Message.sequence_number)).where(Message.session_id == session.id))
        or 0
    ) + 1
    student = Message(
        session_id=session.id,
        student_id=user.id,
        sender="student",
        sequence_number=sequence,
        text_content=body.text,
        request_id=str(body.request_id),
    )
    assistant = Message(
        session_id=session.id,
        student_id=user.id,
        sender="assistant",
        sequence_number=sequence + 1,
        generation={
            "status": "pending",
            "consent_id": consent.id,
            "prompt_version": PROMPT_VERSION,
        },
    )
    db.add_all([student, assistant])
    conversation.updated_at = utcnow()
    db.flush()
    if safety_observations:
        try:
            record_signals(db, student, safety_observations, safety_policy, consent)
        except ConsentDenied as exc:
            db.rollback()
            raise HTTPException(409, str(exc)) from None
        priority = "urgent" if any(c.priority == "urgent" for c in safety_observations) else "prompt"
        assistant.text_content = supportive_message(priority, safety_resources)
        assistant.generation = {**assistant.generation, "status": "completed", "provider": "local-safety",
                                "model": "literal-safety-analysis", "version": safety_policy.fingerprint,
                                "safety_priority": priority, "policy_version": safety_policy.version}
        audit(db, user.id, "conversation.immediate_support", "conversation", conversation_id)
        db.commit()
        return {"messages": [view(student), view(assistant)]}
    analysis_jobs = enqueue(db, student)
    context = list(
        db.scalars(
            select(Message)
            .join(InteractionSession, Message.session_id == InteractionSession.id)
            .where(
                InteractionSession.conversation_id == conversation_id,
                InteractionSession.deleted_at.is_(None),
                Message.deleted_at.is_(None),
                Message.text_content.is_not(None),
                Message.sender.in_(["student", "assistant"]),
            )
            .order_by(Message.created_at.desc(), Message.sequence_number.desc())
            .limit(20)
        )
    )
    messages = [
        {"role": "user" if m.sender == "student" else "assistant", "content": m.text_content}
        for m in reversed(context)
    ]
    receipt_id, assistant_id = consent.id, assistant.id
    audit(db, user.id, "conversation.message_submitted", "conversation", conversation_id)
    db.commit()
    reply = safe_reply(messages)
    execute(db, analysis_jobs)
    # Fresh locking reads defeat stale ORM state and MySQL repeatable-read snapshots.
    try:
        latest = current_consent(db, user.id)
        allowed = (
            latest.id == receipt_id
            and latest.text_processing
            and policy_document()["conversation_processing"] == processing
            and policy_document()["safety_processing"] == policy["safety_processing"]
        )
    except ConsentDenied:
        allowed = False
    conversation = db.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assistant = db.get(Message, assistant_id, populate_existing=True)
    if conversation is None or assistant is None:
        db.commit()
        raise HTTPException(409, "Conversation records are no longer available")
    allowed = (
        retained(db, conversation, "conversations") and allowed
        and not conversation.deleted_at
        and conversation.status == "open"
        and not assistant.deleted_at
    )
    if assistant.generation["status"] != "pending":
        db.commit()
        return {"messages": [view(student), view(assistant)]}
    assistant.generation = {
        **assistant.generation,
        "status": "completed"
        if allowed and not reply.fallback
        else "fallback"
        if allowed
        else "discarded",
        "provider": reply.provider,
        "model": reply.model,
        "version": reply.version,
    }
    assistant.text_content = reply.text if allowed else None
    audit(
        db,
        user.id,
        "conversation.response_saved" if allowed else "conversation.response_discarded",
        "conversation",
        conversation_id,
    )
    db.commit()
    if not allowed:
        raise HTTPException(
            409, "Consent or conversation changed; the generated response was discarded"
        )
    return {"messages": [view(student), view(assistant)]}


@router.get("/conversations/{conversation_id}/messages/{message_id}/analyses")
def message_analyses(conversation_id: str, message_id: str, db: DB, user: CurrentUser):
    conversation = db.get(Conversation, conversation_id)
    if not retained(db, conversation, "conversations"):
        raise HTTPException(404, "Conversation not found")
    authorize_student(db, user, "history:read", conversation.student_id)
    message = db.get(Message, message_id)
    session = db.get(InteractionSession, message.session_id) if message else None
    if (not message or message.deleted_at or not session or session.deleted_at
            or session.conversation_id != conversation_id):
        raise HTTPException(404, "Message not found")
    result = results(db, message_id)
    audit(db, user.id, "text_analysis.read", "message", message_id)
    db.commit()
    return {"analyses": result}
