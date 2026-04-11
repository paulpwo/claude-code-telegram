"""Tests for scrypt KDF replacement in TokenAuthProvider._hash_token."""

import hashlib

import pytest

from src.security.auth import InMemoryTokenStorage, TokenAuthProvider


@pytest.mark.asyncio
async def test_scrypt_hash_differs_from_sha256() -> None:
    """scrypt output must NOT match the old SHA-256 scheme."""
    storage = InMemoryTokenStorage()
    provider = TokenAuthProvider(secret="testsecret", storage=storage)
    token = "mytoken"
    scrypt_hash = provider._hash_token(token)
    sha256_hash = hashlib.sha256(f"{token}testsecret".encode()).hexdigest()
    assert scrypt_hash != sha256_hash


@pytest.mark.asyncio
async def test_token_round_trip() -> None:
    """A generated token must authenticate successfully."""
    storage = InMemoryTokenStorage()
    provider = TokenAuthProvider(secret="testsecret", storage=storage)
    token = await provider.generate_token(user_id=1)
    assert await provider.authenticate(1, {"token": token})


@pytest.mark.asyncio
async def test_wrong_token_rejected() -> None:
    """A different token string must not authenticate."""
    storage = InMemoryTokenStorage()
    provider = TokenAuthProvider(secret="testsecret", storage=storage)
    await provider.generate_token(user_id=1)
    assert not await provider.authenticate(1, {"token": "wrongtoken"})


def test_hash_is_deterministic() -> None:
    """Same token + secret must always produce the same hash."""
    storage = InMemoryTokenStorage()
    provider = TokenAuthProvider(secret="mypassphrase", storage=storage)
    h1 = provider._hash_token("abc123")
    h2 = provider._hash_token("abc123")
    assert h1 == h2


def test_hash_differs_for_different_tokens() -> None:
    """Different tokens must produce different hashes."""
    storage = InMemoryTokenStorage()
    provider = TokenAuthProvider(secret="mypassphrase", storage=storage)
    assert provider._hash_token("token-a") != provider._hash_token("token-b")
