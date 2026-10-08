"""Bridge message persistence to the consent-aware processing boundary."""

from ai.text.preprocessing import VERSION
from ai.text.registry import registry
from ai.text.service import InferenceService
from sqlalchemy import select

from app import config
from app.models import Message, ModelInference, ModelVersion, TextAnalysis
from app.persistence import create_inference
from app.processing import run_analysis


def configured_models():
    return [registry.resolve(name) for name in config.get_settings().text_analysis_models]


def disclosure():
    return {
        "models": [
            {"identifier": m.metadata.identifier, "version": m.metadata.version,
             "adapter_version": m.metadata.adapter_version,
             "configuration": m.metadata.configuration}
            for m in configured_models()
        ],
        "minimum_confidence": config.get_settings().text_analysis_minimum_confidence,
        "processor": "PamatiAI server",
    }


def enqueue(db, message):
    jobs = []
    for model in configured_models():
        meta = model.metadata
        row = db.scalar(select(ModelVersion).where(
            ModelVersion.model_identifier == meta.identifier,
            ModelVersion.version == meta.version, ModelVersion.modality == "text",
        ))
        if row is None:
            row = ModelVersion(model_identifier=meta.identifier, version=meta.version,
                               modality="text", configuration=meta.configuration)
            db.add(row)
            db.flush()
        elif row.configuration != meta.configuration:
            raise ValueError("Model configuration changed without a new model version")
        job = create_inference(
            db, student_id=message.student_id, session_id=message.session_id,
            message_id=message.id, model_version_id=row.id,
            preprocessing_version=VERSION, adapter_version=meta.adapter_version,
        )
        jobs.append((job.id, model, config.get_settings().text_analysis_minimum_confidence))
    return jobs


class MessageAdapter:
    def __init__(self, db, message_id, model, threshold):
        self.db, self.message_id = db, message_id
        self.service = InferenceService(model, threshold)

    def analyze(self, sample):
        if sample.payload_references != {"text": self.message_id}:
            raise ValueError("Message reference mismatch")
        message = self.db.get(Message, self.message_id, populate_existing=True)
        if not message or message.deleted_at or message.sender != "student":
            raise ValueError("Student message unavailable")
        text = message.text_content
        self.db.commit()  # Release the read transaction before model work.
        return self.service.analyze_text(text)


def execute(db, jobs):
    for inference_id, model, threshold in jobs:
        row = db.get(ModelInference, inference_id)
        adapter = MessageAdapter(db, row.message_id, model, threshold)
        run_analysis(db, inference_id, adapter, {"text": row.message_id})


def results(db, message_id):
    rows = db.execute(
        select(ModelInference, ModelVersion, TextAnalysis)
        .join(ModelVersion, ModelInference.model_version_id == ModelVersion.id)
        .outerjoin(TextAnalysis, TextAnalysis.inference_id == ModelInference.id)
        .where(ModelInference.message_id == message_id, ModelInference.modality == "text",
               ModelInference.deleted_at.is_(None))
        .order_by(ModelInference.created_at, ModelInference.id)
    )
    return [
        {"analysis_id": i.id, "message_id": i.message_id, "model_id": m.id,
         "model": m.model_identifier, "model_version": m.version,
         "adapter_version": i.adapter_version, "preprocessing_version": i.preprocessing_version,
         "consent_record_id": i.consent_record_id, "status": i.processing_status,
         "created_at": i.created_at, "started_at": i.started_at, "completed_at": i.completed_at,
         "confidence": i.confidence, "uncertainty": i.uncertainty,
         "error_code": i.error_code, "result": a.labels if a else None,
         "language": a.language if a else None, "limitations": a.limitations if a else []}
        for i, m, a in rows
    ]
