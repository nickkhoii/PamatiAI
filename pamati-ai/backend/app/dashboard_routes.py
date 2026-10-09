"""Role dashboards: bounded SQL queries and explicit, non-secret projections."""

from datetime import date, datetime, time, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import Field, HttpUrl
from sqlalchemy import func, or_, select

from app.auth_dependencies import DB, CurrentUser, audit, authorize_student, require_role
from app.auth_routes import Input
from app.models import (
    AuditLog,
    ConsentRecord,
    Conversation,
    HumanReview,
    ModelVersion,
    ReferralRecord,
    ReviewerAssignment,
    ReviewerProfile,
    RiskSignal,
    Role,
    StudentProfile,
    SupportRequest,
    SystemSetting,
    User,
    WellbeingCheckIn,
)
from app.retention import retained
from app.safety import signal_view, source_live

router = APIRouter(prefix="/api/v1/dashboard", tags=["role dashboards"])


def role_access(db, user, role):
    require_role(role)(db, user)
    permission = {
        "STUDENT": "history:read",
        "COUNSELOR": "review:manage",
        "ADMIN": "accounts:manage",
    }[role]
    if not any(permission in {p.code for p in r.permissions} for r in user.roles):
        raise HTTPException(403, "Access denied")


def assigned_students(db, user):
    latest = (
        select(func.max(ConsentRecord.version))
        .where(ConsentRecord.student_id == StudentProfile.user_id)
        .correlate(StudentProfile)
        .scalar_subquery()
    )
    return (
        select(StudentProfile.user_id)
        .join(User, User.id == StudentProfile.user_id)
        .join(ReviewerAssignment, ReviewerAssignment.student_id == StudentProfile.user_id)
        .join(ConsentRecord, ConsentRecord.student_id == StudentProfile.user_id)
        .where(
            ReviewerAssignment.reviewer_id == user.id,
            ReviewerAssignment.revoked_at.is_(None),
            StudentProfile.deleted_at.is_(None),
            User.deleted_at.is_(None),
            User.is_active.is_(True),
            ConsentRecord.version == latest,
            ConsentRecord.withdrawn_at.is_(None),
            ConsentRecord.reviewer_access.is_(True),
        )
    )


def view(row):
    # Explicit projections exclude credentials, runtime secrets and raw AI scores.
    if isinstance(row, User):
        return {
            "id": row.id,
            "name": row.display_name,
            "email": row.email,
            "status": "active" if row.is_active else "inactive",
            "roles": sorted(r.code for r in row.roles),
            "created_at": row.created_at,
        }
    fields = {
        Conversation: ("id", "status", "created_at"),
        WellbeingCheckIn: ("id", "feeling", "created_at"),
        SupportRequest: ("id", "student_id", "status", "created_at"),
        HumanReview: ("id", "student_id", "risk_signal_id", "decision", "notes", "created_at"),
        ReferralRecord: (
            "id",
            "student_id",
            "human_review_id",
            "service_reference",
            "status",
            "created_at",
        ),
        AuditLog: (
            "id",
            "actor_id",
            "action",
            "resource_type",
            "resource_id",
            "outcome",
            "created_at",
        ),
        ModelVersion: (
            "id",
            "model_identifier",
            "version",
            "modality",
            "license",
            "model_card_reference",
            "created_at",
        ),
        Role: ("id", "code", "description", "created_at"),
    }
    result = {field: getattr(row, field) for field in fields[type(row)]}
    if isinstance(row, Role):
        result["permissions"] = sorted(p.code for p in row.permissions)
    if isinstance(row, HumanReview):
        result["origin"] = "Human-reviewed assessment"
    if isinstance(row, ModelVersion):
        # Registry metadata is public reproducibility data (also in trend provenance).
        # Deployment credentials live in Settings and are never serialized here.
        result["configuration"] = row.configuration
    return result


@router.get("/{role}/{collection}")
def listing(
    role: Literal["STUDENT", "COUNSELOR", "ADMIN"],
    collection: str,
    db: DB,
    user: CurrentUser,
    q: str = Query(default="", max_length=120),
    status: str = Query(default="", max_length=40),
    start: date | None = None,
    end: date | None = None,
    page: int = Query(default=1, ge=1, le=5000),
    limit: int = Query(default=12, ge=1, le=100),
    student: str | None = Query(default=None, max_length=36),
):
    role_access(db, user, role)
    if start and end and start > end:
        raise HTTPException(422, "Start date must precede end date")
    if role == "COUNSELOR":
        profile = db.get(ReviewerProfile, user.id)
        if not profile or profile.deleted_at:
            raise HTTPException(403, "Active counselor profile required")
    if collection == "resources":
        row = db.get(SystemSetting, "institutional_resources")
        items = row.value.get("resources", []) if row else []
        items = [r for r in items if q.casefold() in r["label"].casefold()]
        return {
            "items": items[(page - 1) * limit : page * limit],
            "total": len(items),
            "page": page,
            "limit": limit,
        }
    if role == "ADMIN" and collection == "settings":
        rows = list(
            db.scalars(
                select(SystemSetting).where(
                    SystemSetting.key.in_(["data_retention", "raw_media_retention"])
                )
            )
        )
        items = [
            {"id": r.key, "key": r.key, "value": r.value, "description": r.description}
            for r in rows
            if q.casefold() in r.key.casefold()
        ]
        return {"items": items, "total": len(items), "page": 1, "limit": limit}
    maps = {
        "STUDENT": {
            "conversations": Conversation,
            "check-ins": WellbeingCheckIn,
            "support": SupportRequest,
        },
        "COUNSELOR": {
            "cases": User,
            "queue": RiskSignal,
            "reviews": HumanReview,
            "referrals": ReferralRecord,
            "support": SupportRequest,
        },
        "ADMIN": {"users": User, "roles": Role, "models": ModelVersion, "audit": AuditLog},
    }
    model = maps[role].get(collection)
    if model is None:
        raise HTTPException(404, "Collection not found")
    query = select(model)
    if hasattr(model, "deleted_at"):
        query = query.where(model.deleted_at.is_(None))
    if role == "STUDENT":
        authorize_student(db, user, "history:read", user.id)
        query = query.where(model.student_id == user.id)
    if role == "COUNSELOR":
        if student:
            authorize_student(db, user, "review:manage", student)
        column = User.id if model is User else model.student_id
        query = query.where(column.in_(assigned_students(db, user)))
        if student:
            query = query.where(column == student)
    if q:
        columns = [
            getattr(model, name)
            for name in (
                "id",
                "display_name",
                "email",
                "signal_code",
                "decision",
                "notes",
                "action",
                "model_identifier",
                "code",
                "service_reference",
                "feeling",
            )
            if hasattr(model, name)
        ]
        query = query.where(or_(*(c.contains(q, autoescape=True) for c in columns)))
    if status:
        if model is User:
            if status in {"active", "inactive"}:
                query = query.where(User.is_active.is_(status == "active"))
            else:
                query = query.where(User.roles.any(Role.code == status))
        else:
            column = next(
                (
                    getattr(model, k)
                    for k in (
                        "workflow_state",
                        "status",
                        "decision",
                        "modality",
                        "outcome",
                        "feeling",
                    )
                    if hasattr(model, k)
                ),
                None,
            )
            if column is not None:
                query = query.where(column == status)
    if start:
        query = query.where(model.created_at >= datetime.combine(start, time()))
    if end:
        query = query.where(model.created_at < datetime.combine(end + timedelta(days=1), time()))
    query = query.order_by(model.created_at.desc(), model.id.desc())
    # Source liveness is domain logic: apply it before counting or paginating.
    if model in {Conversation, WellbeingCheckIn}:
        category = "conversations" if model is Conversation else "check_ins"
        rows = [r for r in db.scalars(query) if retained(db, r, category)]
        total = len(rows)
        rows = rows[(page - 1) * limit : page * limit]
    elif model in {RiskSignal, HumanReview, ReferralRecord}:
        rows = list(db.scalars(query))
        rows = [
            r
            for r in rows
            if source_live(
                db,
                r
                if model is RiskSignal
                else r.risk_signal
                if model is HumanReview
                else db.get(HumanReview, r.human_review_id).risk_signal,
            )
        ]
        total = len(rows)
        rows = rows[(page - 1) * limit : page * limit]
    else:
        total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
        rows = list(db.scalars(query.offset((page - 1) * limit).limit(limit)))
    items = [
        signal_view(r) | {"origin": "AI-generated observation"} if model is RiskSignal else view(r)
        for r in rows
    ]
    audit(db, user.id, "dashboard.read", collection)
    db.commit()
    return {"items": items, "total": total, "page": page, "limit": limit}


class CheckInInput(Input):
    feeling: Literal["comfortable", "mixed", "difficult", "prefer_not_to_say"]


@router.post("/check-ins", status_code=201)
def check_in(body: CheckInInput, db: DB, user: CurrentUser):
    from app.retention import retention_policy

    role_access(db, user, "STUDENT")
    authorize_student(db, user, "support:request", user.id)
    row = WellbeingCheckIn(
        student_id=user.id,
        feeling=body.feeling,
        retention_snapshot=retention_policy(db).model_dump(),
    )
    db.add(row)
    db.flush()
    audit(db, user.id, "check_in.created", "check_in", row.id)
    result = view(row)
    db.commit()
    return result


@router.delete("/check-ins/{record_id}", status_code=204)
def remove_check_in(record_id: str, db: DB, user: CurrentUser):
    from app.models import utcnow

    row = db.get(WellbeingCheckIn, record_id)
    if not row or row.deleted_at:
        raise HTTPException(404, "Check-in not found")
    authorize_student(db, user, "privacy:manage", row.student_id)
    row.deleted_at = utcnow()
    audit(db, user.id, "check_in.hidden", "check_in", row.id)
    db.commit()


class ResourceInput(Input):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    label: str = Field(min_length=1, max_length=160)
    description: str = Field(max_length=1000)
    url: HttpUrl


class ResourceDirectory(Input):
    resources: list[ResourceInput] = Field(max_length=100)


@router.put("/resources")
def save_resources(body: ResourceDirectory, db: DB, user: CurrentUser):
    from app.auth_dependencies import require_permission

    role_access(db, user, "ADMIN")
    require_permission("configuration:manage")(db, user)
    if len({r.id for r in body.resources}) != len(body.resources):
        raise HTTPException(422, "Resource identifiers must be unique")
    row = db.get(SystemSetting, "institutional_resources", with_for_update=True)
    if row is None:
        row = SystemSetting(
            key="institutional_resources", description="Institutional support directory"
        )
        db.add(row)
    row.value = body.model_dump(mode="json")
    row.updated_by = user.id
    audit(db, user.id, "resources.updated", "setting")
    db.commit()
    return row.value


@router.get("/observations/students/{student_id}")
def observations(
    student_id: str, db: DB, user: CurrentUser, start: date | None = None, end: date | None = None
):
    authorize_student(db, user, "history:read", student_id)
    consent = db.scalar(
        select(ConsentRecord)
        .where(ConsentRecord.student_id == student_id)
        .order_by(ConsentRecord.version.desc())
        .limit(1)
    )
    if not consent or consent.withdrawn_at or not consent.longitudinal_tracking:
        return {"items": [], "message": "Optional trend tracking is currently off."}
    if start and end and start > end:
        raise HTTPException(422, "Start date must precede end date")
    from app.longitudinal import summaries

    series = summaries(db, student_id)
    items = [
        {
            "id": s["id"],
            "dimension": s["dimension"],
            "model": s["model"],
            "model_version": s["model_version"],
            "daily": [
                d
                for d in s["summary"]["daily"]
                if (not start or d["day"] >= start.isoformat())
                and (not end or d["day"] <= end.isoformat())
            ],
        }
        for s in series
    ]
    audit(db, user.id, "dashboard.trends_read", "student", student_id)
    db.commit()
    return {"items": items}


class SupportState(Input):
    status: Literal["requested", "acknowledged", "closed"]


@router.patch("/support/{request_id}")
def update_support(request_id: str, body: SupportState, db: DB, user: CurrentUser):
    role_access(db, user, "COUNSELOR")
    row = db.get(SupportRequest, request_id, with_for_update=True)
    if not row:
        raise HTTPException(404, "Support request not found")
    authorize_student(db, user, "review:manage", row.student_id)
    row.status = body.status
    audit(db, user.id, "support.updated", "support_request", row.id)
    db.commit()
    return view(row)
