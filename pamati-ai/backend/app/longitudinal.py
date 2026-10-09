"""Longitudinal summaries with current purpose consent and immutable source lineage."""
import json
from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from ai.longitudinal.algorithms import day_start, validate_config
from ai.longitudinal.interface import Observation, TrackingConfig
from ai.longitudinal.registry import registry
from ai.text.confidence import bounded, probabilities
from sqlalchemy import func, select

from app import config
from app.models import (
    AudioAnalysis,
    ConsentRecord,
    Conversation,
    FusionInput,
    InteractionSession,
    Message,
    ModelInference,
    ModelVersion,
    MultimodalAnalysis,
    SentimentObservation,
    SentimentTrend,
    TextAnalysis,
    TrendObservation,
    VisualAnalysis,
)
from app.persistence import ConsentDenied, create_trend, require_purpose
from app.retention import retained

ANALYSES = {"text": TextAnalysis, "audio": AudioAnalysis, "visual": VisualAnalysis, "multimodal": MultimodalAnalysis}


def configured():
    settings = config.get_settings()
    options = TrackingConfig(**settings.longitudinal_configuration)
    validate_config(options)
    return registry.resolve(settings.longitudinal_algorithm), options


def disclosure():
    algorithm, options = configured()
    return {"experimental": True, "algorithm": algorithm.identifier, "version": algorithm.version,
            "configuration": asdict(options), "timezone": "UTC", "score": "no_universal_mental_health_score"}


def authorize_tracking(db, student_id, *, processing=False):
    from app.consent_policy import POLICY_VERSION

    receipt = require_purpose(db, student_id, "longitudinal")
    if processing and (receipt.policy_version != POLICY_VERSION or not receipt.disclosure_snapshot
                       or receipt.disclosure_snapshot.get("longitudinal_processing") != disclosure()):
        raise ConsentDenied("Review the current experimental longitudinal disclosure")
    return receipt


def source_available(db, row, receipt):
    row = db.scalar(select(ModelInference).where(ModelInference.id == row.id)
                    .with_for_update().execution_options(populate_existing=True))
    if not row or row.student_id != receipt.student_id:
        return False
    if not retained(db, row, "analysis") or row.processing_status != "completed":
        return False
    inputs = row.input_modalities or ([row.modality] if row.modality != "multimodal" else [])
    if not inputs or any(m not in {"text", "audio", "visual"} or not getattr(receipt, m + "_processing") for m in inputs):
        return False
    original = db.get(ConsentRecord, row.consent_record_id)
    if not original or not original.longitudinal_tracking:
        return False
    interaction = db.scalar(select(InteractionSession).where(InteractionSession.id == row.session_id)
                            .with_for_update().execution_options(populate_existing=True))
    if not interaction or interaction.deleted_at:
        return False
    conversation = db.scalar(select(Conversation).where(Conversation.id == interaction.conversation_id)
                             .with_for_update().execution_options(populate_existing=True))
    if not retained(db, conversation, "conversations"):
        return False
    if row.message_id:
        message = db.scalar(select(Message).where(Message.id == row.message_id)
                            .with_for_update().execution_options(populate_existing=True))
        if not message or message.deleted_at or message.sender != "student":
            return False
    if row.modality == "multimodal":
        edges = list(db.scalars(select(FusionInput).where(FusionInput.fusion_inference_id == row.id)))
        if len(edges) != len(inputs):
            return False
        for edge in edges:
            source = db.get(ModelInference, edge.source_inference_id, populate_existing=True)
            if (not source or source.modality == "multimodal" or source.session_id != row.session_id
                    or not source_available(db, source, receipt)):
                return False
    return True


def dimensions(row, labels):
    """Preserve distinct observable targets and probability semantics; never infer diagnoses."""
    result = {}
    if row.modality == "text" and labels.get("sentiment_polarity") is not None:
        result["sentiment_polarity"] = bounded(labels["sentiment_polarity"], -1, 1)
    if row.modality in {"text", "audio"}:
        if labels.get("emotion_probabilities"):
            probabilities(labels["emotion_probabilities"], distribution=labels.get("emotion_probability_kind") == "exclusive")
        for label, score in (labels.get("emotion_probabilities") or {}).items():
            if label not in {"joy", "sadness", "anger", "fear", "disgust", "surprise", "neutral", "calm", "excitement", "boredom"}:
                raise ValueError("Unsupported affect label")
            kind = labels.get("emotion_probability_kind")
            if kind not in {"exclusive", "independent"}:
                raise ValueError("Unknown affect probability semantics")
            result[f"affect_{kind}:{label}"] = bounded(score)
    if row.modality == "visual":
        if labels.get("expression_probabilities"):
            probabilities(labels["expression_probabilities"], distribution=labels.get("probability_kind") == "exclusive")
        for label, score in (labels.get("expression_probabilities") or {}).items():
            from ai.visual.normalization import EXPRESSIONS
            if label not in EXPRESSIONS or labels.get("probability_kind") not in {"exclusive", "independent"}:
                raise ValueError("Unsupported observable expression")
            result[f"expression_{labels['probability_kind']}:{label}"] = bounded(score)
    if row.modality == "multimodal":
        outputs = labels.get("individual_modality_outputs", {})
        by_id = {value["source_id"]: modality for modality, value in outputs.items()}
        for channel in labels.get("combined_output", {}).get("probability_channels", []):
            participants = "_".join(sorted({by_id[s] for s in channel["source_ids"]}))
            target, kind = channel["target"], channel["probability_kind"]
            from ai.multimodal.channels import LABELS
            if target not in LABELS or kind not in {"exclusive", "independent"}:
                raise ValueError("Unsupported fusion target")
            allowed = {"text_sentiment": {"text"}, "modeled_affect": {"text", "audio"},
                       "observed_expression": {"visual"}}[target]
            if set(participants.split("_")) - allowed:
                raise ValueError("Source modality cannot establish this target")
            probabilities(channel["probabilities"], distribution=kind == "exclusive")
            for label, score in channel["probabilities"].items():
                if label not in LABELS[target]:
                    raise ValueError("Unsupported fusion label")
                dimension = f"{target}_{kind}_{participants}:{label}"
                if dimension in result or len(dimension) > 60:
                    raise ValueError("Ambiguous fusion channel")
                result[dimension] = bounded(score)
    return result


def rebuild(db, student_id, start, end):
    start, end = day_start(start), day_start(end)
    if not 1 <= (end - start).days <= 366:
        raise ValueError("Use a one-to-366-day tracking window")
    receipt = authorize_tracking(db, student_id, processing=True)
    algorithm, options = configured()
    fingerprint = sha256(json.dumps(disclosure(), sort_keys=True).encode()).hexdigest()
    evidence_start = start - timedelta(days=options.baseline_days)
    source_time = func.coalesce(Message.created_at, ModelInference.created_at)
    sources = list(db.scalars(select(ModelInference).outerjoin(Message, Message.id == ModelInference.message_id).where(
        ModelInference.student_id == student_id, source_time >= evidence_start.replace(tzinfo=None),
        source_time < end.replace(tzinfo=None), ModelInference.deleted_at.is_(None),
        ModelInference.processing_status == "completed",
    ).order_by(ModelInference.created_at, ModelInference.id).limit(5001)))
    if len(sources) > 5000:
        raise ValueError("Too many sources: select a shorter time window")
    grouped, source_rows = defaultdict(list), {}
    excluded_count = 0
    for row in sources:
        if not source_available(db, row, receipt):
            excluded_count += 1
            continue
        analysis = db.get(ANALYSES[row.modality], row.id)
        if not analysis or analysis.labels.get("abstained"):
            excluded_count += 1
            continue
        message = db.get(Message, row.message_id) if row.message_id else None
        observed_at = message.created_at if message else row.created_at
        if not evidence_start.replace(tzinfo=None) <= observed_at < end.replace(tzinfo=None):
            continue
        try:
            scores = dimensions(row, analysis.labels)
        except (ValueError, TypeError, KeyError):
            excluded_count += 1
            continue
        for dimension, score in scores.items():
            existing = db.scalar(select(SentimentObservation).where(SentimentObservation.inference_id == row.id,
                                                                   SentimentObservation.dimension == dimension))
            if existing is None:
                existing = SentimentObservation(student_id=student_id, inference_id=row.id,
                                                 dimension=dimension, score=score, observed_at=observed_at)
                db.add(existing)
                db.flush()
            if existing.deleted_at:
                continue
            if existing.score != score or existing.observed_at != observed_at:
                raise ValueError("Observation changed without new inference provenance")
            key = (row.model_version_id, row.preprocessing_version, row.adapter_version, dimension)
            grouped[key].append(Observation(existing.id, row.session_id, existing.observed_at.replace(tzinfo=UTC),
                                            existing.score, row.confidence, row.uncertainty))
            source_rows[existing.id] = row
    if len(grouped) > 128:
        raise ValueError("Too many experimental series: reduce configured models or time window")
    sessions = tuple((row.id, row.created_at.replace(tzinfo=UTC)) for row in db.scalars(
        select(InteractionSession).join(Conversation).where(
            InteractionSession.student_id == student_id, InteractionSession.deleted_at.is_(None),
            Conversation.deleted_at.is_(None), InteractionSession.created_at >= start.replace(tzinfo=None),
            InteractionSession.created_at < end.replace(tzinfo=None),
        )))
    created = []
    for (model_id, preprocessing, adapter, dimension), records in grouped.items():
        if not any(start <= record.timestamp < end for record in records):
            continue
        summary = algorithm.summarize(tuple(records), start, end, options, sessions=sessions)
        # Validate before creating lineage too: a changed source must not reach a
        # MySQL evidence trigger while pending edges from another dimension flush.
        for source in source_rows.values():
            if not source_available(db, source, receipt):
                raise ConsentDenied("Tracking source became unavailable")
        if (summary.get("schema_version") != "longitudinal-observation-v1"
                or set(summary.get("source_observation_ids", [])) != {record.id for record in records}):
            raise ValueError("Tracking algorithm must preserve normalized evidence lineage")
        json.dumps(summary, allow_nan=False)
        summary.update({"dimension": dimension, "source_model_version_id": model_id,
                        "preprocessing_version": preprocessing, "adapter_version": adapter,
                        "algorithm_configuration_sha256": fingerprint, "excluded_source_count": excluded_count,
                        "timestamp_basis": "message_creation_or_inference_submission", "generated_at": datetime.now(UTC).isoformat()})
        # Include baseline evidence in the persisted half-open provenance window.
        trend = create_trend(db, student_id=student_id, model_version_id=model_id, dimension=dimension,
                             window_start=evidence_start.replace(tzinfo=None), window_end=end.replace(tzinfo=None),
                             algorithm_version=f"{algorithm.version}:{fingerprint}", sample_count=len(records), summary=summary)
        for record in records:
            db.add(TrendObservation(trend_id=trend.id, observation_id=record.id, student_id=student_id))
        db.flush()
        created.append(trend.id)
    # Locks held by current_consent serialize consent/deletion changes with publication.
    latest = authorize_tracking(db, student_id, processing=True)
    if latest.id != receipt.id or sha256(json.dumps(disclosure(), sort_keys=True).encode()).hexdigest() != fingerprint:
        raise ConsentDenied("Tracking configuration or consent changed")
    for source in source_rows.values():
        if not source_available(db, source, latest):
            raise ConsentDenied("Tracking source became unavailable")
    db.flush()
    return created


def summaries(db, student_id):
    try:
        receipt = authorize_tracking(db, student_id)
    except ConsentDenied:
        return []
    rows = list(db.scalars(select(SentimentTrend).where(SentimentTrend.student_id == student_id,
                                                       SentimentTrend.deleted_at.is_(None))
                          .order_by(SentimentTrend.created_at.desc(), SentimentTrend.id.desc()).limit(512)))
    result, seen = [], set()
    for row in rows:
        if not retained(db, row, "analysis"):
            continue
        summary = row.summary
        if summary.get("schema_version") != "longitudinal-observation-v1":
            continue
        key = (row.model_version_id, summary.get("preprocessing_version"), summary.get("adapter_version"), row.dimension)
        if key in seen:
            continue
        seen.add(key)
        evidence = list(db.scalars(select(SentimentObservation).join(TrendObservation,
                            TrendObservation.observation_id == SentimentObservation.id)
                            .where(TrendObservation.trend_id == row.id)))
        if (len(evidence) != row.sample_count or any(o.deleted_at or not source_available(db, o.inference, receipt) for o in evidence)):
            continue
        model = db.get(ModelVersion, row.model_version_id)
        result.append({"id": row.id, "dimension": row.dimension, "model": model.model_identifier,
                       "model_version": model.version, "model_configuration": model.configuration,
                       "consent_record_id": row.consent_record_id, "created_at": row.created_at,
                       "summary": summary})
    return result
