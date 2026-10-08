# Longitudinal sentiment and affect tracking

PamatiAI's `ai/longitudinal/` services describe changes across interactions through replaceable research methods. The supplied `descriptive-personal-trends` method, version `1`, is **experimental**. Its defaults are operational research parameters, not empirically validated psychological thresholds. There is no universal mental-health score, diagnostic classification, crisis detector or automatic risk signal. Negative sentiment does not establish illness or crisis. A prior baseline is descriptive history, not a definition of health.

## Source observations and separation

Eligible sources are completed, non-abstained analysis records belonging to the student, whose submission consent permitted longitudinal tracking. Current active longitudinal consent and current permission for every source modality are also required. Text observations use message creation time; standalone audio/visual and multimodal observations use inference submission time. These are UTC operational timestamps, not synchronized media capture times. Failed, deleted, missing or refused sources contribute no fabricated observation. No microphone or camera is started by tracking.

Supported dimensions:

- Native text `sentiment_polarity`, retained on its declared -1 to +1 scale. Categories are not assigned invented numeric scores.
- Native text/audio affect probabilities, separated by label and exclusive/independent probability semantics.
- Observable visual expression probabilities, kept separate from internal affect. Visual expression is not an internal-state measurement.
- Multimodal probability channels, separated by target, probability semantics and participating modality set. A fused sentiment-label probability remains a probability, not a fabricated polarity. Underlying fusion evidence must remain eligible.

Each series uses one source model-version ID, preprocessing version, adapter version and dimension. Different model versions and pipelines are not pooled into a baseline. A new model starts with insufficient history. Exclusive affect dimensions can be compared together only when the same sources and label ontology apply; separately missing labels are never zero-filled or rescaled into a universal affect distribution. Independent label probabilities are not expected to sum to one. Means are means of model predictions, not measured population prevalence or a person's true emotional state.

Source observations are persisted once per inference/dimension in `sentiment_observations`. Each derived snapshot in `sentiment_trends` links its evidence through `trend_observations`, including prior-window baseline evidence. The existing MySQL guards enforce model, dimension and evidence-window agreement. No schema migration is needed. Snapshots record algorithm identity/version, configuration hash, source model-version ID, preprocessing/adapter versions, observation IDs, consent receipt, generation time, summary window, timestamp basis, counts and missingness. Retain versioned artifacts and deployment dependencies for reproduction. Changing a method requires a new algorithm version; changing source analysis output requires a new inference, not silently rewriting an existing observation.

## Mathematical definitions

All reporting windows are half-open `[start, end)` UTC calendar dates. Baseline evidence extends back `baseline_days` before the visible window. One interaction-day segment consists of all eligible observations for the same session, dimension and UTC day. Sessions spanning several days form several daily segments; periods count unique sessions as specified below.

For scores `x(i,j)` from observation `j` in session/day segment `i`:

```text
interaction mean m_i = (1 / n_i) * S_j x(i,j)
daily mean d_t = (1 / k_t) * S_{i on day t} m_i
weekly mean w = (1 / number of observed days) * S_t d_t
```

This gives each session/day equal weight within a day and each observed day equal weight within a week. A prolific conversation does not outweigh another session just because it contains more messages. Weeks begin Monday. Missing days are excluded from the weekly numerator and denominator, counted explicitly, and never treated as neutral or zero. A week truncated by the requested window is marked partial, independently of missing observations within a full week. An empty day/week has a null mean.

Daily interaction frequency is the number of distinct analyzed sessions with an eligible observation on that day. Weekly frequency is the number of distinct analyzed sessions across the included week. The separate `recorded_session_starts` daily metadata counts visible sessions created in that day under current tracking permission, whether or not they have an eligible analyzed score; it must not be confused with analyzed coverage. Frequency is not a measure of wellbeing, adherence or engagement quality.

The rolling baseline for day `t` uses only observed daily means in `[t - B, t)`, with `B = baseline_days`:

```text
baseline b_t = mean(d_u for observed days u in [t - B, t))
delta ?_t = d_t - b_t
```

The current day and future observations never enter its baseline. Calculate `b_t` only when the lookback contains at least `minimum_baseline_interactions` interaction-day segments AND `minimum_baseline_days` distinct observed days. Default requirements are 8 segments across 4 days within 28 calendar days. Otherwise baseline and delta are null with `insufficient_history`, including when many messages exist on just one day. A baseline can exist on a day with no new estimate, but its delta remains null. Rolling baselines adapt; a long-lasting change can eventually become the reference pattern.

The trajectory is an ordinary least-squares slope over observed daily means in `[t - T + 1, t]`, with `T = trajectory_days` (default 7):

```text
q_u = calendar-day distance from first observed day
slope = S_u (q_u - mean(q)) * (d_u - mean(d)) / S_u (q_u - mean(q))²
```

Require a current-day estimate and at least `minimum_trajectory_days` distinct observed days (default 3). Use actual calendar-day distances through gaps; do not interpolate. The slope has dimension-score units per day and no clinical interpretation.

A descriptive change is `above_baseline` if `?_t = change_threshold`, `below_baseline` if `?_t = -change_threshold`, otherwise no threshold finding. Default threshold is 0.25; it is arbitrary and must be evaluated for each task, model, probability scale and population. Require an available baseline first. A persistent pattern requires at least `persistence_days` consecutive calendar days (default 3) with the same threshold direction. A missing day, insufficient baseline or direction change resets the run. Persistence is calculated across the visible daily window and starts afresh at its first day; prior-window data supports baseline estimation but not an inherited persistence flag.

`returning_toward_baseline` describes local movement, not clinical recovery. It requires available current and prior deltas, a prior threshold-sized difference, and:

```text
|d_t - b_(t-1)| < |d_(t-1) - b_(t-1)|
```

Using the previous day's baseline for both sides prevents baseline drift alone from creating this flag. Missing preceding data suppresses it. Crossing the baseline can qualify if the absolute distance shrinks; this is a descriptive movement finding, not a health outcome.

## Uncertainty

Interaction summaries report sample standard deviation of available source scores; daily summaries report sample standard deviation of interaction means; weekly summaries report sample standard deviation of observed daily means; baselines report sample standard deviation of historical daily means:

```text
s = sqrt(S_i (v_i - mean(v))² / (n - 1)), for n = 2
```

With fewer than two values, spread is unavailable, not zero. These quantities describe observed dispersion, not calibrated confidence intervals, accuracy, or uncertainty about a latent emotional state. Source confidence/uncertainty availability is counted rather than averaged into an invented confidence score. Correlated sources, selection effects and model miscalibration remain. Counts, missing days and history requirements accompany all findings. The interface deliberately labels summaries uncalibrated.

## Configuration and replacement

```dotenv
LONGITUDINAL_ALGORITHM=descriptive-personal-trends
LONGITUDINAL_CONFIGURATION={"baseline_days":28,"minimum_baseline_interactions":8,"minimum_baseline_days":4,"trajectory_days":7,"minimum_trajectory_days":3,"change_threshold":0.25,"persistence_days":3}
```

`{}` uses these defaults. Configuration is validated; history counts and days are bounded, at least two baseline days/interactions are required, and persistence needs at least two days. Docker Compose forwards both settings. The current algorithm/configuration is disclosed in the versioned consent policy; processing after changes requires acknowledging the new disclosure. Registry factories implement `TrackingAlgorithm.summarize`, declare identity/version and return the normalized summary/evidence contract. Replace the descriptive method with empirically evaluated methods without coupling calculations to API or database code. No scientific conclusions are hard-coded.

## API and visualizations

- `POST /api/v1/students/{student_id}/longitudinal` explicitly generates and stores current snapshots. Body `{}` means the last 90 UTC calendar days, including today. Alternatively provide `{"start":"2026-09-01","end":"2026-10-01"}`; end is exclusive. Windows must contain 1–366 days and cannot extend beyond tomorrow UTC. Completed source records can be recomputed; observations are reused without duplication, while snapshots retain generation history.
- `GET /api/v1/students/{student_id}/longitudinal` reads the most recent snapshot per source pipeline/dimension. It performs no generation. Missing tracking permission returns an empty series list. Generating without current tracking consent/disclosure returns 409. Sources from receipts that declined tracking are not retroactively converted when tracking is later enabled.

The bounded generator rejects more than 5,000 candidate sources or 128 experimental series rather than silently truncating evidence. Reads inspect at most the latest 512 stored snapshots; use a fresh bounded generation to refresh the dashboard rather than treat it as a complete archival export. Calculations run on existing bounded summaries under student/source locks, with a final authorization/source/configuration check before commit. Withdrawal or deleted inputs prevents publication. Changed/deleted evidence suppresses the entire stored snapshot on read; regenerate from remaining sources. Stored history is not automatically erased by consent withdrawal; privacy/export/erasure controls remain separate.

Students see daily/weekly charts on `/student/records`. Assigned reviewers use `/reviewer/trends` with the student's record ID. Backend authorization independently requires history permission, an active assignment and current reviewer-access consent for reviewers; administrator status does not grant content access. Reviewers can refresh permitted snapshots. The cookie gateway protects tokens and enforces Origin for mutations. Declining tracking does not disable text conversation.

Charts show estimates, a dashed rolling baseline, gaps, analyzed interaction counts and a readable numerical table. The table provides baseline coverage, descriptive spread and threshold findings without red crisis labels or diagnoses. UTC dates, partial weeks, models and experimental thresholds are explicit. Charts are supplemented by accessible tabular values. No real student data or synthetic examples are silently inserted into a student's view.

## Research limitations and validation

Baseline means are sensitive to outliers, changing context, observation frequency and adaptive drift. Aggregation choices and thresholds affect findings. Same-session observations are dependent. Missingness may reflect consent, device access, disability/accessibility differences, timing, language or technical failure, and cannot establish recovery or disengagement. Sarcasm, code-switching, cultural context, individual expression, microphone noise, accent and domain shift remain source-pipeline limitations. Scientific validation needs task-specific reference measures, consented ethics-approved studies, calibrated uncertainty, sensitivity analyses, held-out evaluation and model-change handling. This implementation does not perform research export or replace institutional approval.

Synthetic tests cover stable patterns, gradual changes, a temporary negative interaction, insufficient history, missing data and movement toward baseline, plus unequal message volume, prior-only baselines and invalid thresholds. API tests check purpose consent, provenance, source deletion, version separation, reviewer authorization and changed configuration. Passing these tests establishes software behavior, not empirical or clinical validity.
