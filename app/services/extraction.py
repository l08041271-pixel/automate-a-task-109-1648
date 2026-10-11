"""Conservative signal extraction from a customer's own message text.

This module NEVER invents information. It only *echoes back* things the
customer explicitly wrote (a service word, a city/district, a time phrase) so
the qualification engine has something to score. Everything extracted is
recorded as machine-detected and is always re-confirmable by a human.

Deliberately NOT extracted: price, availability, staff, ratings, or any
commitment. Those must come from the business, never from a parser.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.config import settings

#: Time phrases we recognise verbatim (English + Arabic).
_TIME_PHRASES = (
    "tonight", "today", "tomorrow", "this evening", "this morning",
    "this afternoon", "asap", "right now", "now", "this weekend", "weekend",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "اليوم", "غدا", "غداً", "الليلة", "بكرة", "هذا المساء", "بعد قليل",
)

#: Riyadh districts/landmarks we can recognise verbatim.
_DISTRICTS = (
    "al olaya", "olaya", "al malaz", "malaz", "al sulaimaniyah", "sulaimaniyah",
    "al hittin", "hittin", "al narjis", "narjis", "qurtubah", "al qurtubah",
    "al rabwah", "rabwah", "al yasmin", "yasmin", "diplomatic quarter",
    "al murabba", "murabba", "al sahafah", "sahafah", "exit 5", "exit 6",
    "العليا", "الملز", "السليمانية", "حطين", "النرجس", "القرطبة",
)

#: Explicit clock times, e.g. "8pm", "8 pm", "20:30".
_CLOCK_RE = re.compile(r"\b(\d{1,2}(?::\d{2})?\s?(?:am|pm)|\d{1,2}:\d{2})\b", re.IGNORECASE)


@dataclass
class ExtractedSignals:
    service_interest: str | None = None
    location_text: str | None = None
    preferred_time_text: str | None = None
    evidence: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not any((self.service_interest, self.location_text, self.preferred_time_text))


def _first_match(haystack: str, needles: tuple[str, ...]) -> str | None:
    for needle in needles:
        if needle and needle in haystack:
            return needle
    return None


def extract_signals(text: str | None) -> ExtractedSignals:
    """Extract service / location / time hints that the customer wrote."""
    result = ExtractedSignals()
    if not text or not text.strip():
        return result

    lowered = text.lower()

    # --- service: reuse the configured core-service keywords --------------
    service = _first_match(lowered, tuple(settings.hot_service_keyword_list))
    if service:
        result.service_interest = service
        result.evidence.append(f"service mentioned: '{service}'")

    # --- location: business city or a known district ----------------------
    location = _first_match(lowered, (settings.business_city.lower(), *_DISTRICTS))
    if location:
        # Normalise a district hit to a city-qualified label.
        if location != settings.business_city.lower():
            location = f"{settings.business_city} - {location.title()}"
        else:
            location = settings.business_city
        result.location_text = location
        result.evidence.append(f"location mentioned: '{location}'")

    # --- time: explicit clock time first, then a phrase -------------------
    clock = _CLOCK_RE.search(text)
    if clock:
        result.preferred_time_text = clock.group(0).strip()
        result.evidence.append(f"time mentioned: '{result.preferred_time_text}'")
    else:
        phrase = _first_match(lowered, _TIME_PHRASES)
        if phrase:
            result.preferred_time_text = phrase
            result.evidence.append(f"time mentioned: '{phrase}'")

    return result
