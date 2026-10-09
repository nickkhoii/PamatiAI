"""JSONL ingestion and split validation. Inputs remain private and are not report fields."""

import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from ai.evaluation.contracts import Sample


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path, contract):
    records = []
    with Path(path).open(encoding="utf-8-sig") as source:
        for index, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                records.append(contract.model_validate_json(line))
            except (ValidationError, ValueError):
                # ValidationError repr includes input values; never forward it to shared logs.
                raise ValueError(
                    f"Invalid {contract.__name__} record at line {index}; inspect the private input locally."
                ) from None
    return records


def validate_dataset(samples, spec):
    seen, groups, fingerprints = set(), {}, {}
    for sample in samples:
        if sample.sample_id in seen:
            raise ValueError("Duplicate sample ID; evaluation unit must be unique across splits.")
        seen.add(sample.sample_id)
        if spec.split_unit == "participant" and not sample.group_id:
            raise ValueError(
                "Participant-independent evaluation requires a private group ID on every sample."
            )
        if sample.group_id:
            split = groups.setdefault(sample.group_id, sample.split)
            if split != sample.split:
                raise ValueError("Participant/group leakage across dataset splits.")
        if sample.labels is not None:
            if len(set(sample.labels)) != len(sample.labels) or set(sample.labels) - set(
                spec.labels
            ):
                raise ValueError("Gold annotations must match the versioned label vocabulary.")
            if spec.task == "single_label" and len(sample.labels) != 1:
                raise ValueError(
                    "Single-label annotations require one class; do not silently collapse multilabel emotions."
                )
        hashes = dict(sample.input_sha256)
        if sample.text is not None:
            hashes["text"] = hashlib.sha256(sample.text.encode()).hexdigest()
        for modality, digest in hashes.items():
            if modality not in sample.modalities:
                raise ValueError("Input fingerprint is inconsistent with available modalities.")
            previous = fingerprints.setdefault((modality, digest), sample.split)
            if previous != sample.split:
                raise ValueError("Exact input-content leakage across dataset splits.")


def load_samples(path, spec):
    samples = read_jsonl(path, Sample)
    validate_dataset(samples, spec)
    return samples


def canonical_digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
