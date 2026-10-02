"""Authorization policy only: callers must authenticate principals on the server."""
from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    STUDENT = "STUDENT"
    COUNSELOR = "COUNSELOR"
    SYSTEM_ADMINISTRATOR = "SYSTEM_ADMINISTRATOR"


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: Role


def permitted(
    principal: Principal,
    permission: str,
    *,
    student_id: str | None = None,
    assigned: bool = False,
    consent_active: bool = False,
) -> bool:
    if principal.role == Role.STUDENT:
        return permission in {"consent:manage", "conversation:manage", "history:read", "privacy:manage"} and student_id == principal.user_id
    if principal.role == Role.COUNSELOR:
        return permission in {"history:read", "review:manage"} and student_id is not None and assigned and consent_active
    if principal.role == Role.SYSTEM_ADMINISTRATOR:
        return permission in {"accounts:manage", "configuration:manage"} and student_id is None
    return False
