import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol

from services.conversation.prompt import SYSTEM_PROMPT


@dataclass(frozen=True)
class Reply:
    text: str
    provider: str
    model: str
    version: str
    fallback: bool = False


class ConversationProvider(Protocol):
    def generate(self, messages: list[dict[str, str]]) -> Reply: ...


FALLBACK = "I’m PamatiAI, an AI assistant. I couldn’t generate a response just now. You can try again, or reach out to a trusted person or your campus support office. If you are in immediate danger, contact local emergency services; this chat cannot provide emergency help."


class LocalSupportProvider:
    """Deterministic offline baseline, explicitly not an LLM or sentiment model."""

    def generate(self, messages: list[dict[str, str]]) -> Reply:
        text = messages[-1]["content"].casefold()
        if any(word in text for word in ("exam", "study", "deadline", "assignment", "grades")):
            answer = "Study pressure can feel overwhelming. You could choose one small task, work on it for ten minutes, then take a break. An instructor or campus academic support office may help you explore extensions or study support. What part feels hardest to start?"
        elif any(word in text for word in ("campus", "counselor", "counsellor", "support", "help")):
            answer = "You deserve support that fits your needs. Your campus student affairs or counseling office may be a place to ask about available options; I don’t have a verified campus directory. You can also use Help here to request human support, though it is not an emergency channel. Would you like help thinking through what to ask?"
        else:
            answer = "Thank you for sharing that. I’m an AI assistant, and I can help you reflect, though I may miss important context. You can share only what feels comfortable. Would it help to talk about what has been weighing on you, or think through a small next step?"
        return Reply(answer, "local-support", "rule-based-support", "1")


class CompatibleHTTPProvider:
    """Adapter for a deployment-approved chat-completions compatible server."""

    def __init__(self, settings):
        self.settings = settings

    def generate(self, messages: list[dict[str, str]]) -> Reply:
        import httpx

        with (
            httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as client,
            client.stream(
                "POST",
                self.settings.conversation_endpoint,
                headers={"Authorization": f"Bearer {self.settings.conversation_api_key}"},
                json={
                    "model": self.settings.conversation_model,
                    "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *messages],
                    "max_tokens": 500,
                },
            ) as response,
        ):
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_bytes(chunk_size=8192):
                content.extend(chunk)
                if len(content) > 65536:
                    raise ValueError("Oversized provider response")
            payload = json.loads(content)
        return Reply(
            payload["choices"][0]["message"]["content"],
            "compatible-http",
            str(payload.get("model", self.settings.conversation_model))[:160],
            self.settings.conversation_model_version,
        )


def get_provider() -> ConversationProvider:
    from app.config import get_settings

    settings = get_settings()
    if settings.conversation_provider == "compatible-http":
        if not settings.conversation_endpoint or not settings.conversation_model:
            raise ValueError("Conversation provider is not configured")
        return CompatibleHTTPProvider(settings)
    return LocalSupportProvider()


def safe_reply(messages: list[dict[str, str]]) -> Reply:
    from app.safety import screen
    from services.safety.resources import supportive_message

    candidates, policy, resources = screen(messages[-1]["content"])
    if candidates:
        return Reply(
            supportive_message("urgent" if any(c.priority == "urgent" for c in candidates) else "prompt", resources),
            "local-safety",
            "literal-safety-analysis",
            policy.fingerprint,
        )
    try:
        reply = get_provider().generate(messages)
        text = reply.text
        forbidden = (
            "i know exactly how you feel",
            "as a human",
            "i am human",
            "i'm human",
            "i am a human",
            "i'm a human",
            "you have depression",
            "you have bipolar",
            "you have anxiety disorder",
            "i diagnose",
            "i am your therapist",
            "i'm your therapist",
            "as your therapist",
            "you are depressed",
            "depressed student",
            "suicidal student",
            "mental disorder detected",
            "you are suicidal",
            "you are mentally ill",
            "your mental health score",
        )
        if not isinstance(text, str) or not text.strip() or len(text) > 6000:
            raise ValueError("Invalid provider output")
        normalized = " ".join(
            unicodedata.normalize("NFKC", text)
            .casefold()
            .replace("’", "'")
            .replace("*", "")
            .replace("_", "")
            .split()
        )
        clinical_assertion = re.search(
            r"\b(?:your diagnosis is|you (?:are diagnosed with|meet the criteria for)|you (?:have|suffer from) (?:clinical |a |an )?(?:depression|bipolar|ptsd|adhd|ocd|schizophrenia|autism|panic disorder|anxiety disorder|[a-z -]+ disorder))\b",
            normalized,
        )
        if any(s in normalized for s in forbidden) or clinical_assertion:
            raise ValueError("Unsafe or invalid provider output")
        return reply
    except Exception:  # noqa: BLE001 - provider boundary must fail closed for every adapter failure
        # Never expose provider errors, credentials or student content in logs/API errors.
        return Reply(FALLBACK, "local-fallback", "support-fallback", "1", True)
