# Analysis adapters

`text/` implements versioned preprocessing, replaceable model interfaces and registry,
inference, normalization and confidence handling. Configured models analyze submitted
student messages through consent-aware backend persistence. Analysis is disabled by
default; the supplied offline English lexicon is an unvalidated research comparator.
See [TEXT_ANALYSIS](../docs/TEXT_ANALYSIS.md) for configuration, outputs and limitations.

Speech, optional visual processing and fusion remain contracts only. No automatic
model downloads or clinical classifiers are included. See docs/AI_SAFETY.md for
consent and evaluation requirements.
