# Multimodal fusion (experimental)

PamatiAI combines existing derived analyses through `ai/multimodal/`. The default is **experimental late fusion**, not an empirically validated psychological measure. Fusion never records media, starts a camera/microphone, generates a diagnosis, identifies faces, infers protected attributes, or treats visible expression as internal emotion. Text functionality does not depend on fusion, audio or visual permission.

## Strategies and output meaning

- `late-fusion` preserves independent probability channels and all accepted individual outputs, including numeric features and categorical observations. It does not manufacture a universal affect score.
- `weighted-probability` averages only channels with the same target, probability semantics and exact label set. Nonnegative configured weights are normalized over present participants. A missing modality contributes no artificial neutral score. Zero-weight sources remain documented but do not contribute to probability channels. Default equal weights are arbitrary experimental settings, **not scientific validation**.
- Learned plugins implement `FusionStrategy` and register a factory in `registry`. Declare `FusionMetadata`, a new version, model configuration, and a pinned artifact SHA-256. No trained fusion model is supplied. Plugins must accept variable modality sets, return normalized supported channels with explicit source IDs, and disclose any confidence method. Pin training/evaluation dataset versions, split identifiers, preprocessing, seeds, runtime dependencies and calibration artifacts in metadata configuration. These requirements do not establish scientific validity.

Text sentiment is a separate target from modeled text/audio affect. Visual expression is a separate observable-expression target; it cannot contribute to sentiment or internal affect. Matching labels alone do not prove two models measure the same construct: researchers must validate ontology, task and calibration compatibility before choosing weighted fusion. Independent probabilities are not forced to sum to one; exclusive distributions must. Features and categorical outputs are preserved without invented probabilities.

The normalized observation includes available/missing/excluded modalities, complete accepted source summaries, model identifiers/versions/configuration, source consent receipts and message references, preprocessing/adapter versions, fusion strategy/version/configuration, effective weights and contributing IDs per channel, combined channels, timestamp, limitations and abstention. The combined output intentionally has no universal affect score.

## API and consent

`POST /api/v1/sessions/{session_id}/multimodal-analyses`:

```json
{"source_inference_ids": ["UUID-of-text-inference", "UUID-of-optional-audio-inference"]}
```

Supply one to three distinct analysis IDs, at most one per modality. Sources must belong to the authenticated student's same active session. Select IDs from the conversation/text, audio or visual analysis responses. Sources are explicitly selected; the server does not silently join the latest records from unrelated turns. `GET /api/v1/multimodal-analyses/{analysis_id}` uses existing protected history access controls.

A current active consent receipt acknowledging the configured fusion disclosure is required. Each source modality must currently be permitted; unconsented content is never loaded or passed to a strategy. Historical sources retain their original receipt IDs, while the new fusion job references the current receipt. Failed, pending, cancelled, abstained, deleted, absent, invalid or out-of-window sources are excluded. Unknown IDs count as unavailable. Foreign-session/student sources are rejected. If none remain usable, the API returns 409 without creating a job; the standalone service produces an empty abstained observation. Refusal or failure is not evidence about wellbeing.

Consent, source existence/status, linked-message availability, active session and processor configuration are checked again before atomic publication. Changed sources or withdrawn consent discard the combined result. Strategies failing during execution produce a failed job without analysis or evidence links. Optional modalities are never retried or required by fusion.

## Configuration

```dotenv
MULTIMODAL_FUSION_ENABLED=true
MULTIMODAL_FUSION_STRATEGY=late-fusion
MULTIMODAL_FUSION_WEIGHTS={"text":1.0,"audio":1.0,"visual":1.0}
MULTIMODAL_FUSION_MINIMUM_CONFIDENCE=0.0
MULTIMODAL_FUSION_MAXIMUM_SOURCE_SPAN_SECONDS=300.0
```

These settings are forwarded by Docker Compose. Setting enabled to false disables the fusion endpoint's processing; text support remains independent. Fusion is explicit through the API, never automatically invoked by conversation submission. Audio and visual pipelines remain independently disabled by default.

The alignment window (0–3600 seconds) excludes sources older than the newest selected source's processing completion timestamp. This is a conservative operational filter, **not capture synchronization**. Asynchronous processing delays can distort alignment; same-session sources can still refer to different utterances. Research protocols must document capture times and turn pairing externally rather than claim simultaneous evidence.

## Persistence and reproduction

Reuse existing `model_inferences`, `multimodal_analyses`, `model_versions` and `fusion_inputs` tables; no new migration is needed. A SHA-256 of canonical disclosed strategy/schema/configuration JSON identifies the fusion model version, distinguishing different weight settings. The human strategy revision and pinned learned artifact remain in configuration. The inference manifest contains only accepted inputs. The normalized observation and provenance edges are published in one transaction. Preserve source records, disclosure snapshot, stored configuration and plugin artifacts for reproduction; the fingerprint cannot recreate unavailable artifacts or recover deleted data. Existing deletion/export/retention workflows apply to the derived record. Fusion stores no additional raw images, video or audio. Research consent remains separate from processing consent; this endpoint does not export research data or authorize a study.

## Uncertainty and limitations

Exclusive channels report normalized probability entropy. Entropy measures distribution spread, not probability of correctness, clinical certainty or a calibrated confidence interval. Independent channels report unavailable entropy. Built-in strategies return no scalar confidence; they do not average source confidence or assume independence. A positive minimum-confidence threshold makes these strategies abstain. Learned confidence requires a declared method, remains labeled uncalibrated, and needs independent calibration assessment.

Additional modalities can have correlated errors. Disagreement may reflect different constructs, timing, noisy measurements or context; agreement does not establish truth. Missingness is potentially informative and unequal across disability, accessibility, language, consent, hardware and connectivity groups. Results conditioned on availability may be biased. Evaluate missing-modality subsets, failed inputs, calibration, ablations, demographic/accessibility fairness through appropriately approved methods, domain shift and prospective task performance. Do not infer protected attributes to create those evaluations from facial media. Language/code-switching, sarcasm, cultural context, accent, recording quality and individual expression differences remain limitations inherited from each pipeline. Visible facial behavior cannot directly establish a person's internal mental state.

Tests cover modality combinations, missing/refused/failed inputs, weight normalization, incompatible semantics, alignment, persistence/provenance and consent/source/configuration changes during execution. Tests establish software behavior, not scientific validity.
