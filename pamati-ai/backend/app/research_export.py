"""Restricted research-worker export; not an administrator content-access API.

Only explicit research membership and live, currently consented sources can be
exported. No raw text, media, case notes, direct identifiers or student timestamps.
"""

import argparse
import hashlib
import hmac
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

from ai.evaluation.contracts import NOT_EVALUATED, DatasetSpec
from ai.evaluation.contracts import ModelVersion as Version
from ai.evaluation.datasets import canonical_digest
from ai.evaluation.metrics import validate_probabilities
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.auth_dependencies import audit
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
    ResearchDatasetRecord,
    TextAnalysis,
    VisualAnalysis,
)
from app.persistence import ConsentDenied, require_purpose


class ExportDenied(ValueError):
    pass


def pseudonym(secret, dataset, version, kind, identifier):
    if len(secret) < 32:
        raise ExportDenied("A separately managed export HMAC key of at least 32 bytes is required")
    material = json.dumps([dataset, version, kind, identifier], separators=(",", ":")).encode()
    return hmac.new(secret, material, hashlib.sha256).hexdigest()


def live_source(db, row, receipt, seen=None):
    seen = set(seen or ())
    if row.id in seen:
        return False
    seen.add(row.id)
    db.refresh(row, with_for_update=True)
    if (
        row.student_id != receipt.student_id
        or row.deleted_at
        or row.processing_status != "completed"
    ):
        return False
    original = db.get(ConsentRecord, row.consent_record_id)
    if (
        not original
        or original.student_id != row.student_id
        or not original.research_data_use
        or original.withdrawn_at
    ):
        return False
    inputs = row.input_modalities or ([row.modality] if row.modality != "multimodal" else [])
    if (
        not inputs
        or len(set(inputs)) != len(inputs)
        or (row.modality != "multimodal" and inputs != [row.modality])
        or any(
            m not in {"text", "audio", "visual"}
            or not getattr(receipt, m + "_processing")
            or not getattr(original, m + "_processing")
            for m in inputs
        )
    ):
        return False
    session = db.get(
        InteractionSession, row.session_id, with_for_update=True, populate_existing=True
    )
    conversation = (
        db.get(Conversation, session.conversation_id, with_for_update=True, populate_existing=True)
        if session
        else None
    )
    if (
        not session
        or session.deleted_at
        or session.student_id != row.student_id
        or not conversation
        or conversation.deleted_at
    ):
        return False
    if row.message_id:
        message = db.get(Message, row.message_id, with_for_update=True, populate_existing=True)
        if not message or message.deleted_at or message.student_id != row.student_id:
            return False
    if row.modality == "multimodal":
        edges = list(
            db.scalars(select(FusionInput).where(FusionInput.fusion_inference_id == row.id))
        )
        sources = [db.get(ModelInference, edge.source_inference_id) for edge in edges]
        if (
            len(sources) != len(inputs)
            or {s.modality for s in sources if s} != set(inputs)
            or any(
                not source
                or source.modality == "multimodal"
                or source.session_id != row.session_id
                or not live_source(db, source, receipt, seen)
                for source in sources
            )
        ):
            return False
    return True


def observation_view(db, row, dataset):
    table = {
        "text": TextAnalysis,
        "audio": AudioAnalysis,
        "visual": VisualAnalysis,
        "multimodal": MultimodalAnalysis,
    }[row.modality]
    analysis = db.get(table, row.id)
    if analysis is None:
        return None
    labels = analysis.labels
    if not isinstance(labels, dict) or type(labels.get("abstained", False)) is not bool:
        return None
    category, probabilities, kind = None, None, None
    if row.modality == "text" and dataset.target == "sentiment":
        category = labels.get("sentiment_category")
        probabilities, kind = labels.get("sentiment_probabilities"), "exclusive"
    elif row.modality in {"text", "audio"} and dataset.target == "emotion":
        probabilities = labels.get("emotion_probabilities")
        kind = labels.get("emotion_probability_kind")
    elif row.modality == "visual" and dataset.target == "observed_expression":
        probabilities = labels.get("expression_probabilities")
        kind = labels.get("probability_kind")
    elif row.modality == "multimodal":
        target = {
            "sentiment": "text_sentiment",
            "emotion": "modeled_affect",
            "observed_expression": "observed_expression",
        }[dataset.target]
        channels = [
            c
            for c in labels.get("combined_output", {}).get("probability_channels", [])
            if c.get("target") == target
        ]
        # Do not silently choose among incompatible late-fusion channels.
        if len(channels) == 1:
            probabilities, kind = (
                channels[0].get("probabilities"),
                channels[0].get("probability_kind"),
            )
    if category is not None and (not isinstance(category, str) or category not in dataset.labels):
        return None
    if probabilities is not None:
        if not isinstance(probabilities, dict):
            return None
        if kind != ("exclusive" if dataset.task == "single_label" else "independent"):
            return None
        try:
            validate_probabilities(probabilities, dataset)
        except ValueError:
            return None
    if category is None and probabilities is None:
        return None
    return {
        "ai_labels": [category] if category else None,
        "probabilities": probabilities,
        "probability_kind": kind if probabilities else None,
        "abstained": labels.get("abstained", False),
        "origin": "AI-generated observation",
        "ground_truth": None,
    }


def build_research_export(db, dataset, secret, *, minimum_group_size=5):
    """Call within a dedicated worker transaction; locks serialize consent withdrawal.

    Membership does not invent ground truth. The output requires independent
    annotations before empirical scoring. Returned rows are pseudonymous, not anonymous.
    """
    if (
        dataset.population_scope != "institutional_consented"
        or dataset.evidence_kind != "unlabeled"
    ):
        raise ExportDenied("Database observations must be exported as unlabeled institutional data")
    if minimum_group_size < 5 or len(secret) < 32:
        raise ExportDenied("A protected key and minimum participant cell size of five are required")
    query = (
        select(ResearchDatasetRecord)
        .where(
            ResearchDatasetRecord.dataset_identifier == dataset.identifier,
            ResearchDatasetRecord.dataset_version == dataset.version,
            ResearchDatasetRecord.deleted_at.is_(None),
            ResearchDatasetRecord.revoked_at.is_(None),
        )
        .order_by(ResearchDatasetRecord.student_id, ResearchDatasetRecord.id)
    )
    candidates, splits, excluded = [], {}, Counter()
    for record in list(db.scalars(query)):
        # Lock user/student/consent before membership, matching withdrawal lock order.
        try:
            receipt = require_purpose(db, record.student_id, "research")
        except ConsentDenied:
            excluded["current_research_consent_unavailable"] += 1
            continue
        db.refresh(record, with_for_update=True)
        if record.deleted_at or record.revoked_at:
            excluded["revoked_membership"] += 1
            continue
        if not record.ethics_approval_reference or not record.deidentification_version:
            excluded["missing_research_provenance"] += 1
            continue
        source = db.get(ModelInference, record.inference_id)
        member_receipt = db.get(ConsentRecord, record.consent_record_id)
        if (
            not source
            or source.student_id != record.student_id
            or not member_receipt
            or member_receipt.student_id != record.student_id
            or not member_receipt.research_data_use
            or member_receipt.withdrawn_at
            or not live_source(db, source, receipt)
        ):
            excluded["unavailable_or_unconsented_source"] += 1
            continue
        observed = observation_view(db, source, dataset)
        model = db.get(ModelVersion, source.model_version_id)
        if not observed or not model:
            excluded["incompatible_or_missing_target"] += 1
            continue
        prior = splits.setdefault(record.student_id, record.split)
        if prior != record.split:
            raise ExportDenied(
                "Participant memberships cross research splits; reconcile before exporting"
            )
        try:
            version = Version(
                identifier=model.model_identifier,
                version=model.version,
                adapter_version=source.adapter_version,
                artifact_sha256=model.artifact_sha256,
                configuration_sha256=canonical_digest(model.configuration),
            )
        except ValueError:
            excluded["invalid_model_provenance"] += 1
            continue
        candidates.append((record, source, observed, version))
    cells = defaultdict(set)
    for record, source, _, _ in candidates:
        cells[(record.split, source.modality)].add(record.student_id)
    rows = []
    for record, source, observed, version in candidates:
        if len(cells[(record.split, source.modality)]) < minimum_group_size:
            excluded["suppressed_small_participant_cell"] += 1
            continue
        code = lambda kind, identifier: pseudonym(
            secret, dataset.identifier, dataset.version, kind, identifier
        )
        rows.append(
            {
                "sample_id": code("inference", source.id),
                "group_id": code("participant", record.student_id),
                "session_code": code("session", source.session_id),
                "split": record.split,
                "modalities": source.input_modalities or [source.modality],
                "observation_modality": source.modality,
                "model_version": version.model_dump(),
                "observation": observed,
            }
        )
    audit(db, None, "research.export_prepared", "research_dataset")
    return {
        "schema_version": "pamati-research-export-v1",
        "dataset": dataset.model_dump(),
        "status": NOT_EVALUATED,
        "rows": rows,
        "exported_row_count": len(rows),
        "minimum_participant_cell_size": minimum_group_size,
        "suppressed_or_excluded_row_count": sum(excluded.values()),
        "privacy": "Pseudonymous restricted research data, not anonymous; no raw inputs, direct identifiers, precise student timestamps or case notes.",
        "annotation_requirement": "AI outputs are never ground truth. Independent human annotations and a versioned labeled dataset are required.",
    }


def write_export(export, output):
    folder = Path(output)
    # Never overwrite another research artifact or write the key/mapping to an export.
    folder.mkdir(parents=True, exist_ok=False)
    with (folder / "observations.jsonl").open("x", encoding="utf-8") as target:
        for row in export["rows"]:
            target.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
    manifest = {k: v for k, v in export.items() if k != "rows"}
    manifest["observations_sha256"] = canonical_digest(export["rows"])
    with (folder / "export.json").open("x", encoding="utf-8") as target:
        json.dump(manifest, target, sort_keys=True, indent=2, allow_nan=False)
    return folder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-spec", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--minimum-group-size", type=int, default=5)
    args = parser.parse_args()
    try:

        from app.db import SessionLocal

        dataset = DatasetSpec.model_validate_json(
            Path(args.dataset_spec).read_text(encoding="utf-8-sig")
        )
        secret = bytes.fromhex(os.environ.get("RESEARCH_EXPORT_HMAC_KEY", ""))
        with SessionLocal() as db, db.begin():
            export = build_research_export(
                db, dataset, secret, minimum_group_size=args.minimum_group_size
            )
            write_export(export, args.output)
    except (ValueError, OSError, SQLAlchemyError):
        parser.exit(
            2,
            "Research export unavailable; verify private worker configuration, consent and permissions.\n",
        )
    print(NOT_EVALUATED)
    print("Pseudonymous research observations exported; independent labels are required.")


if __name__ == "__main__":
    main()
