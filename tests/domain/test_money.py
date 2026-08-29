from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from reflow.domain.models import Money
from reflow.domain.types import Currency


def test_float_is_rejected() -> None:
    with pytest.raises(TypeError):
        Money(100.0)  # type: ignore[arg-type]


def test_bool_is_rejected() -> None:
    with pytest.raises(TypeError):
        Money(True)  # type: ignore[arg-type]


def test_currency_mismatch_is_rejected() -> None:
    fake_currency = object()
    with pytest.raises(TypeError):
        Money(100, fake_currency)  # type: ignore[arg-type]


@given(st.integers(min_value=-(2**62), max_value=2**62 - 1))
def test_negation_is_exact(value: int) -> None:
    money = Money(value)
    assert (-money).amount_paise == -value


@given(
    st.integers(min_value=-(2**61), max_value=2**61 - 1),
    st.integers(min_value=-(2**61), max_value=2**61 - 1),
)
def test_addition_preserves_exact_integer_value(left: int, right: int) -> None:
    assert (Money(left, Currency.INR) + Money(right, Currency.INR)).amount_paise == left + right


def test_int64_overflow_is_rejected() -> None:
    with pytest.raises(OverflowError):
        Money(2**63)


def test_timestamp_fixture_is_timezone_aware() -> None:
    assert datetime(2026, 8, 29, tzinfo=UTC).utcoffset() is not None
