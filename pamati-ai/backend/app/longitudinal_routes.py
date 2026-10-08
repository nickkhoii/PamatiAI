from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, HTTPException, Request
from pydantic import model_validator

from app.auth_dependencies import DB, CurrentUser, audit, authorize_student, throttle
from app.auth_routes import Input
from app.longitudinal import rebuild, summaries
from app.persistence import ConsentDenied

router = APIRouter(prefix="/api/v1", tags=["experimental personal longitudinal trends"])


class TrackingRequest(Input):
    start: date | None = None
    end: date | None = None

    @model_validator(mode="after")
    def dates(self):
        if (self.start is None) != (self.end is None):
            raise ValueError("Provide both start and exclusive end dates")
        if self.start and not 1 <= (self.end - self.start).days <= 366:
            raise ValueError("Use a one-to-366-day window")
        if self.end and self.end > datetime.now(UTC).date() + timedelta(days=1):
            raise ValueError("The window cannot extend beyond tomorrow UTC")
        return self


@router.post("/students/{student_id}/longitudinal", status_code=201)
def refresh_tracking(student_id: str, body: TrackingRequest, request: Request, db: DB, user: CurrentUser):
    authorize_student(db, user, "history:read", student_id)
    throttle(db, request, "longitudinal.refresh", user.id, ip_limit=30, subject_limit=10)
    end = datetime.combine(body.end or datetime.now(UTC).date() + timedelta(days=1), time(), UTC)
    start = datetime.combine(body.start, time(), UTC) if body.start else end - timedelta(days=90)
    try:
        ids = rebuild(db, student_id, start, end)
        audit(db, user.id, "longitudinal.generated", "student", student_id)
        db.commit()
    except ConsentDenied as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from None
    result = {"created_trend_ids": ids, "series": summaries(db, student_id)}
    db.commit()
    return result


@router.get("/students/{student_id}/longitudinal")
def read_tracking(student_id: str, db: DB, user: CurrentUser):
    authorize_student(db, user, "history:read", student_id)
    result = summaries(db, student_id)
    audit(db, user.id, "longitudinal.read", "student", student_id)
    db.commit()
    return {"series": result}
