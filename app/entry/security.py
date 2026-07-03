from __future__ import annotations

import hashlib
import re

from app.entry.models import SecurityFlags


PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
ID_CARD_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
BANK_CARD_RE = re.compile(r"(?<!\d)\d{13,19}(?!\d)")
TOKEN_RE = re.compile(r"\b(?:sk|ak|pk|token)[-_][A-Za-z0-9_-]{12,}\b", re.I)


def build_security_flags(text: str) -> SecurityFlags:
    normalized = str(text or "").strip()
    redacted = redact_text(normalized)
    has_pii = redacted != normalized
    reasons: list[str] = []

    if has_pii:
        reasons.append("pii_redacted")

    return SecurityFlags(
        has_pii=has_pii,
        redacted_text=redacted if has_pii else None,
        text_hash=hash_text(normalized),
        reasons=reasons,
    )


def redact_text(text: str) -> str:
    value = str(text or "")

    value = PHONE_RE.sub(lambda m: m.group(0)[:3] + "****" + m.group(0)[-4:], value)
    value = EMAIL_RE.sub(_mask_email, value)
    value = ID_CARD_RE.sub(lambda m: m.group(0)[:4] + "**********" + m.group(0)[-4:], value)
    value = BANK_CARD_RE.sub(lambda m: m.group(0)[:4] + " **** **** " + m.group(0)[-4:], value)
    value = TOKEN_RE.sub(lambda m: m.group(0)[:4] + "***", value)

    return value


def hash_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _mask_email(match: re.Match[str]) -> str:
    email = match.group(0)
    name, _, domain = email.partition("@")
    if not name:
        return "***@" + domain
    return name[:1] + "***@" + domain