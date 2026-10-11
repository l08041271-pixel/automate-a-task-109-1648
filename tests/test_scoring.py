"""Unit tests for the lead qualification engine (pure functions, no DB)."""
from __future__ import annotations

from datetime import datetime, timezone

from app.db.enums import BookingStatus, LeadClassification, PipelineStage
from app.services.lead_scoring import (
    HOT_THRESHOLD,
    TOTAL_MAX,
    WARM_THRESHOLD,
    LeadSignals,
    score_lead,
)

_T = datetime(2030, 1, 1, 18, 0, tzinfo=timezone.utc)


def _classify(score: int) -> LeadClassification:
    if score >= HOT_THRESHOLD:
        return LeadClassification.HOT
    if score >= WARM_THRESHOLD:
        return LeadClassification.WARM
    return LeadClassification.COLD


def test_fully_specified_ready_lead_is_hot():
    result = score_lead(
        LeadSignals(
            service_interest="home massage",
            initial_inquiry="I want to book an appointment today",
            preferred_time_at=_T,
            location_text="Riyadh - Al Olaya",
            name="Sara",
            phone_e164="+966500000001",
            stage=PipelineStage.NEW,
            booking_status=BookingStatus.REQUESTED,
        )
    )
    # 25 (service) + 16 (readiness: stage 0 + booking 8 + intent 8)
    # + 20 (time) + 15 (location) + 15 (completeness) = 91
    assert result.score == 91
    assert result.classification == LeadClassification.HOT
    assert result.missing_info == []
    assert "Route to the business owner" in result.recommended_action


def test_early_stage_vague_inquiry_is_cold():
    result = score_lead(
        LeadSignals(
            initial_inquiry="hello, I have a question",
            email="anon@example.com",
            stage=PipelineStage.NEW,
        )
    )
    # 0 (service) + 0 (readiness) + 0 (time) + 8 (unknown location)
    # + 3 (completeness: only contact present) = 11
    assert result.score == 11
    assert result.classification == LeadClassification.COLD
    assert "customer name" in result.missing_info
    assert "the requested service" in result.missing_info
    assert "Do not follow up repeatedly" in result.recommended_action


def test_partially_qualified_lead_is_warm():
    result = score_lead(
        LeadSignals(
            service_interest="deep tissue",
            preferred_time_text="next week",
            location_text="Jeddah",
            name="Ali",
            phone_e164="+966500000002",
            stage=PipelineStage.QUALIFIED,
        )
    )
    # 18 + 15 + 12 + 5 + 15 = 65
    assert result.score == 65
    assert result.classification == LeadClassification.WARM
    assert "offer to hold a slot" in result.recommended_action


def test_explanation_is_complete_and_has_disclaimer():
    result = score_lead(LeadSignals(service_interest="massage", name="X"))
    explanation = result.explanation()
    assert explanation["total_score"] == result.score
    assert explanation["max_score"] == TOTAL_MAX == 100
    assert explanation["classification"] == result.classification.value
    factor_names = {f["factor"] for f in explanation["factors"]}
    assert factor_names == {
        "service_interest",
        "booking_readiness",
        "preferred_time",
        "location_compatibility",
        "booking_info_completeness",
    }
    assert "not a prediction" in explanation["disclaimer"]


def test_score_is_bounded_and_consistent_with_classification():
    cases = [
        LeadSignals(),
        LeadSignals(service_interest="massage"),
        LeadSignals(service_interest="massage", initial_inquiry="book now",
                    preferred_time_at=_T, location_text="Riyadh", name="A",
                    phone_e164="+966500000003", stage=PipelineStage.QUALIFIED),
    ]
    for signals in cases:
        result = score_lead(signals)
        assert 0 <= result.score <= TOTAL_MAX
        assert result.classification == _classify(result.score)
        assert sum(f.points for f in result.factors) == result.score


def test_intent_keywords_increase_readiness_score():
    without = score_lead(LeadSignals(initial_inquiry="hello"))
    with_intent = score_lead(LeadSignals(initial_inquiry="I want to book"))
    assert with_intent.score > without.score


def test_arabic_intent_keyword_is_detected():
    ar = score_lead(LeadSignals(initial_inquiry="مرحبا أريد أن أحجز موعد"))
    en = score_lead(LeadSignals(initial_inquiry="hello"))
    assert ar.score > en.score


def test_location_outside_city_scores_below_in_city():
    in_city = score_lead(LeadSignals(location_text="Riyadh"))
    out_city = score_lead(LeadSignals(location_text="Dammam"))
    assert in_city.score > out_city.score
