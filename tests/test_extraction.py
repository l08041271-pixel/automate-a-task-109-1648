"""Tests for conservative message-text extraction.

The extractor must only echo back what the customer actually wrote, and must
never manufacture a service, location, time, price or availability.
"""
from __future__ import annotations

from app.services.extraction import extract_signals


def test_empty_and_blank_text_yield_nothing():
    for value in (None, "", "   "):
        result = extract_signals(value)
        assert result.is_empty
        assert result.service_interest is None
        assert result.location_text is None
        assert result.preferred_time_text is None


def test_extracts_service_location_and_time_from_one_message():
    result = extract_signals("I want to book a home massage in Riyadh tonight")
    assert result.service_interest == "massage"
    assert result.location_text == "Riyadh"
    assert result.preferred_time_text == "tonight"
    assert len(result.evidence) == 3


def test_clock_time_wins_over_vague_phrase():
    result = extract_signals("can we do today at 8pm?")
    assert result.preferred_time_text == "8pm"


def test_district_is_normalised_to_city_qualified_label():
    result = extract_signals("I'm in Al Olaya")
    assert result.location_text == "Riyadh - Al Olaya"


def test_arabic_time_phrase_is_recognised():
    result = extract_signals("أريد حجز موعد الليلة")
    assert result.preferred_time_text == "الليلة"
    assert result.service_interest == "حجز"


def test_does_not_invent_a_service_when_none_mentioned():
    result = extract_signals("hello, are you open?")
    assert result.service_interest is None
    assert result.location_text is None


def test_price_availability_and_promises_are_never_extracted():
    result = extract_signals("How much is it? Do you have a slot at 9pm? Is it confirmed?")
    # Only the explicit time is echoed back; nothing about price/availability.
    assert result.preferred_time_text == "9pm"
    assert result.service_interest is None
    assert result.location_text is None
