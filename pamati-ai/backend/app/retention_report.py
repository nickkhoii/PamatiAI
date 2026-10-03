"""Aggregate retention review report: python -m app.retention_report. Never deletes records."""

import json
from datetime import timedelta

from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    ConsentRecord,
    Conversation,
    MediaAsset,
    ModelInference,
    ResearchDatasetRecord,
    utcnow,
)
from app.retention import active_holds, deadline, retention_policy


def report(db):
    result = {}
    for category, cls in [
        ("conversations", Conversation),
        ("analysis", ModelInference),
        ("research", ResearchDatasetRecord),
        ("consent_audit", ConsentRecord),
    ]:
        due, held = 0, 0
        for row in db.scalars(select(cls)):
            snapshot = row.retention_snapshot if category == "conversations" else None
            receipt = (
                row
                if category == "consent_audit"
                else (
                    db.get(ConsentRecord, row.consent_record_id)
                    if category in {"analysis", "research"}
                    else None
                )
            )
            if receipt and receipt.disclosure_snapshot:
                snapshot = receipt.disclosure_snapshot.get("retention")
            if active_holds(db, row.student_id, category):
                held += 1
            elif (
                deadline(db, row.student_id, category, row.created_at, snapshot=snapshot)
                <= utcnow()
            ):
                due += 1
        result[category] = {"due_for_review": due, "held": held}
    cap = timedelta(hours=retention_policy(db).raw_media_hours)
    result["raw_media"] = {
        "due_for_erasure": sum(
            min(asset.expires_at, asset.created_at + cap) <= utcnow()
            for asset in db.scalars(select(MediaAsset).where(MediaAsset.purged_at.is_(None)))
        )
    }
    return result


if __name__ == "__main__":
    with SessionLocal() as session:
        print(json.dumps(report(session)))
