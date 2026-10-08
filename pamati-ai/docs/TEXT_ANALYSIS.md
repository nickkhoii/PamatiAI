# Text analysis for research

Text analysis estimates properties of a submitted message. It does not establish a
student's emotional state, diagnose a condition, validate risk, or make a research
conclusion. Analysis does not drive conversation replies, referrals, or safety signals.

## Configuration and integration

`TEXT_ANALYSIS_MODELS` is a JSON list of registered model names. It defaults to `[]`
(disabled). Set `TEXT_ANALYSIS_MODELS=["lexicon-baseline"]` in `.env` and rebuild the
backend to enable the included offline comparator. No model download or external
text transmission occurs in this adapter. Changing enabled models, versions, model
configuration, or confidence thresholds requires a new informed consent receipt.
Policy `2026-10-08.1` adds text-analysis disclosure to onboarding.
Use `TEXT_ANALYSIS_MINIMUM_CONFIDENCE=0.0` for no confidence-based abstention;
a positive value causes missing or lower confidence to abstain. This is an operational
threshold, not a clinically validated cutoff.

For local execution from `backend`, install the project with
`../.venv/Scripts/python.exe -m pip install -e .` so the sibling `ai` package is available,
or set `PYTHONPATH` to the absolute `pamati-ai` directory. Docker includes that path.

`POST /api/v1/conversations/{conversation_id}/messages` reserves one analysis job
per configured model for each new student message. Inference runs synchronously
after reply generation, outside the message reservation transaction. Replayed request
IDs reuse the saved turn and do not create additional analyses. Assistant and system
messages are excluded. A model failure is recorded without failing the reply or the
other models. Consent is checked before execution and again before publication;
withdrawal, changed receipts, and deleted records discard unfinished results.
This synchronous integration adds model latency to message submission. A process
interruption can leave pending/running jobs; a production worker, execution deadlines
and recovery scheduler are not included. Replaying a turn does not restart those jobs.
Adapters should load expensive model artifacts lazily rather than during metadata
resolution for consent disclosure.

`GET /api/v1/conversations/{conversation_id}/messages/{message_id}/analyses`
returns all model runs, including failed/abstained statuses. It uses the same ownership,
reviewer assignment, and reviewer consent checks as conversation history. An admin
role alone does not grant access. Historical results remain subject to existing
retention and deletion workflows; withdrawal alone does not erase history.

## Modules and replacement

`ai/text/preprocessing.py` performs versioned NFC normalization and outer whitespace
removal, preserving emoji, punctuation, negation, case and code switching. It never
silently truncates input; message length remains limited to 4,000 characters.
`interface.py` defines `TextModel`, `ModelMetadata`, and `ModelOutput`.
`registry.py` maps configuration names to model factories. `service.py` orchestrates
preprocessing, prediction and normalization. `normalization.py` validates output
semantics; `confidence.py` validates finite ranges and computes optional entropy.
`backend/app/text_analysis.py` bridges these modules to the existing consent-aware
`run_analysis` boundary.

To add a comparator, implement `metadata` and `predict(TextInput) -> ModelOutput`,
then register a factory in `registry.py`. Configure multiple names to run experiments
on the same message. Map model-specific labels to positive/negative/neutral/mixed
inside the adapter. Pin the actual artifact revision in `metadata.version`, record
non-secret inference parameters in `configuration`, and change the version whenever
weights, vocabulary or model configuration changes. Versions are immutable in the
existing database. Unknown names fail configuration resolution; models are never
silently substituted. External adapters need appropriate disclosure and institutional
approval before deployment; the supplied integration is for server-local models.

## Results and traceability

`model_versions` stores model identity, revision and configuration. `model_inferences`
links the message, student, session, model version and consent receipt, with preprocessing
and adapter revisions, status, UTC creation/start/completion times, confidence,
uncertainty and sanitized error code. `text_analyses` stores normalized JSON labels,
limitations and optional language. The existing schema requires no migration.
Sentiment observations and trends are not automatically created: their separate
longitudinal consent and research-purpose workflows remain necessary.

Result schema version `1` includes `sentiment_polarity` in [-1, 1],
`sentiment_category`, optional sentiment probabilities, optional emotion probabilities,
emotion probability semantics, abstention and `interpretation=research_estimate`.
Unavailable capabilities are null, not invented zeros. Emotion outputs must declare
`exclusive` (sum to one) or `independent` (multiple affects may coexist). Distributions
must already be probabilities; logits and invalid distributions are rejected, not
silently repaired. Confidence requires a declared method and stays null if unsupported.
Sentiment entropy measures distribution spread, not correctness, and is not computed
for independent emotion probabilities. All current confidence is marked uncalibrated.
Abstained runs can retain estimates for inspection; consumers must check status before
using them. Language stays null unless supplied by a supported integration; no language
detector is claimed.

The baseline is a tiny, unvalidated English lexicon. Polarity is the difference between
positive and negative token counts divided by their total; mixed vocabulary produces
the mixed category. Without known tokens it abstains. It supports neither confidence
nor emotion probabilities. It is a plumbing comparator, not a validated NLP model.

## Limitations and experimental evaluation

- Sarcasm, irony and negation can invert literal sentiment; the baseline ignores these.
- Multilingual and code-switched language, dialects and transliteration may be poorly
  represented. English vocabulary hits do not establish understanding of a mixed message.
- Cultural context changes how emotion, politeness and distress are expressed. Labels
  need local interpretation and cannot be presumed universal.
- Domain shift between training corpora and student conversations can change accuracy
  and calibration. Report dataset, population and collection conditions.
- Single-message analysis loses conversation context. Missing evidence is not neutrality,
  and neutral sentiment is not evidence of wellbeing.
- Confidence and entropy can be misleading even when mathematically valid. Evaluate
  calibration, abstention coverage and error rates on held-out, locally relevant data.

Compare pinned models using the same appropriately consented, de-identified evaluation
set, independent annotations, explicit splits, per-language/subgroup error analysis and
documented metrics. Do not select or encode a preferred research conclusion in adapters.
The automated tests validate software contracts and privacy behavior, not empirical
accuracy or clinical utility. Run `python -m pytest` from `backend`; MySQL-specific
checks additionally require a dedicated `TEST_DATABASE_URL` ending in `_test`.
