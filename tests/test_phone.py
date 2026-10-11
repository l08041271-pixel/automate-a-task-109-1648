"""Phone normalisation tests."""
from __future__ import annotations

import pytest

from app.core.phone import PhoneError, normalize_phone


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0500000001", "+966500000001"),
        ("+966500000001", "+966500000001"),
        ("966500000001", "+966500000001"),
        ("00966500000001", "+966500000001"),
        ("050 000 0001", "+966500000001"),
        ("+1 415 555 2671", "+14155552671"),
        (None, None),
        ("", None),
    ],
)
def test_normalize_phone_valid(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["abc", "12", "+", "000000"])
def test_normalize_phone_invalid(raw):
    with pytest.raises(PhoneError):
        normalize_phone(raw)
