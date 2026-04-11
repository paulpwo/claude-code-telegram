"""Tests for verify_timestamp helper in src/api/auth.py."""

from datetime import UTC, datetime

from src.api.auth import verify_timestamp


def test_valid_timestamp_accepted() -> None:
    """Current timestamp must be accepted."""
    now = str(int(datetime.now(UTC).timestamp()))
    assert verify_timestamp(now) is True


def test_timestamp_at_boundary_accepted() -> None:
    """Timestamp exactly at the 300-second boundary must be accepted."""
    boundary = str(int(datetime.now(UTC).timestamp()) - 300)
    assert verify_timestamp(boundary) is True


def test_missing_timestamp_rejected() -> None:
    """None header must be rejected."""
    assert verify_timestamp(None) is False


def test_empty_timestamp_rejected() -> None:
    """Empty string must be rejected."""
    assert verify_timestamp("") is False


def test_stale_timestamp_rejected() -> None:
    """Timestamp older than 300 seconds must be rejected."""
    stale = str(int(datetime.now(UTC).timestamp()) - 301)
    assert verify_timestamp(stale) is False


def test_future_timestamp_rejected() -> None:
    """Timestamp more than 300 seconds in the future must be rejected."""
    future = str(int(datetime.now(UTC).timestamp()) + 301)
    assert verify_timestamp(future) is False


def test_malformed_timestamp_rejected() -> None:
    """Non-integer string must be rejected."""
    assert verify_timestamp("not-a-number") is False


def test_float_string_rejected() -> None:
    """Float string must be rejected (int() cannot parse it directly)."""
    assert verify_timestamp("1700000000.5") is False


def test_custom_window_accepted() -> None:
    """Custom window_seconds parameter must be respected."""
    ts = str(int(datetime.now(UTC).timestamp()) - 600)
    assert verify_timestamp(ts, window_seconds=700) is True
    assert verify_timestamp(ts, window_seconds=500) is False
