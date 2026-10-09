"""Private in-app event inbox, projected from currently authorized live records."""

from datetime import date

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.auth_dependencies import DB, CurrentUser, audit, authorize_student
from app.dashboard_routes import assigned_students, role_access
from app.models import (
    DataControlRequest,
    HumanReview,
    NotificationReceipt,
    ReferralRecord,
    ReviewerProfile,
    SupportRequest,
)
from app.safety import source_live

router = APIRouter(prefix="/api/v1/notifications", tags=["private notifications"])


def events(db, user):
    result = []
    roles = {r.code for r in user.roles}
    if "STUDENT" in roles:
        role_access(db, user, "STUDENT")
        authorize_student(db, user, "history:read", user.id)
        for row in db.scalars(select(SupportRequest).where(SupportRequest.student_id == user.id)):
            result.append({"id": f"support:{row.id}:{row.status}", "title": f"Support request: {row.status}",
                           "created_at": row.created_at, "url": "/student"})
        for row in db.scalars(select(ReferralRecord).where(ReferralRecord.student_id == user.id,
                                                        ReferralRecord.deleted_at.is_(None))):
            review = db.get(HumanReview, row.human_review_id)
            if review and source_live(db, review.risk_signal):
                result.append({"id": f"referral:{row.id}:{row.status}", "title": f"Support offer: {row.status}",
                               "created_at": row.created_at, "url": "/student/records"})
        for row in db.scalars(select(DataControlRequest).where(DataControlRequest.student_id == user.id)):
            result.append({"id": f"privacy:{row.id}:{row.status}", "title": f"Privacy request: {row.status}",
                           "created_at": row.created_at, "url": "/student/privacy"})
    if "COUNSELOR" in roles:
        role_access(db, user, "COUNSELOR")
        profile = db.get(ReviewerProfile, user.id)
        if not profile or profile.deleted_at:
            return []
        for row in db.scalars(select(SupportRequest).where(
                SupportRequest.student_id.in_(assigned_students(db, user)), SupportRequest.status == "requested")):
            result.append({"id": f"intake:{row.id}:requested", "title": "An authorized support request awaits review",
                           "created_at": row.created_at, "url": "/counselor"})
    if "ADMIN" in roles:
        role_access(db, user, "ADMIN")
        for row in db.scalars(select(DataControlRequest).where(DataControlRequest.status == "requested")):
            result.append({"id": f"intake-privacy:{row.id}:requested", "title": "A privacy request awaits institutional review",
                           "created_at": row.created_at, "url": "/admin"})
    receipts = set(db.scalars(select(NotificationReceipt.event_key).where(NotificationReceipt.user_id == user.id)))
    for item in result:
        item["read"] = item["id"] in receipts
    return sorted(result, key=lambda item: (item["created_at"], item["id"]), reverse=True)


@router.get("")
def inbox(db: DB, user: CurrentUser, page: int = Query(1, ge=1, le=5000),
          limit: int = Query(12, ge=1, le=100), unread: bool = False,
          q: str = Query("", max_length=120), start: date | None = None, end: date | None = None):
    if start and end and start > end:
        raise HTTPException(422, "Start date must precede end date")
    rows = events(db, user)
    unread_count = sum(not row["read"] for row in rows)
    rows = [r for r in rows if (not unread or not r["read"]) and q.casefold() in r["title"].casefold()
            and (not start or r["created_at"].date() >= start)
            and (not end or r["created_at"].date() <= end)]
    audit(db, user.id, "notifications.read", "notification")
    db.commit()
    return {"items": rows[(page - 1) * limit:page * limit], "total": len(rows),
            "unread_count": unread_count, "page": page, "limit": limit,
            "delivery": "in-app only", "continuous_monitoring": False}


@router.post("/{event_key}/read", status_code=204)
def mark_read(event_key: str, db: DB, user: CurrentUser):
    if len(event_key) > 100 or event_key not in {r["id"] for r in events(db, user)}:
        raise HTTPException(404, "Notification not found")
    # Serialize receipts per owner to make retries and simultaneous clicks idempotent.
    from app.auth_dependencies import lock_user
    lock_user(db, user.id)
    receipt = db.scalar(select(NotificationReceipt).where(NotificationReceipt.user_id == user.id,
                        NotificationReceipt.event_key == event_key).with_for_update())
    if receipt is None:
        db.add(NotificationReceipt(user_id=user.id, event_key=event_key))
    audit(db, user.id, "notification.read_marked", "notification")
    db.commit()
