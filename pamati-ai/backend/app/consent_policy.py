"""Versioned student disclosures. Changes to these words require a new policy version."""

from copy import deepcopy
from hashlib import sha256
from urllib.parse import urlsplit

POLICY_VERSION = "2026-10-08.1"
DISCLOSURES = [
    {
        "title": "Purpose",
        "text": "PamatiAI is a research and student-support tool for higher education. It is designed to support reflection on conversations and, if you choose, patterns over time.",
    },
    {
        "title": "What AI analysis does",
        "text": "Text conversation uses your written messages and recent messages in the same conversation to prepare supportive replies. The default is a local predefined response service, not an LLM or sentiment analysis. A separately configured model service may receive this text when disclosed below. Sentiment or affect analysis uses only the modalities you permit and is separate from conversational replies. Saving consent does not start recording or analysis.",
    },
    {
        "title": "What it does not do",
        "text": "PamatiAI does not diagnose mental-health conditions, prescribe treatment, read your mind, identify you from your face or replace a qualified professional. A score is not a clinical assessment.",
    },
    {
        "title": "Limits and uncertainty",
        "text": "Automated sentiment estimates can be wrong. Language, dialect, culture, sarcasm, context, recording quality and differences between training data and your experience can affect results. Signals may be missed or raised unnecessarily. You can ask a person to discuss or correct an interpretation.",
    },
    {
        "title": "Human oversight",
        "text": "A counselor can review your records only with an active assignment and your separate reviewer-access permission. Review is not continuous or guaranteed to be immediate. Administrator status alone does not permit reading conversations.",
    },
    {
        "title": "Modalities and choice",
        "text": "Text analysis uses written messages. Audio analysis would use speech and vocal features; visual analysis would use optional visual samples. Audio, visual, longitudinal tracking and research use are independent choices. No microphone or camera is activated here. Text consent is needed for AI conversational functionality, but you may decline it and still use privacy controls and request human support.",
    },
    {
        "title": "Data retention",
        "text": "The current configured retention periods are shown below. Audio and visual analysis permission is separate from permission to retain raw recordings. Raw retention is off by default and requires institutional configuration as well as your explicit choice. Backups and documented, time-limited institutional holds may delay deletion. Withdrawing analysis consent does not itself delete historical records.",
    },
    {
        "title": "Research use",
        "text": "Research use is optional and independent of support. Only separately approved research workflows may use permitted records, with documented ethics approval and de-identification. Pseudonyms reduce exposure but do not guarantee anonymity. Withdrawal blocks new research use and marks linked records revoked; material already exported or published may require institutional review and may not be fully retractable.",
    },
    {
        "title": "Changing or withdrawing",
        "text": "You can change individual choices or withdraw all consent from this same account at any time. Future work will use your latest choices; queued work is cancelled and results from work already in progress are discarded if permission changes before saving. Processing already performed cannot be undone. You may separately request a personal export or deletion and see any documented retention restrictions.",
    },
    {
        "title": "Emergency limitations",
        "text": "PamatiAI is not an emergency service, does not guarantee detection of distress and cannot dispatch emergency help. If you or someone else is in immediate danger, contact local emergency services or seek immediate help from a person or nearby emergency facility. Do not wait for an AI score or a counselor response here.",
    },
]


def policy_document():
    from app.config import get_settings
    from app.text_analysis import disclosure

    settings = get_settings()
    processing = {
        "provider": settings.conversation_provider,
        "host": urlsplit(settings.conversation_endpoint).hostname or "PamatiAI server",
        "endpoint_fingerprint": sha256(settings.conversation_endpoint.encode()).hexdigest(),
        "model": settings.conversation_model
        if settings.conversation_provider == "compatible-http"
        else "rule-based-support",
        "version": settings.conversation_model_version
        if settings.conversation_provider == "compatible-http"
        else "1",
    }
    disclosures = deepcopy(DISCLOSURES)
    disclosures[1]["text"] += (
        f" Current conversational processor: {processing['provider']} on {processing['host']}; model {processing['model']}, version {processing['version']}."
    )
    text_processing = disclosure()
    disclosures[1]["text"] += (
        " Current text-analysis models on the PamatiAI server: "
        + (", ".join(f"{m['identifier']} version {m['version']}" for m in text_processing["models"])
           or "disabled")
        + ". When enabled, each submitted student message is analyzed separately from replies."
    )
    return {
        "version": POLICY_VERSION,
        "disclosures": disclosures,
        "conversation_processing": processing,
        "text_analysis_processing": text_processing if text_processing["models"] else {"models": []},
    }
