# Empirical evaluation

PamatiAI now provides an offline evaluation framework in `ai/evaluation/`. It does
not contain a real labeled evaluation corpus or claim measured model performance.
When annotations are absent, every model metric is `null` and the report states:

> Not evaluated — labeled dataset required.

Unit-test fixtures are synthetic numerical checks, not empirical evidence. The
manifest and reports explicitly distinguish `empirical_labeled`,
`synthetic_fixture`, and `unlabeled`. Supplying an evidence flag is a researcher
attestation, not independent verification of dataset origin or annotation quality.

## Run an experiment

Use the existing Python environment; the evaluator requires Pydantic, already a
backend dependency. Metric computation uses the Python standard library and never
downloads a model, dataset, or extra package.

From `pamati-ai`:

```powershell
# A reproducible report with no invented measurements:
.\.venv\Scripts\python.exe -m ai.evaluation ai/evaluation/manifest.template.json --output research-reports

# Once an approved real dataset and versioned outputs exist:
.\.venv\Scripts\python.exe -m ai.evaluation private-research/study-manifest.json --output research-reports

# Or actually run an explicitly selected registered text adapter:
.\.venv\Scripts\python.exe -m ai.evaluation private-research/text-study.json --text-model lexicon-baseline --output research-reports
```

For the text inference option, select `text_only` in the manifest and copy the
adapter's actual `model_versions` into that variant. The current lexicon
comparator identifies itself as `lexicon-baseline`, model version `1`, adapter
version `1`. Its vocabulary-based decisions are not calibrated probabilities;
ROC-AUC, Brier score and log loss remain unavailable for those outputs.
Do not provide `predictions_path` when executing a predictor.

Each experiment writes a new directory named by its experiment ID, containing:

- `report.json`: full metrics, applicability reasons, denominators, model versions,
  parameters, dataset/prediction fingerprints, source fingerprints, runtime versions,
  cohort policy, system observations in aggregate, and bootstrap settings.
- `report.md`: a readable comparison, confusion matrices, system evaluation, and
  limitations.
- `metrics.csv`: aggregate classifier results; no sample or participant identifiers.
- `report.sha256`: SHA-256 of the canonical sorted report object (not the pretty
  JSON file's byte hash).

Existing experiment directories cannot be overwritten. Use a new experiment ID
for a new model, annotation release, parameter choice, or test run. Input paths
resolve relative to the manifest. A configured file that is absent or malformed
is a configuration error; it is not silently treated as a successful empty run.

## Dataset and prediction contracts

Use UTF-8 JSONL: one independently identified example per line. Dataset rows follow
`Sample` in `contracts.py`:

| Field | Meaning |
| --- | --- |
| `sample_id` | Private unique evaluation-unit identifier, never printed in reports |
| `group_id` | Private participant/speaker grouping key, required for participant-independent splits |
| `split` | `train`, `validation`, or `test` |
| `labels` | Human/reference label codes; `null` means unannotated; an empty list is a valid no-positive-label example only for multilabel tasks |
| `modalities` | Available `text`, `audio`, and/or `visual` inputs |
| `text`, `audio`, `visual` | Optional private adapter inputs; media fields are references, never report contents |
| `input_sha256` | Optional per-modality input fingerprints for duplicate/leakage detection |

The dataset manifest declares its identifier/version, annotation and label-mapping
versions, target, task, ordered label vocabulary, source/license references,
population scope, evidence kind, split unit, and binary positive label where
applicable. Annotation labels must match the frozen vocabulary. Continuous
sentiment intensities require a separately preregistered classification mapping;
this release does not silently turn regression into classification or evaluate
regression metrics. Preserve original annotations and the mapping artifact in the
restricted study archive.

Prediction rows follow `Prediction`: `sample_id`, `variant`, actual
`input_modalities`, versioned `model_versions`, optional predicted `labels`,
optional `probabilities`, declared `probability_kind`, optional `confidence`, and
`abstained`. Versions must exactly match the manifest, including adapter version,
optional artifact/configuration hashes, and recorded numeric model parameters.
Duplicate outputs, wrong split, unknown labels, mismatched modalities, invalid
probabilities, or changed model provenance fail validation rather than producing
partial-looking results. Names, transcripts, notes, credentials, and arbitrary
configuration dictionaries are not model-metadata fields.

Hard labels are accepted. If only probabilities are supplied, binary decisions use
the declared positive label and threshold; multiclass decisions use maximum
probability with the manifest's label order as deterministic tie-breaking;
multilabel decisions use the declared threshold for each label. A positive minimum
confidence requires a declared confidence value; missing/below-threshold values
are abstentions. Confidence heuristics are never substituted for class probabilities.

`EvaluationPredictor` and `execute_predictors()` provide the interface for actual
audio, visual, and learned fusion inference. Supply reviewed adapters that use
exactly the requested modalities and explicitly map the dataset's label ontology.
The built-in direct-inference bridge currently supports registered text models.
Other model types can be evaluated from actual imported versioned outputs or
reviewed programmatic predictors; this is not a claim that an audio/visual emotion
classifier or universal fusion model has been trained or evaluated. Production
fusion preserves distinct sentiment, modeled-affect, and observed-expression
channels; those channels must not be collapsed into an invented universal score.

## Metrics and interpretation

Classification supports binary/multiclass single-label and multilabel tasks.
Accuracy is exact class match or exact label-set match, respectively. Reports
include per-class precision/recall/F1 and support, macro and support-weighted F1,
macro/weighted precision and recall, and confusion matrices with declared row and
column meanings. Binary headline precision/recall/F1 use the predeclared positive
class; multiclass headlines use macro averaging; multilabel headlines use micro
averaging and also include Hamming loss. Undefined class precision/recall/F1
uses a documented zero-denominator convention of zero. Macro averages include
all preregistered classes, even if a class has no support in that cohort.

Missing predictions and abstentions remain in the eligible sample denominator.
Reports separate coverage, selective accuracy, end-to-end accuracy, missing
outputs, and abstention/confidence rejections. Selective F1 and confusion matrices
use answered samples; a model that refuses difficult cases must not appear superior
without reporting its coverage. No answered outputs means selective metrics are
`null`, not invented perfect scores.

Probability metrics require complete, finite class probabilities for every answered
example, with exactly the declared vocabulary. Exclusive probabilities must sum
to one; multilabel probabilities are independent Bernoulli outputs. Binary ROC-AUC
requires a declared positive label and examples of both classes. Macro one-vs-rest
AUC requires positive and negative examples for every declared label; otherwise
its aggregate is unavailable and per-label reasons are retained. Hard decisions
and unspecified confidence values are not accepted as ranking scores. These
conditions follow the [scikit-learn ROC-AUC definition](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.roc_auc_score.html).

Brier score and clipped log loss are computed for valid probabilistic outputs.
Binary Brier uses positive-label squared error; multiclass Brier is the unscaled
sum of squared class errors; multilabel Brier averages Bernoulli errors across
labels and samples. ECE uses equal-width bins and reports bin counts and observed
frequencies, with predicted-label confidence for single-label tasks and label-wise
Bernoulli calibration for multilabel tasks. Empty bins remain empty. ECE depends on
binning and sample size; Brier/log loss are not pure calibration measures. Fit any
calibrator on separate development/calibration data, never this test set. See
[probability calibration](https://scikit-learn.org/stable/modules/calibration.html).

## Multimodal comparisons and uncertainty

All seven requested variants are represented: text only, audio only, visual only,
text + audio, text + visual, audio + visual, and all available modalities. The last
variant uses the modalities actually present on each example and records their
patterns; it is not silently assumed to mean all three.

`paired_complete` is the default: all selected variants use the same labeled
examples having the required inputs. Prediction availability does not determine
cohort inclusion. With all seven variants selected, complete text/audio/visual
alignment is normally necessary for paired comparisons. A text-only corpus cannot
manufacture audio or video: affected comparisons remain unevaluated.
`per_variant` reports each eligible cohort separately and explicitly marks raw
cross-cohort differences as not paired evidence of a modality improvement.

The first manifest variant is the preregistered reference. Paired comparisons
report end-to-end accuracy and coverage differences on the shared cohort.
Optional seeded participant-cluster percentile bootstraps provide descriptive
95% intervals for accuracy/F1 and paired end-to-end accuracy differences. At least
two independent groups are required. These intervals do not establish causality,
clinical usefulness, or confirmatory significance. Small clusters, selected test
sets, label uncertainty, and multiple comparisons need separate research review.

## System-level evaluation

Provide private `SystemObservation` JSONL via `system_path`. No dimension defaults
to an invented score. Missing dimensions report **Not evaluated — observations
required.** Each observation declares empirical or synthetic provenance and its
rubric version. Incompatible rubric versions, judge sources and latency phases
are summarized separately.

- **Usability:** measured task success/duration and completed 10-item, 1-to-5 SUS
  responses. SUS reverses alternating items, sums adjusted contributions and
  multiplies by 2.5; its 0-to-100 result is not a percentage or health score. Repeated
  respondents require an explicit longitudinal design instead of independent counting.
  The instrument appears in the [US government SUS appendix](https://www.reginfo.gov/public/do/DownloadDocument?objectID=121062001).
- **Conversation quality:** documented human ratings of relevance, coherence,
  empathy, autonomy, and groundedness using anchored 1-to-5 rubrics. Report ordinal
  distributions and descriptive summaries; do not replace counselors with an
  unvalidated automatic judge.
- **Latency:** monotonic measured milliseconds, separately for first token, complete
  response and human review. Report success/failure denominators and separate
  duration distributions, including timeouts. Inference adapters measure actual
  elapsed time; they do not invent timing values.
- **Safety behavior:** independent expected/observed coded behaviors, exact match,
  required-behavior coverage, omissions, and unexpected behaviors. Human-reviewed
  versus rule-based annotations remain distinct. This measures conformity with
  a test rubric, not real-world crisis sensitivity or clinical safety.
- **Human-review agreement:** paired independent nominal decisions from a fixed
  ordered rater pair. Report observed agreement, confusion matrix and unweighted
  Cohen kappa; kappa is unavailable when chance agreement is one. AI–human
  comparisons are explicitly separate from human–human agreement. Agreement is
  not diagnostic truth. See [Cohen kappa documentation](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.cohen_kappa_score.html).

## Identity-protecting research export

The separate trusted worker `app.research_export` exports only explicit research
memberships for a selected dataset/version. It checks current research and modality
permission, original research permission, live source records, ethics/de-identification
provenance, membership revocation, participant-independent splits, and fusion
source availability. Consent locks are held while preparing and writing the local
artifact. This does not give administrators a new student-content API.

From `backend`, with a dedicated worker credential and externally provisioned
`RESEARCH_EXPORT_HMAC_KEY` (hex-encoded random key, at least 32 bytes):

```powershell
..\.venv\Scripts\python.exe -m app.research_export --dataset-spec ../private-research/export-dataset.json --output ../private-research/export-release-1
```

The dataset spec must declare `institutional_consented` and `unlabeled`.
`observations.jsonl` contains dataset-scoped HMAC codes for samples, participants
and sessions, approved model versions, split/modality information, and only the
requested target's coded AI labels/probabilities. `export.json` records aggregate
export counts and provenance. Student IDs/emails/names, raw text/media, precise
student timestamps, storage paths, risk narratives, counselor notes, secrets and
identity mappings are excluded. Cells with fewer than five distinct participants
per split/modality are suppressed; institutions may choose a larger minimum.

This is **pseudonymous restricted research data, not anonymous data**. Codes,
probabilities and rare patterns can still enable linkage. Keep the HMAC key and
identity linkage under separate institutional control. Use restricted storage and
institutional disclosure review; the worker does not publish artifacts. The minimum
cell rule is not a proof of anonymity or differential privacy.

AI observations are never exported as gold labels. Independently annotate and
adjudicate approved evaluation units in a protected workspace, then create validated
`Sample`/`Prediction` JSONL and a versioned manifest. Preserve the export as unlabeled
provenance. Revocation requires removing affected memberships from future releases
and managing already released copies under the approved withdrawal/retention plan.
No default researcher download contains transcripts or raw recordings.

## Reproduction and validation

Archive source revision and actual source hashes, private input hashes, frozen
splits, label mapping, model artifacts/configuration hashes, all selected parameters,
package lockfiles, hardware/runtime details, and calibration/training seeds. The
runner captures its own source hashes plus Python/Pydantic versions. External
training/inference dependencies and nondeterministic accelerator settings remain
the adapter operator's responsibility. Measured latency and run timestamps naturally
vary; deterministic metric recalculation on the same fixed predictions is the
reproducible claim.

Run `python -m pytest tests/backend/test_evaluation.py tests/backend/test_research_export.py`
from `pamati-ai` with `PYTHONPATH=backend;.` on Windows (or use the backend test
configuration). Tests cover known metric values, seven-way cohorts, abstentions,
missing classes/probabilities, leakage, provenance mismatch, invalid records,
seeded uncertainty, report identity minimization, and consent-aware export. Test
results validate software behavior, not model accuracy on a real research corpus.
