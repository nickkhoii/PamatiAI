# PamatiAI doctoral research protocol

## Protocol status and scope

This document is an implementable protocol template, not a record of ethical
approval, enrollment, completed experiments, validated models, or clinical efficacy.
The researcher and institution must register an approved protocol version, primary
questions, analysis plan, recruitment/sampling procedures, governance, and retention
plan before collecting participant data or examining held-out outcomes.

PamatiAI studies consented conversational support and sentiment/affect observations
in higher education. It does not diagnose, prescribe treatment, establish a
psychiatric risk score, or replace professional or emergency care. An experiment's
label taxonomy describes its annotation construct, not the participant's clinical
condition. Observable expression, communicated emotion, self-report, sentiment,
and a counselor's contextual assessment are distinct constructs.

There is no real labeled evaluation dataset supplied with this implementation.
Until an approved labeled dataset exists, the required model-evaluation status is:

> Not evaluated — labeled dataset required.

Unit tests and synthetic fixtures are software checks. They must not be reported as
empirical doctoral findings. Public benchmark evaluation, local institutional
validation, controlled usability studies, and clinical effectiveness are distinct
stages; success at an earlier stage does not establish success at a later one.

## Research questions and preregistration

Select primary outcomes before unblinding the test split. Candidate questions are:

1. How accurately do specified model versions classify the declared sentiment or
   communicated-emotion labels on independent held-out examples?
2. On the same aligned examples and label ontology, do specified modality variants
   change end-to-end classification accuracy and coverage relative to a
   preregistered reference?
3. How do probabilistic outputs behave with respect to discrimination and
   calibration on a held-out target population?
4. Can students complete consent, privacy, support-request and conversation tasks,
   including participants using assistive technology?
5. How do independent raters judge conversation quality and safety-behavior
   conformity, and how consistently do counselors review contextual signals?
6. What measured latency and failure patterns occur under declared device,
   concurrency, model, network, and institutional-review conditions?

Specify the confirmatory versus exploratory status of every question, model,
comparison, subgroup and metric. The first selected experiment variant is the
framework's reference. Prespecify a primary outcome and practical-effect threshold;
do not manufacture a favorable hypothesis after viewing test results. Record
sampling/power justification with an appropriate statistician using plausible pilot
variance and participant clustering. This template invents no target sample size,
expected effect, accuracy, significance result, or completion date.

## Dataset selection and construct validity

The researcher must obtain data from an authorized source and verify its actual
license, release/version, permitted uses, annotation process and split definitions.
The evaluator does not automatically fetch datasets. Potential benchmark families
include the following; they are candidates, not datasets already evaluated here:

| Candidate | Appropriate use and limits |
| --- | --- |
| [GoEmotions](https://aclanthology.org/2020.acl-main.372/) | Text with fine-grained human emotion annotations. Its 27 emotion categories plus neutral require explicit multilabel handling and a versioned mapping to the study's taxonomy. Reddit language is not a validation sample of Filipino university students. |
| [IEMOCAP](https://sail.usc.edu/iemocap/) | Acted multimodal, multispeaker emotional interactions. Inspect the official access terms, annotations and speaker/session splits. Acted expression and communicated emotion do not establish a participant's internal condition. |
| [CMU-MOSEI](https://multicomp.cs.cmu.edu/resources/cmu-mosei-dataset/) | Aligned multimodal opinion sentiment/emotion data for declared text/audio/visual experiments. Preserve release-specific segment alignment and original annotations; any intensity-to-class conversion must be preregistered. |

For a visual-expression study, use labels of observable expression compatible with
the adapter's output, or explicitly review and justify a distinct benchmark
emotion construct. Do not map a smile to happiness or infer internal distress from
facial geometry. Production PamatiAI's visual channel is observable expression;
its fusion channels do not define a universal emotion score. A visual-only or
universal-emotion experiment can remain unevaluated when no semantically compatible
model/annotation pair exists.

For local validation, recruit through approved institutional procedures and separate
research participation from access to support, academic standing, and treatment.
Document languages and code switching, cultural context, disability/accessibility,
recording conditions, and population coverage without assuming benchmark
performance transfers. Collect only approved characteristics needed to examine
prespecified performance differences; do not derive protected characteristics from
faces, voices, or model outputs.

## Annotation and reference outcomes

Define an annotation manual with the unit of analysis, allowable labels, ambiguity
handling, multilabel rules, unavailable/uncertain judgments, and adjudication.
Train annotators on development material. Keep evaluation labels independent from
AI predictions and, where feasible, blind annotators to model and modality variant.
Use independent initial ratings and retain pre-adjudication judgments so agreement
is not artificially inflated by reporting consensus as independence.

Labels may describe communicated sentiment/emotion or observable expression;
self-reports and clinician judgments should remain separately identified sources.
Never use generated model labels, safety triggers, lexicon scores, or unreviewed
case notes as ground truth. If a task requires clinical outcomes, it needs a
separate approved clinical design and qualified assessment beyond this framework.

Version annotation releases, mapping artifacts and the training manual. Freeze
the ordered vocabulary, binary positive label, multilabel thresholds, exclusion
rules and ambiguity treatment before evaluating the test split. Changing a mapping
requires a new dataset/annotation version and experiment ID. Preserve the original
annotations privately; expose no participant names or excerpts in experiment reports.

## Splits, leakage and model development

Use participant/speaker-independent train, development/calibration and test splits
when repeated measures exist. Split all sessions from a participant together and
preserve the same split across modalities. Keep semantically related segments,
shared source recordings and duplicates together. The framework rejects duplicate
sample IDs, group membership across splits and exact provided input fingerprints
across splits; it does not prove the absence of paraphrase leakage or pretraining
contamination. Inspect these risks separately.

Record all training, preprocessing and augmentation decisions; pin actual model,
adapter, artifact and configuration versions. Preserve model-specific preprocessing
and do not fit vocabulary, feature normalization, calibrators or thresholds on test
examples. Hyperparameters, early stopping and calibration belong to training or
validation data. External adapters must record package versions, hardware, seeds
and determinism settings. Never substitute a baseline's heuristic confidence for
class probabilities or invent distributions for abstentions.

Include reviewed simple baselines and appropriate established comparators, with
matching annotation targets. The lexicon comparator is a limited English baseline
with abstentions; it is not an emotion classifier or an empirical standard of care.
Any reused test set must be disclosed; repeated model selection on test outcomes
invalidates its role as an untouched confirmatory set.

## Multimodal design and analysis

Evaluate text only; audio only; visual only; text + audio; text + visual; audio +
visual; and all available modalities when genuine inputs and compatible models
exist. Each output declares which inputs were actually used. The framework rejects
an output that falsely claims an ablation. A learned multimodal predictor must
actually mask/drop the omitted modalities; relabeling one fused output seven times
is not an ablation experiment.

Use the default paired-complete cohort for direct comparisons. This requires the
same available inputs and gold labels for the selected variants; failed predictions
remain failures rather than selective exclusions. Report excluded counts, coverage,
answered-only metrics, end-to-end accuracy and modality patterns. If evaluating
natural missingness with per-variant cohorts, report those differences separately
and avoid attributing population composition changes to fusion efficacy.

Audio/visual refusal, failed capture and absent data are not evidence of neutral
emotion or better health. Do not synthesize missing modality data for an empirical
comparison. Record optional participation and missingness as design limitations.
Avoid a complete-case claim of representativeness when consent or missingness
selects a different student population.

Report full confusion matrices and class support, macro/weighted F1, explicitly
averaged precision/recall/F1, and accuracy according to the task. Assess ROC-AUC
and probabilistic metrics only when their input/label conditions are met, following
[EVALUATION.md](EVALUATION.md). Publish denominators and unavailable-metric reasons.
Prespecify subgroup analyses and multiple-comparison handling; sparse cells require
cautious interpretation and disclosure control. No aggregate performance measure
licenses a diagnostic or individual clinical interpretation.

Use participant-cluster uncertainty where repeated observations exist. The
framework's optional seeded percentile bootstrap and paired accuracy differences
are descriptive tools, not automatic confirmatory significance tests. Review
cluster size, dependence, class imbalance, label uncertainty, multiplicity and
sampling assumptions before making inferential claims. Do not present a model's
confidence score as an empirical confidence interval.

## System studies

Conduct approved usability tasks covering chat, independent consent choices,
withdrawal, records/privacy, support requests, counselor review and referrals.
Include keyboard/screen-reader and responsive-device testing. Record task success,
errors, assistance and measured duration; retain independently completed SUS
responses privately and summarize them with the actual instrument/version.
Repeated participants require a longitudinal analysis plan, not independent counting.

For conversation quality, preregister anchored relevance, coherence, empathy,
autonomy and groundedness rubrics. Define each 1-to-5 anchor in an approved rubric
artifact. Use trained human raters; document adjudication, context available to the
rater and blinded presentation. Report distributions and disagreement. A fluent
response is not automatically helpful, factual or safe.

For latency, identify the timing boundary and clock: request-to-first-token,
request-to-complete-response, or signal-to-human-review completion. Record warmup,
network, device, concurrency, hardware/model version, failure/timeout policy and
measurement tool. Use actual monotonic elapsed durations. Separate successes from
failed/timeout attempts and do not pool different timing phases or environments.
The runner's built-in adapter latency measures model inference, not browser or
institutional service latency.

For safety behavior, establish clinician-reviewed coded expected behaviors and
explicit prohibited or unexpected behaviors. Include contextual ambiguity,
quotation, code switching, indirect language, supportive guidance, refusal to
make diagnoses, appropriate human support, and consent/privacy boundaries.
Review harmful failures privately; do not reproduce sensitive participant text in
public reports. Keep rule-based test annotations distinct from human assessments.
Conformity on a curated test bank is not a validated estimate of crisis detection
in real students or assurance of continuously available support.

For human-review agreement, retain independent nominal decisions from a defined
rater panel before adjudication. Use matched units and an ordered fixed rater pair
for Cohen kappa; report raw agreement, marginals/confusion matrix, denominator and
undefined results. Separate AI–human from human–human comparisons. An agreement
measure does not establish truth, competence or diagnostic validity. New panels
or changed rubrics need separate strata and documented versions.

## Governance, consent and participant protection

Obtain institutional ethics approval and authorized dataset access before collection.
Document recruitment, understandable participation information, independent consent
for research and each modality, withdrawal, human escalation, accessibility,
retention, lawful institutional handling and responsible personnel. This template
is not legal advice or evidence that any approval has been granted.

Do not reactivate AI processing, raw-media retention, counselor access or research
use through evaluation code. Live research export requires explicit membership,
current research/modality permission, originally consented research sources and
live records. A later research opt-in must not retroactively authorize originally
unconsented observations. Raw text/audio/video access needs separate approved
procedures; ordinary research exports omit these inputs.

Provide an institution-approved response and escalation procedure staffed by humans,
including how to handle adverse experiences and how participants reach timely
support. Define actual monitoring and response availability without inventing a
service guarantee. Do not expose experimental risk/diagnostic-style scores to
students. Preserve the distinction between AI-generated observation and
human-reviewed assessment at collection, review, export and publication.

## Identity protection, archive and release

Use the restricted worker described in [EVALUATION.md](EVALUATION.md). Dataset-scoped
HMAC pseudonyms permit necessary grouping without exporting direct identifiers.
Keep the key and linkage in separate controlled institutional storage. Suppress
small participant cells and review rare patterns, combined releases, potential
linkage and case narratives. Pseudonymization and a minimum cell size do not prove
anonymity; obtain institutional disclosure review before sharing any artifact.

Retain reproducible aggregate reports and access-controlled private evidence with
approved retention/deletion procedures. Version every dataset release and track
memberships so withdrawn/revoked participants are excluded from future exports.
Document how already shared copies, derived results and backups are handled under
the approved plan. A database flag cannot recall an already released file. Verify
export audit commitment and authorization before release; do not publish a worker
output solely because the local file was created.

Archive protocol/ethics version, registration/analysis plan, dataset/source/license
version, annotation manual and mapping, split assignment, model artifacts and
configurations, code/dependency versions, seeds, hashes, exclusions, actual metrics,
uncertainty, raters/rubrics, failures and deviations. Keep identities, raw recordings,
text, raters' identities and case notes outside general experiment reports.
An exact reproduction of fixed-output metric calculations is different from a
new timed inference run or a clinical-effectiveness replication.

## Reporting and permissible claims

Publish actual observed results with their population, task, labeling construct,
model/dataset versions, settings, denominators, uncertainty and limitations.
Report missing data, abstentions, failed variants and negative results; never fill
unavailable cells with attractive example numbers. Keep synthetic fixtures clearly
marked and separate from empirical tables.

When no labeled data exists, report **Not evaluated — labeled dataset required.**
When labels exist but compatible model outputs, required modalities or probability
inputs do not, report the specific unevaluated/inapplicable reason. Software tests
establish implementation behavior only. This framework does not establish clinical
efficacy, acceptable institutional performance thresholds, validated distress
screening, guaranteed safety, or generalization to a new student population.
