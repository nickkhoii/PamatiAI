# Optional visual expression research architecture

Visual processing is completely optional and disabled by default. PamatiAI does not
activate a camera, identify students through face recognition, infer protected attributes,
diagnose psychiatric conditions or claim that facial movement directly reveals a person's
internal mental state. Visual estimates do not drive replies, referrals, risk signals,
eligibility decisions or student ranking. Text support remains available when visual
processing is refused, including after unrelated visual adapter/sampling changes.

## Scope and conservative default

The implementation supports bounded, uncompressed 24-bit BMP images and timestamped
BMP frame sequences. Standard BMP bottom-up and top-down row order and row padding are
decoded without additional dependencies. JPEG, PNG, animated images, compressed BMP,
video containers, remote URLs and client filesystem paths are intentionally unsupported
in this first decoder. A future video decoder must enforce duration, resolution, memory
and frame limits before exposing sampled frames; video codec processes are not included.
The current sequence path lets a reviewed upstream decoder supply bounded video frames
without tying feature extraction or expression models to a video codec. Uploaded timing
is declared by the uploader and is not independently verified.

The default `no-expression` extractor/model pair returns technical whole-frame luminance,
contrast and extreme-luminance summaries and abstains from expression inference. It does
not detect faces, establish the number of people present, or fabricate affect probabilities.
This baseline verifies pipeline behavior; it is not a scientifically validated affect model.
No trained expression model or weights are bundled or downloaded automatically.

## Consent and deployment configuration

Both server opt-in (`VISUAL_ANALYSIS_ENABLED=true`) and explicit current
`visual_processing=true` consent are required. Text or audio permission cannot authorize
visual processing. Policy `2026-10-08.3` discloses the current visual model, extractor,
versions, processing location, limits, sampling and confidence settings. An enabled visual
workflow requires a current acknowledged matching disclosure before any upload is read.
Changing the visual pipeline requires a new informed receipt for future visual analysis;
it does not require a visual opt-in from a student who has declined that modality.

The backend checks student ownership and consent before reading the request stream,
again before parsing a received envelope, before file creation/decoding/extraction and
before results are published. Processing uses the existing `run_analysis` boundary;
withdrawal or a replacement receipt cancels unfinished jobs and discards results.
Closed/deleted sessions, deleted conversations and changed processors also prevent
publication. Locks are released during receiving/model work so withdrawal can proceed.
Already completed computation cannot be undone; historical summaries remain governed
by the existing analysis retention and erasure workflows.

| Setting | Default | Meaning |
| --- | --- | --- |
| `VISUAL_ANALYSIS_ENABLED` | `false` | Explicit deployment opt-in |
| `VISUAL_FEATURE_EXTRACTOR` | `no-expression` | Registered observable-feature extractor |
| `VISUAL_ANALYSIS_MODEL` | `no-expression` | Registered expression model |
| `VISUAL_ANALYSIS_MINIMUM_CONFIDENCE` | `0.0` | Operational confidence abstention cutoff |
| `VISUAL_MAX_BYTES` | `3000000` | Maximum upload and decoded frame bytes |
| `VISUAL_MAX_PIXELS` | `262144` | Maximum pixels per frame; each side is also limited to 1024 |
| `VISUAL_MAX_INPUT_FRAMES` | `32` | Maximum submitted frames |
| `VISUAL_SAMPLE_COUNT` | `8` | Maximum frames decoded and presented to the extractor |
| `VISUAL_MAX_SECONDS` | `30.0` | Maximum uploader-declared timestamp |
| `VISUAL_TEMPORARY_DIRECTORY` | system temporary directory | Private temporary frame root |

Limits may be lowered but cannot exceed the built-in caps. Docker uses `/tmp/pamati-visual`
with private permissions, not a persistent raw-media volume. Set configuration in `.env`
and rebuild the backend after registering adapters. The included path requires no optional
ML dependencies; local execution uses the README's `PYTHONPATH` setup.

## API and sampling

`POST /api/v1/sessions/{session_id}/visual-analyses` requires bearer authentication and
an active student-owned session in an open conversation. Conversation messages/history
provide `session_id`. The endpoint never fabricates a text message or transcript.

Supply either a single BMP as the entire body with `Content-Type: image/bmp`
(`image/x-ms-bmp` also accepted), or `application/json` containing only this envelope:

```json
{
  "frames": [
    {"bmp_base64": "BASE64_ENCODED_BMP_BYTES", "timestamp_seconds": 0.0},
    {"bmp_base64": "BASE64_ENCODED_BMP_BYTES", "timestamp_seconds": 0.5}
  ]
}
```

JSON overhead/base64 expansion counts toward the upload-size limit. Unknown fields,
paths, filenames, identity fields and malformed base64 are rejected. Frame timestamps
must be finite, nonnegative, strictly increasing and within the duration cap. All submitted
frames are checked for complete, bounded BMP structure before sampling; invalid unsampled
frames are not silently accepted. `uniform-frame-index-v1` deterministically selects
uniformly spaced frame indices, retaining first/last frames when sampling more than one.
It samples indices rather than uniform elapsed time. Sparse or irregular timing can miss
short movements; stored indices/timestamps and the timing-source flag document coverage.

Accepted jobs return HTTP 201 with their inference ID and terminal status. Clients must
inspect `status`: the included baseline is `abstained`; malformed images or model failures
produce `failed` and a sanitized `adapter_failed` code, without derived expression results.
Consent changes during processing yield no published result. Pre-upload denial returns
409; unsupported media type 415; excessive streamed bytes 413; empty or invalid JSON
envelopes 422. Inference is synchronous in a thread pool, so optional model latency affects
response time. Upload retries create separate runs; no idempotency key is implemented.

`GET /api/v1/visual-analyses/{inference_id}` uses normal history permissions, student
ownership, reviewer assignment and reviewer-access consent. Administrator status alone
does not grant access. There is no raw image/video download endpoint.

## Interfaces, output contracts and provenance

`ai/visual/validation.py`, `sampling.py` and `files.py` handle bounded input, selection
and server-generated private temporary files. Temporary directories are removed on normal
completion, invalid decoding, extractor/model errors and normalization failure. Only sampled
frames are written. Client paths never reach file creation; no archive extraction, subprocess
codec or identity tracking is performed. Abrupt termination may leave temporary directories;
deployments still need process-level limits and startup/periodic stale-temp cleanup.
On Windows, provision private directory ACLs; POSIX temporary files use restrictive modes.

`interface.py` defines separate `VisualFeatureExtractor` and `VisualModel` protocols,
versioned `VisualMetadata`, `ObservableFeatures` and `VisualModelOutput`. Register factories
in `registry.py` and choose them through configuration. Extractors receive bounded decoded
RGB frames. Models receive only the extractor's observable summary, with no identity
embeddings, raw landmarks, student profile, protected attributes or previous identities
in the interface. Model metadata resolution should not load heavy weights; load lazily.
Adapters are trusted code, not sandboxed: schema enforcement alone cannot prevent an
arbitrary plugin from performing prohibited computation. Review actual adapter behavior,
training objective, weights, licensing and data handling before registration.

Approved extractors may emit action-unit intensity summaries from the declared AU
vocabulary on a 0–5 estimated-intensity scale or explicitly mapped 0–1 observable
measurements (`mouth_openness`, `brow_raise`, `lip_corner_raise`, `eye_closure`). These
scales are contracts, not validated norms; document how each adapter maps its output.
Unsupported features stay null rather than invented zeros. Anonymous technical quality
measurements do not establish face/expression visibility or scientific measurement quality.

Models may provide probabilities for observed expression classes: `smiling`, `frowning`,
`brow_raised`, `mouth_open`, `eyes_closed`, `no_clear_expression`. These labels describe
estimated configurations; they are not happiness, distress, intent, psychiatric diagnosis
or a person's internal emotion. Identity, embeddings, protected-attribute and diagnostic
feature keys and internal-state output labels are rejected before persistence. Forbidden
feature keys are rejected before model prediction. Adding a scientifically justified
observable label requires a reviewed schema/version change, not arbitrary JSON expansion.

`confidence.py` and `normalization.py` validate finite ranges and probability semantics.
`exclusive` distributions must sum to one; `independent` probabilities may coexist.
Confidence is optional and requires a method; exclusive-distribution entropy describes
spread over expression classes, not correctness or internal-state uncertainty. Confidence
is explicitly uncalibrated; missing confidence stays null. A positive configured cutoff
abstains when confidence is absent/below threshold. Consumers must honor abstention.
No model output is hard-coded as a research conclusion.

`service.py` orchestrates validation, sampling, temporary handling, quality summaries,
extraction and prediction. `backend/app/visual_analysis.py` bridges to the existing
`model_versions`, `model_inferences` and `visual_analyses` tables; no migration is needed.
Records link student/session, inference, model identity/version, extractor/version,
validation/schema versions, consent receipt, UTC creation/start/completion times,
sampled-frame count, uncertainty and limitations. Sampling version, indices, relative
timestamps and timing provenance are saved in normalized JSON. Model configuration
captures extractor/version and configuration; changing it requires a new model version.

## Storage minimization

This visual implementation never retains raw images/video or creates `media_assets`,
even if generic raw-media storage is enabled and a receipt permits `retain_visual`.
Only bounded observation/quality summaries and provenance are persisted. Raw pixels,
biometric templates, face embeddings, landmark arrays and student-identification results
are excluded from the analysis schema. Derived summaries remain sensitive and potentially
linkable to a student; they are not automatically anonymous. Separate research consent,
ethics approval and de-identification remain necessary for approved dataset workflows.
The pipeline does not automatically generate datasets, longitudinal trends or alerts.

## Substantial scientific limitations

Facial movement is observable; its psychological interpretation requires context. A major
review describes variation across situations, cultures and individuals, and notes that
similar movements can accompany different emotions or serve other communicative purposes.
A classifier's chosen label therefore cannot establish the underlying mental state.
See [Barrett et al. (2019), Emotional Expressions Reconsidered](https://pubmed.ncbi.nlm.nih.gov/31313636/).

Culture-sensitive perception is also documented experimentally. A study of reconstructed
facial-expression representations found differences between its Western and East Asian
samples. That result supports evaluating local populations rather than assuming universal
label mappings; it does not establish uniform differences for every member of a culture.
See [Jack et al. (2012)](https://pubmed.ncbi.nlm.nih.gov/22509011/). The interpretation of
cross-cultural commonalities is debated, as illustrated by [Sauter and Eisner's response](https://pubmed.ncbi.nlm.nih.gov/23300281/).

The following are limitations to investigate, not conclusions about any participant:

- **Context and ambiguity:** smiling can be communicative or posed; a single sampled
  image does not identify its cause. A lack of classified movement is not emotional
  neutrality, wellbeing, disengagement or evidence that something is wrong.
- **Annotation validity:** agreement with annotators or a dataset label is agreement
  about the annotation task, not verification of a participant's subjective experience.
  Forced-choice expression categories can constrain what an experiment can measure.
- **Domain shift:** posed laboratory images may not represent spontaneous, occluded,
  low-resolution student interactions. Local recording conditions and population should
  be assessed separately before using an adapter in research.
- **Imaging conditions:** camera position, exposure, lighting, blur, occlusion, compression,
  masks and glasses may change measured appearance or hide facial movements. Global
  luminance/contrast is only a technical proxy and does not certify facial visibility.
- **Temporal limitations:** sparse frame sampling can miss or misrepresent movement.
  Uploader-declared times are not verified video timing. A sequence summary cannot establish
  the duration/cause of a subjective emotion or person-specific behavioral baseline.
- **Individual and cultural differences:** expression habits and social display conventions
  vary. Do not interpret a student's difference from a training-set pattern as abnormality.
  Never infer a student's protected characteristics to route a model or explain an output.
- **Disability and accessibility:** facial palsy, motor differences, atypical expression,
  neurodivergence, fatigue and assistive communication can make standard expression tasks
  inaccessible or unrepresentative. These must not be classified as psychiatric illness.
  Provide equal text/human-support alternatives, and involve relevant users in consent,
  accessibility and evaluation design. Refusal must have no penalty or loss of text support.
- **Confidence:** a high softmax score or low entropy can reflect an incorrect or unfamiliar
  input. Neither establishes truth, and neither justifies psychiatric or administrative action.
- **Identity and bystanders:** image consent from the account owner does not establish consent
  from others appearing in a frame. Do not identify people to resolve this uncertainty.
  Approved capture workflows must avoid bystanders; adapters should abstain on ambiguous,
  absent or multiple-face input according to a documented, non-identifying eligibility check.

Any study must define its observable construct and hypothesis in advance, document model
and feature versions, use appropriately consented data, evaluate measurement validity and
calibration on independent locally relevant annotations, report abstention coverage/errors,
and distinguish observable-expression labels from subjective self-report. Never treat those
two targets as interchangeable or choose software thresholds to encode a preferred finding.

## Tests

Run `python -m pytest` from `backend`. Visual tests cover known BMP pixels/orientation,
size/dimension/encoding/timestamp bounds, deterministic sampling, cleanup on failures,
output normalization and rejection of prohibited labels. Backend tests verify absent,
declined, withdrawn, superseded and outdated visual permission prevents media processing;
denied requests never consume the upload body; revocation during model work discards results;
reviewer/ownership controls protect derived records; raw media is never retained; and
refusing visual processing leaves text and onboarding/chat functionality available.
These tests verify contracts and privacy behavior, not scientific validity or clinical utility.
MySQL-specific checks additionally require an isolated `TEST_DATABASE_URL` ending in `_test`.
