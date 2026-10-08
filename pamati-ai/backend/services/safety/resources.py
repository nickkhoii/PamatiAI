from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SafetyResource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=60, pattern=r"^[a-z0-9-]+$")
    label: str = Field(min_length=1, max_length=160)
    kind: str = Field(pattern=r"^(emergency|crisis|campus|trusted_support)$")
    institution: str = Field(min_length=1, max_length=160)
    jurisdiction: str = Field(min_length=1, max_length=160)
    phone: str = Field(default="", max_length=60, pattern=r"^[0-9+() -]*$")
    url: str = Field(default="", max_length=2048)
    availability: str = Field(default="Confirm current availability", max_length=200)

    @field_validator("url")
    @classmethod
    def safe_url(cls, value):
        parsed = urlsplit(value)
        if value and (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password):
            raise ValueError("Use institution-verified HTTPS resource links without credentials")
        return value


def supportive_message(priority, resources):
    if priority == "urgent":
        text = ("Thank you for telling me. Your immediate safety matters. If you or someone else may be in immediate danger, "
                "contact your local emergency service or go to the nearest emergency department now. "
                "If possible, reach a trusted person who can stay with you and help you get support. "
                "You can also contact an appropriate local crisis service. Please do not wait for this chat or a trend estimate. ")
    else:
        text = ("Thank you for sharing this. If you do not feel safe, reach a trusted person or an appropriate local support service. "
                "If there is immediate danger, contact your local emergency service now rather than waiting for this chat. ")
    for resource in resources:
        contact = "; ".join(value for value in (resource.phone, resource.url) if value)
        if contact:
            text += f"{resource.label} ({resource.jurisdiction}): {contact}. {resource.availability}. "
    if not resources:
        text += "No institution-verified contact directory is currently configured here. "
    return text + "PamatiAI cannot dispatch emergency help or guarantee immediate human review. It has not automatically contacted anyone."
