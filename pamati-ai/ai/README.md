# Analysis adapters

`text/` implements versioned preprocessing, replaceable model interfaces and registry,
inference, normalization and confidence handling. Configured models analyze submitted
student messages through consent-aware backend persistence. Analysis is disabled by
default; the supplied offline English lexicon is an unvalidated research comparator.
See [TEXT_ANALYSIS](../docs/TEXT_ANALYSIS.md) for configuration, outputs and limitations.

`audio/` implements explicitly consented WAV uploads, versioned acoustic summaries,
replaceable model adapters and temporary-file cleanup. Derived features can be stored
independently of raw recordings. See [AUDIO_ANALYSIS](../docs/AUDIO_ANALYSIS.md).

`visual/` implements explicitly consented, bounded image/frame-sequence processing,
replaceable observable-expression interfaces and temporary cleanup. It is disabled by
default; the baseline reports technical frame quality and abstains from expression
inference. Raw visual media is never retained. See [VISUAL_ANALYSIS](../docs/VISUAL_ANALYSIS.md).

`multimodal/` implements experimental late and weighted probability fusion, a learned
strategy interface, missing-input handling and source provenance. Explicit API requests
combine existing consented summaries. See [MULTIMODAL_FUSION](../docs/MULTIMODAL_FUSION.md).

No automatic
model downloads or clinical classifiers are included. See docs/AI_SAFETY.md for
consent and evaluation requirements.
