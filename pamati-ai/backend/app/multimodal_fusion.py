"""Consent-gated fusion of explicitly selected, same-session derived observations."""
import json
from dataclasses import asdict
from datetime import UTC
from hashlib import sha256

from ai.multimodal.interface import MODALITIES, FusionConfig, ModalityObservation
from ai.multimodal.registry import registry
from ai.multimodal.service import VERSION, FusionService
from ai.multimodal.strategies import LateFusion
from sqlalchemy import select

from app import config
from app.models import (
    AudioAnalysis,
    Conversation,
    InteractionSession,
    Message,
    ModelInference,
    ModelVersion,
    MultimodalAnalysis,
    TextAnalysis,
    VisualAnalysis,
)
from app.persistence import ConsentDenied, create_inference, current_consent
from app.processing import run_analysis
from app.retention import retained


def configured():
    settings = config.get_settings()
    return registry.resolve(settings.multimodal_fusion_strategy), FusionConfig(
        weights=dict(settings.multimodal_fusion_weights),
        minimum_confidence=settings.multimodal_fusion_minimum_confidence,
        maximum_source_span_seconds=settings.multimodal_fusion_maximum_source_span_seconds,
    )


def disclosure():
    if not config.get_settings().multimodal_fusion_enabled:
        return {"enabled": False}
    strategy, options = configured()
    FusionService(strategy, options)
    return {"enabled": True, "experimental": True, "processor": "PamatiAI server",
            "schema_version": VERSION, "strategy": asdict(strategy.metadata),
            "configuration": asdict(options), "raw_inputs": False}


def authorize_fusion(db, session_id, student_id):
    from app.consent_policy import POLICY_VERSION

    receipt = current_consent(db, student_id)
    if not config.get_settings().multimodal_fusion_enabled:
        raise ConsentDenied("Optional multimodal fusion is disabled")
    if (receipt.policy_version != POLICY_VERSION or not receipt.disclosure_snapshot
            or receipt.disclosure_snapshot.get("multimodal_fusion_processing") != disclosure()):
        raise ConsentDenied("Review the current experimental fusion disclosure")
    interaction = db.scalar(select(InteractionSession).where(InteractionSession.id == session_id)
                            .with_for_update().execution_options(populate_existing=True))
    if (not interaction or interaction.student_id != student_id or interaction.deleted_at or interaction.ended_at):
        raise ConsentDenied("An active student-owned session is required")
    conversation = db.scalar(select(Conversation).where(Conversation.id == interaction.conversation_id)
                             .with_for_update().execution_options(populate_existing=True))
    if not retained(db, conversation, "conversations") or conversation.status != "open":
        raise ConsentDenied("Conversation is unavailable")
    return receipt


def load_sources(db, session_id, student_id, ids, receipt):
    observations, excluded, seen = [], {}, set()
    classes = {"text": TextAnalysis, "audio": AudioAnalysis, "visual": VisualAnalysis}
    for source_id in ids:
        row = db.scalar(select(ModelInference).where(ModelInference.id == source_id)
                        .with_for_update().execution_options(populate_existing=True))
        if not row:
            continue  # Unknown references never require another modality.
        if row.student_id != student_id or row.session_id != session_id or row.modality not in MODALITIES:
            raise ConsentDenied("Sources must belong to this student's session")
        modality = row.modality
        if modality in seen:
            raise ValueError("Select one source per modality")
        seen.add(modality)
        if not getattr(receipt, f"{modality}_processing"):
            excluded[modality] = "unconsented"
            continue  # Do not read unconsented analysis content.
        if not retained(db, row, "analysis") or row.processing_status != "completed":
            excluded[modality] = "deleted" if row.deleted_at else row.processing_status
            continue
        if row.message_id:
            message = db.get(Message, row.message_id, populate_existing=True)
            if not message or message.deleted_at:
                excluded[modality] = "message_unavailable"
                continue
        analysis = db.get(classes[modality], row.id, populate_existing=True)
        if not analysis or not row.completed_at:
            excluded[modality] = "missing_analysis"
            continue
        model = db.get(ModelVersion, row.model_version_id)
        observations.append(ModalityObservation(
            modality, row.id, row.processing_status, analysis.labels, model.model_identifier,
            model.version, row.completed_at.replace(tzinfo=UTC).isoformat(),
            model_configuration={"model_configuration": model.configuration,
                                 "model_version_id": model.id, "artifact_sha256": model.artifact_sha256,
                                 "consent_record_id": row.consent_record_id, "message_id": row.message_id,
                                 "analysis_timestamp": analysis.created_at.isoformat()},
            preprocessing_version=row.preprocessing_version, adapter_version=row.adapter_version,
            confidence=row.confidence, uncertainty=row.uncertainty, limitations=tuple(analysis.limitations),
        ))
    return observations, excluded


class FusionAdapter:
    def __init__(self, db, session_id, student_id, receipt_id, sources, excluded, service, processor):
        self.db, self.session_id, self.student_id = db, session_id, student_id
        self.receipt_id, self.sources, self.excluded = receipt_id, sources, excluded
        self.service, self.processor = service, processor

    def analyze(self, sample):
        self.validate_publication(self.db, None, None)
        if sample.payload_references != {s.modality: s.source_id for s in self.sources}:
            raise ConsentDenied("Fusion manifest changed")
        self.db.commit()
        result = self.service.fuse(self.sources, excluded=self.excluded,
                                   consented_modalities=self.processor["consented_modalities"])
        result.labels["requested_source_inference_ids"] = self.processor["requested_source_inference_ids"]
        result.labels["consent_record_id"] = self.receipt_id
        result.labels["consented_modalities"] = self.processor["consented_modalities"]
        return result

    def validate_publication(self, db, row, result):
        receipt = authorize_fusion(db, self.session_id, self.student_id)
        if receipt.id != self.receipt_id or disclosure() != self.processor["disclosure"]:
            raise ConsentDenied("Fusion authorization or configuration changed")
        sources, excluded = load_sources(db, self.session_id, self.student_id,
                                         [s.source_id for s in self.sources], receipt)
        if excluded or sources != self.sources:
            raise ConsentDenied("Fusion source changed or became unavailable")


def analyze_fusion(db, *, session_id, student_id, source_inference_ids):
    if not 1 <= len(source_inference_ids) <= 3 or len(set(source_inference_ids)) != len(source_inference_ids):
        raise ValueError("Select one to three distinct source analyses")
    receipt = authorize_fusion(db, session_id, student_id)
    strategy, options = configured()
    observations, excluded = load_sources(db, session_id, student_id, source_inference_ids, receipt)
    consented = [m for m in MODALITIES if getattr(receipt, f"{m}_processing")]
    # Validate and align without invoking a learned strategy twice.
    prepared = FusionService(LateFusion(), options).fuse(observations, consented_modalities=consented, excluded=excluded)
    accepted = set(prepared.source_inference_ids)
    sources = [s for s in observations if s.source_id in accepted]
    if not sources:
        raise ConsentDenied("No usable consented source analysis is available")
    processor = disclosure()
    fingerprint = sha256(json.dumps(processor, sort_keys=True, allow_nan=False).encode()).hexdigest()
    version = db.scalar(select(ModelVersion).where(ModelVersion.model_identifier == strategy.metadata.identifier,
                                                  ModelVersion.version == fingerprint,
                                                  ModelVersion.modality == "multimodal"))
    if version is None:
        version = ModelVersion(model_identifier=strategy.metadata.identifier, version=fingerprint,
                               modality="multimodal", artifact_sha256=strategy.metadata.artifact_sha256,
                               configuration=processor)
        db.add(version)
        db.flush()
    elif version.configuration != processor:
        raise ValueError("Fusion configuration fingerprint conflict")
    row = create_inference(db, student_id=student_id, session_id=session_id, model_version_id=version.id,
                           preprocessing_version=VERSION, adapter_version=strategy.metadata.version,
                           input_modalities=[s.modality for s in sources])
    inference_id = row.id
    adapter = FusionAdapter(db, session_id, student_id, receipt.id, sources,
                            prepared.labels["excluded_modalities"], FusionService(strategy, options),
                            {"disclosure": processor, "consented_modalities": consented,
                             "requested_source_inference_ids": list(source_inference_ids)})
    db.commit()
    run_analysis(db, inference_id, adapter, {s.modality: s.source_id for s in sources})
    return inference_id


def result_view(db, row):
    analysis = db.get(MultimodalAnalysis, row.id)
    model = db.get(ModelVersion, row.model_version_id)
    return {"analysis_id": row.id, "session_id": row.session_id, "status": row.processing_status,
            "consent_record_id": row.consent_record_id, "model_version_id": model.id,
            "model_version": model.version, "configuration": model.configuration,
            "created_at": row.created_at, "completed_at": row.completed_at,
            "confidence": row.confidence, "uncertainty": row.uncertainty,
            "error_code": row.error_code, "result": analysis.labels if analysis else None}
