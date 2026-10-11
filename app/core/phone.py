"""E.164 phone normalisation.

Kept deliberately conservative: we only *add* a country code when the input
is an unambiguous local mobile number for the configured default country.
Anything we cannot parse confidently is rejected rather than guessed at.
"""
from __future__ import annotations

import re

from app.core.config import settings

_NON_DIGIT = re.compile(r"[\s\-().]")
_E164 = re.compile(r"^\+[1-9]\d{6,14}$")


class PhoneError(ValueError):
    pass


def normalize_phone(raw: str | None, default_country_code: str | None = None) -> str | None:
    """Return an E.164 string (``+9665XXXXXXXX``) or ``None`` for empty input.

    Raises :class:`PhoneError` when a non-empty value cannot be normalised.
    """
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None

    value = _NON_DIGIT.sub("", value)
    cc = default_country_code or settings.business_country_code

    if value.startswith("+"):
        candidate = value
    elif value.startswith("00"):
        candidate = "+" + value[2:]
    elif value.startswith("0"):
        # Local national format, e.g. 05XXXXXXXX -> +9665XXXXXXXX
        candidate = cc + value[1:]
    elif value.startswith(cc.lstrip("+")):
        candidate = "+" + value
    else:
        # Bare digits without a trunk prefix: assume default country.
        candidate = cc + value

    if not _E164.match(candidate):
        raise PhoneError(f"'{raw}' is not a valid international phone number")
    return candidate
