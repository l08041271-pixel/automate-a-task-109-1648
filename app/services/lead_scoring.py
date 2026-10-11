"""Transparent, rule-based lead qualification engine.

Every point is attributable: the engine returns a per-factor breakdown,
the missing information, and a recommended next action. A score is a
*triage heuristic*, never a prediction that a customer will book.

Factors and weights (total = 100)
---------------------------------
1. service_interest        0-25   how specific/dependable the requested service is
2. booking_readiness       0-25   explicit intent to arrange an appointment
3. preferred_time          0-20   how concrete the requested timing is
4. location_compatibility  0-15   is the customer in our serviceable area
5. booking_info_completeness 0-15 how much of what we need to book is present

Classification
--------------
HOT  : score >= 70
WARM : 40 <= score < 70
COLD : score < 40
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from app.core.config import settings
from app.db.enums import BookingStatus, LeadClassification, PipelineStage

# --- Tunable constants (kept in code so they are reviewable in one place) ---
MAX_SERVICE = 25
MAX_READINESS = 25
MAX_TIME = 20
MAX_LOCATION = 15
MAX_COMPLETENESS = 15
TOTAL_MAX = MAX_SERVICE + MAX_READINESS + MAX_TIME + MAX_LOCATION + MAX_COMPLETENESS

HOT_THRESHOLD = 70
WARM_THRESHOLD = 40

#: Stage already implies how far along the funnel the lead is.
_STAGE_READINESS = {
    PipelineStage.NEW: 0,
    PipelineStage.CONTACTED: 5,
    PipelineStage.QUALIFIED: 15,
    PipelineStage.BOOKED: 25,
    PipelineStage.COMPLETED: 25,
    PipelineStage.LOST: 0,
}

_INTENT_KEYWORDS = (
    "book", "booking", "appointment", "reserve", "available", "availability",
    "confirm", "schedule", "today", "tonight", "asap", "now",
    "احجز", "موعد", "حجز", "اليوم",
)
_INTENT_RE = re.compile("|".join(re.escape(k) for k in _INTENT_KEYWORDS), re.IGNORECASE)

#: Fields we need to actually arrange an appointment.
_BOOKING_FIELDS = ("name", "contact", "service_interest", "preferred_time", "location_text")


@dataclass(frozen=True)
class LeadSignals:
    """Plain input to the scorer (decoupled from the ORM model)."""

    service_interest: str | None = None
    initial_inquiry: str | None = None
    preferred_time_at: datetime | None = None
    preferred_time_text: str | None = None
    location_text: str | None = None
    name: str | None = None
    phone_e164: str | None = None
    wa_id: str | None = None
    email: str | None = None
    stage: PipelineStage = PipelineStage.NEW
    booking_status: BookingStatus | None = None
    business_city: str = settings.business_city
    hot_keywords: tuple[str, ...] = tuple(settings.hot_service_keyword_list)


@dataclass
class Factor:
    name: str
    points: int
    max_points: int
    detail: str

    def as_dict(self) -> dict:
        return {
            "factor": self.name,
            "points": self.points,
            "max_points": self.max_points,
            "detail": self.detail,
        }


@dataclass
class ScoreResult:
    score: int
    classification: LeadClassification
    factors: list[Factor] = field(default_factory=list)
    missing_info: list[str] = field(default_factory=list)
    recommended_action: str = ""

    @property
    def is_hot(self) -> bool:
        return self.classification == LeadClassification.HOT

    def explanation(self) -> dict:
        """Serialisable explanation stored on the lead + returned by the API."""
        return {
            "total_score": self.score,
            "max_score": TOTAL_MAX,
            "classification": self.classification.value,
            "factors": [f.as_dict() for f in self.factors],
            "missing_info": list(self.missing_info),
            "disclaimer": (
                "Score is a heuristic triage value based on the information "
                "provided. It is not a prediction that the customer will book."
            ),
        }


# --------------------------------------------------------------------------- #
# Individual factors
# --------------------------------------------------------------------------- #
def _score_service(s: LeadSignals) -> Factor:
    service = (s.service_interest or "").strip()
    inquiry = (s.initial_inquiry or "").lower()
    if service:
        if any(k in service.lower() for k in s.hot_keywords):
            return Factor("service_interest", MAX_SERVICE, MAX_SERVICE,
                          f"Explicit service '{service}' matches a core service.")
        return Factor("service_interest", 18, MAX_SERVICE,
                      f"Explicit service '{service}' (not a core keyword).")
    if any(k in inquiry for k in s.hot_keywords):
        return Factor("service_interest", 12, MAX_SERVICE,
                      "Service implied by the inquiry text but not stated explicitly.")
    return Factor("service_interest", 0, MAX_SERVICE, "No service interest provided.")


def _score_readiness(s: LeadSignals) -> Factor:
    base = _STAGE_READINESS.get(s.stage, 0)
    detail = f"Pipeline stage {s.stage.value} contributes {base}."
    bonus = 0
    if s.booking_status in (BookingStatus.REQUESTED, BookingStatus.CONFIRMED, BookingStatus.COMPLETED):
        bonus += 8
        detail += f" Booking status {s.booking_status.value} (+8)."
    if _INTENT_RE.search(s.initial_inquiry or ""):
        bonus += 8
        detail += " Inquiry text contains appointment intent keywords (+8)."
    points = min(MAX_READINESS, base + bonus)
    if points == 0:
        detail = "No signal that the customer wants to arrange an appointment yet."
    return Factor("booking_readiness", points, MAX_READINESS, detail)


def _score_time(s: LeadSignals) -> Factor:
    if s.preferred_time_at is not None:
        return Factor("preferred_time", MAX_TIME, MAX_TIME,
                      "A concrete preferred appointment time was provided.")
    if (s.preferred_time_text or "").strip():
        return Factor("preferred_time", 12, MAX_TIME,
                      f"Timing described in words ('{s.preferred_time_text.strip()}'), not yet concrete.")
    return Factor("preferred_time", 0, MAX_TIME, "No preferred appointment time provided.")


def _score_location(s: LeadSignals) -> Factor:
    loc = (s.location_text or "").strip()
    if not loc:
        return Factor("location_compatibility", 8, MAX_LOCATION,
                      "Location unknown; treated as neutral (not penalised heavily).")
    if s.business_city.lower() in loc.lower():
        return Factor("location_compatibility", MAX_LOCATION, MAX_LOCATION,
                      f"Location '{loc}' is within the served city ({s.business_city}).")
    return Factor("location_compatibility", 5, MAX_LOCATION,
                  f"Location '{loc}' is outside the default city ({s.business_city}); "
                  "confirm serviceability.")


def _present_booking_fields(s: LeadSignals) -> tuple[list[str], list[str]]:
    present: list[str] = []
    missing: list[str] = []
    has_contact = bool(s.phone_e164 or s.wa_id or s.email)
    checks = {
        "name": bool((s.name or "").strip()),
        "contact": has_contact,
        "service_interest": bool((s.service_interest or "").strip()),
        "preferred_time": bool(s.preferred_time_at or (s.preferred_time_text or "").strip()),
        "location_text": bool((s.location_text or "").strip()),
    }
    labels = {
        "name": "customer name",
        "contact": "a reachable contact channel (phone, WhatsApp id, or email)",
        "service_interest": "the requested service",
        "preferred_time": "a preferred appointment time",
        "location_text": "the service location",
    }
    for key in _BOOKING_FIELDS:
        (present if checks[key] else missing).append(labels[key])
    return present, missing


def _score_completeness(present: list[str]) -> Factor:
    ratio = len(present) / len(_BOOKING_FIELDS)
    points = round(MAX_COMPLETENESS * ratio)
    return Factor("booking_info_completeness", points, MAX_COMPLETENESS,
                  f"{len(present)}/{len(_BOOKING_FIELDS)} booking fields present.")


# --------------------------------------------------------------------------- #
# Recommended action
# --------------------------------------------------------------------------- #
def _recommend(classification: LeadClassification, missing: list[str]) -> str:
    if classification == LeadClassification.HOT:
        base = ("Route to the business owner now. Confirm the requested details, "
                "verify real availability with staff, and only then confirm the booking.")
        if missing:
            base += " Quick check needed: " + ", ".join(missing) + "."
        return base
    if classification == LeadClassification.WARM:
        ask = (" Ask for: " + ", ".join(missing) + ".") if missing else ""
        return ("Send one concise clarifying reply with the missing details and offer "
                "to hold a slot pending availability verification." + ask)
    return ("Low readiness. Send a single, friendly informational reply and wait for a "
            "response. Do not follow up repeatedly.")


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def score_lead(signals: LeadSignals) -> ScoreResult:
    """Score a lead from its signals. Pure function, no I/O, fully testable."""
    factors = [
        _score_service(signals),
        _score_readiness(signals),
        _score_time(signals),
        _score_location(signals),
    ]
    present, missing = _present_booking_fields(signals)
    factors.append(_score_completeness(present))

    score = max(0, min(TOTAL_MAX, sum(f.points for f in factors)))
    if score >= HOT_THRESHOLD:
        classification = LeadClassification.HOT
    elif score >= WARM_THRESHOLD:
        classification = LeadClassification.WARM
    else:
        classification = LeadClassification.COLD

    return ScoreResult(
        score=score,
        classification=classification,
        factors=factors,
        missing_info=missing,
        recommended_action=_recommend(classification, missing),
    )


def signals_from_lead(lead) -> LeadSignals:  # noqa: ANN001 - ORM Lead
    """Adapt an ORM ``Lead`` row into :class:`LeadSignals`."""
    return LeadSignals(
        service_interest=lead.service_interest,
        initial_inquiry=lead.initial_inquiry,
        preferred_time_at=lead.preferred_time_at,
        preferred_time_text=lead.preferred_time_text,
        location_text=lead.location_text,
        name=lead.name,
        phone_e164=lead.phone_e164,
        wa_id=lead.wa_id,
        email=lead.email,
        stage=lead.stage,
        booking_status=lead.booking_status,
    )
