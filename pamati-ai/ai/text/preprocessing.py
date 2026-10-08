import unicodedata
from dataclasses import dataclass

VERSION = "unicode-nfc-strip-v1"


@dataclass(frozen=True)
class TextInput:
    text: str
    language: str | None = None


def preprocess(text: str, language: str | None = None) -> TextInput:
    if not isinstance(text, str) or "\x00" in text or len(text) > 4000:
        raise ValueError("Invalid text input")
    # Preserve case, emoji, punctuation, negation and code switching for model adapters.
    return TextInput(unicodedata.normalize("NFC", text).strip(), language)
