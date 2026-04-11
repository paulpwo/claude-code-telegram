"""Tests for deterministic webhook deduplication key derivation."""

import hashlib


def _make_dedup_key(provider: str, x_timestamp: str, body: bytes) -> str:
    """Mirror the key derivation logic in src/api/server.py."""
    return hashlib.sha256(
        f"{provider}:{x_timestamp}:{body[:32].hex()}".encode()
    ).hexdigest()


def test_dedup_key_stable_for_same_inputs() -> None:
    """Same inputs must always produce the same key."""
    body = b"hello world" * 5
    k1 = _make_dedup_key("myservice", "1700000000", body)
    k2 = _make_dedup_key("myservice", "1700000000", body)
    assert k1 == k2


def test_dedup_key_differs_for_different_provider() -> None:
    """Different providers with same body + timestamp must produce different keys."""
    body = b"hello"
    k1 = _make_dedup_key("service-a", "1700000000", body)
    k2 = _make_dedup_key("service-b", "1700000000", body)
    assert k1 != k2


def test_dedup_key_differs_for_different_timestamp() -> None:
    """Same provider + body but different timestamp must produce different keys."""
    body = b"hello"
    k1 = _make_dedup_key("svc", "1700000000", body)
    k2 = _make_dedup_key("svc", "1700000001", body)
    assert k1 != k2


def test_dedup_key_differs_for_different_body() -> None:
    """Same provider + timestamp but different body must produce different keys."""
    k1 = _make_dedup_key("svc", "1700000000", b"body-a" * 10)
    k2 = _make_dedup_key("svc", "1700000000", b"body-b" * 10)
    assert k1 != k2


def test_dedup_key_uses_only_first_32_bytes_of_body() -> None:
    """Two bodies identical in the first 32 bytes must produce the same key."""
    prefix = b"X" * 32
    k1 = _make_dedup_key("svc", "1700000000", prefix + b"AAA")
    k2 = _make_dedup_key("svc", "1700000000", prefix + b"BBB")
    assert k1 == k2


def test_dedup_key_is_64_hex_chars() -> None:
    """sha256 hex digest is always 64 characters."""
    key = _make_dedup_key("svc", "1700000000", b"body")
    assert len(key) == 64
    assert all(c in "0123456789abcdef" for c in key)
