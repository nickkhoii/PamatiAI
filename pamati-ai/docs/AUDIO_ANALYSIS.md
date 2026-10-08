# Optional audio analysis

Audio analysis extracts research measurements from an explicitly uploaded recording.
It never diagnoses psychiatric conditions, identifies a speaker, or triggers a referral,
risk signal or conversational response. No microphone is activated by this implementation.
Students can continue using text without providing audio.

## Consent and configuration

Audio analysis defaults to disabled (`AUDIO_ANALYSIS_ENABLED=false`). Enable it only
for an institutionally approved workflow. The current processor, pinned model version,
feature/validation versions, thresholds, limits and raw-storage setting are disclosed
in policy `2026-10-08.2`. Audio uploads require a current acknowledged disclosure and
explicit `audio_processing=true`. Text consent alone is insufficient. Configuration
changes require a new informed receipt before further uploads.

The backend checks authorization and audio consent before consuming the upload body,
again after receiving it, before decoding/feature extraction, and before saving results.
Locks are released during upload/model execution so consent can be withdrawn.
Withdrawal or a newer receipt cancels unfinished jobs and discards their results.
Disabled processing, closed/deleted sessions, deleted conversations and changed processor
configuration block publication. Processing completed before withdrawal cannot be undone.
Historical derived records follow the existing analysis retention and erasure workflows.

| Setting | Default | Purpose |
| --- | --- | --- |
| `AUDIO_ANALYSIS_ENABLED` | `false` | Explicit audio-processing deployment opt-in |
| `AUDIO_ANALYSIS_MODEL` | `acoustic-features` | Registered local model factory |
| `AUDIO_ANALYSIS_MINIMUM_CONFIDENCE` | `0.0` | Operational model-confidence abstention cutoff |
| `AUDIO_MAX_BYTES` | `3000000` | Bounded request size; can only be lowered |
| `AUDIO_MAX_SECONDS` | `30.0` | Bounded recording duration; can only be lowered |
| `AUDIO_TEMPORARY_DIRECTORY` | system temporary directory | Private temporary WAV files |
| `AUDIO_STORAGE_DIRECTORY` | `../private-audio` | Private raw-recording store, when permitted |
| `ALLOW_RAW_MEDIA_STORAGE` | `false` | Existing separate raw-storage deployment gate |

Docker uses private container paths and the `audio_recordings` volume. Rebuild the
backend after adding adapters; the base implementation needs no additional dependencies
or model downloads. For local use, follow the README's `PYTHONPATH` setup.

## API

`POST /api/v1/sessions/{session_id}/audio-analyses` accepts the WAV bytes as the entire
request body with `Content-Type: audio/wav` (also `audio/x-wav` or `audio/wave`) and
the normal bearer authorization header. It does not accept client file paths or names,
multipart form uploads, compressed audio, URLs, archives, stereo, or raw PCM.
The session must belong to the submitting student and be active in an open conversation.
Use the `session_id` returned with conversation messages/history; this endpoint does
not create sessions. The upload is associated with that session, without fabricating
a text message or transcript.

```shell
curl -X POST "$API/api/v1/sessions/$SESSION_ID/audio-analyses" \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H "Content-Type: audio/wav" \
  --data-binary @sample.wav
```

An accepted job returns HTTP 201 with its inference ID and terminal `status`.
Clients must inspect status: malformed WAV or adapter errors produce a saved `failed`
run with `error_code=adapter_failed` and no analysis payload. Consent changes during
inference produce no analysis payload. Pre-upload consent denial returns 409, wrong
content type 415, oversized streamed bodies 413, and empty bodies 422.
The implementation uses synchronous analysis in a thread pool; model latency affects
response time. HTTP retries create independent runs; there is no upload idempotency key.

`GET /api/v1/audio-analyses/{inference_id}` retrieves derived results. Existing ownership,
reviewer assignment and reviewer-consent checks protect access; administrator status
alone does not permit reading. No raw-recording download endpoint is exposed.

## Architecture and research measurements

`ai/audio/validation.py` checks WAV signatures/container lengths, uncompressed mono
16-bit PCM, 8–48 kHz sample rate, nonzero frames, complete payload and duration limits
(at least 40 ms). Decoding uses Python's WAV parser, with no shell commands or external
codec processes. `files.py` creates server-named private temporary files and removes
them on successful completion, validation error or model failure. Recording-store keys
are generated opaque UUID names; traversal and symlink references are rejected, and
exclusive creation prevents overwriting existing recordings.

`features.py` emits `acoustic-summary-v1` summaries with explicit units and methods:

- Pause characteristics: counts and duration summaries for energy-gated quiet runs of
  at least 200 ms, including leading/trailing silence, plus quiet-time fraction.
- Pitch statistics: mean, population standard deviation, minimum and maximum in Hz
  from periodic frames, with the fraction of all frames yielding a pitch estimate.
- Energy statistics: frame RMS amplitude converted to dBFS, with a -120 dBFS floor.
- Prosodic summaries: pitch and energy variability plus acoustically active duration.
- Quality indicators: clipped-sample fraction. SNR and actual speech detection remain
  unavailable; no environmental quality score is fabricated.
- Speech rate: null by default. An optional adapter may supply a validated nonnegative
  word count and versioned timing method; words per minute then uses the entire recording
  duration, including pauses. Energy-active time is never claimed to be speech rate.

The comparator uses nonoverlapping 40 ms frames, a fixed -40 dBFS quiet gate, and
decimated autocorrelation with an 80–400 Hz search range and 0.6 correlation gate.
These are reproducible algorithm parameters, not validated population norms or clinical
cutoffs. Decimation has no anti-alias filter in this baseline; pitch can have aliasing
and octave errors, and voices outside the search range can be missed. Background tones
can also produce pitch estimates. Silence produces valid acoustic summaries with null
pitch and no invented emotion output.

`interface.py` defines `AudioModel`, `AudioModelMetadata` and `AudioModelOutput`.
`registry.py` supplies the default features-only comparator and supports registered
replacement factories. An adapter implements `predict(AudioInput, features)` and declares
its identifier, actual artifact revision, adapter revision and non-secret configuration.
It receives bounded decoded samples, never an arbitrary user path. Load weights lazily
so consent disclosures can resolve metadata without loading a model. The supplied
workflow is server-local; external processors need adapted disclosures before use.

`service.py` orchestrates safe temporary handling, decoding, extraction, model inference
and `normalization.py`. Map model affect labels to the supported emotion vocabulary in
the adapter; psychiatric labels are rejected. Optional probabilities must declare
`exclusive` (sum to one) or `independent` (coexisting affect outputs). Invalid, nonfinite
or out-of-range values are rejected. Confidence is optional and requires a method.
Exclusive-distribution entropy reports probability spread, not correctness. All current
confidence is explicitly uncalibrated; unavailable confidence/uncertainty stays null.
The configured confidence cutoff can abstain without asserting a research conclusion.
Consumers must honor failed/cancelled/abstained statuses when interpreting outputs.

## Persistence, minimization and raw retention

`backend/app/audio_analysis.py` bridges the pipeline to `run_analysis`, using the existing
`model_versions`, `model_inferences` and `audio_analyses` tables. No migration is needed.
Each inference records student/session, consent receipt, validation and adapter versions,
model identity/revision, confidence, uncertainty and UTC creation/start/completion times.
Model configuration records the feature version and extraction parameters; normalized
JSON labels contain derived feature summaries, optional affect output and limitations.
The API exposes consent permissions at submission, receipt/policy version and withdrawal
timestamp. A historical consent snapshot does not authorize a new processing run.
No waveform, transcript, filename, frame-level signal or psychiatric diagnosis is stored
inside analysis JSON. Model/feature changes require new versioned provenance.

Derived features remain usable after the waveform is deleted. Optional research export,
longitudinal aggregation and ethics approval requirements remain separate; this pipeline
does not automatically create datasets, sentiment observations, trends or safety signals.
Derived voice features are still sensitive data, not automatically anonymous.

Raw retention requires all three existing gates: `ALLOW_RAW_MEDIA_STORAGE=true`, the
`raw_media_retention` database setting with `enabled=true`, and the latest consent with
both `audio_processing=true` and `retain_audio=true`. If any gate is closed, only derived
features are retained and temporary files are removed. Successfully analyzed recordings
can be stored under opaque references in `media_assets` with a bounded expiry selected
from the existing raw-media retention policy (24 hours by default). Failed/cancelled runs
never retain recordings. If a raw-storage write/commit fails, its newly created file is
removed; already saved derived analysis does not depend on that file.

Schedule `python -m app.audio_analysis` regularly and after consent changes to physically
purge expired, revoked or deleted recordings from the configured store. In Docker, run
`docker compose exec backend python -m app.audio_analysis`. Purging also honors a lowered
raw-retention cap and marks `purged_at` only after deletion succeeds. Withdrawal schedules
expiry through the existing consent service; it does not synchronously invoke this worker.
The deployment must schedule this command before enabling raw retention. POSIX files use
restrictive modes; on Windows provision appropriate directory ACLs. Storage encryption,
backup lifecycle and access control remain deployment responsibilities. The raw store is
outside public/static paths and excluded from version control.

Normal exits clean temporary files automatically. Abrupt process termination or a host
crash can leave temporary directories or a raw file written before its database commit;
deployment-level temporary/orphan cleanup and bounded worker execution are still needed.
The bounded WAV format reduces work but is not a hard wall-clock deadline for optional
models. No automatic retry/recovery scheduler is included for interrupted analysis jobs.

## Limitations and accessibility

- Microphone quality, automatic gain control, compression, distance and positioning
  affect amplitude and pitch estimates. dBFS describes the digital signal, not sound
  pressure or a person's emotional intensity.
- Background noise, music and other speakers can corrupt quiet/pause detection and
  produce false periodic pitch. The baseline does not isolate speakers or estimate SNR.
- Accent, dialect, language and code switching affect pronunciation, speaking rhythms
  and optional recognizer performance. Evaluate adapters on the relevant local languages.
- Individual speaking differences, age, habitual expressiveness, fatigue and recording
  context can dominate feature variation. Do not rank wellbeing using a universal norm.
- Disability/accessibility considerations include stuttering, dysarthria, atypical
  phonation, respiratory differences, assistive speech devices and inability or preference
  not to speak. These differences must not be labeled as psychiatric illness or penalized.
  Keep audio optional, offer text/human-support alternatives, and include relevant users
  in consent, usability and evaluation work.
- Acoustic emotion outputs are model estimates affected by culture, training-data domain
  shift and annotation disagreement. They do not establish a participant's internal state.
  Report calibration, coverage, per-language/subgroup errors and recording conditions on
  independently annotated, appropriately consented evaluation data.

## Tests

From `backend`, run `python -m pytest`. The audio suite checks known-tone measurements,
silence, format/size/duration rejection, normalized output contracts, temporary cleanup,
path safety, three-gate raw retention, physical erasure and API access restrictions.
It proves missing/declined/withdrawn/superseded audio consent blocks the inference service
and temporary-file creation, with a route-level assertion that denied uploads do not
consume the request stream. Revocation during inference discards derived results and raw
retention. Optional MySQL checks require an isolated `TEST_DATABASE_URL` ending in `_test`.
These tests validate implementation contracts, not scientific validity or diagnostic utility.
