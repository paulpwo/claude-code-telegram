"""Tests for admin_user_ids in WhitelistAuthProvider.get_user_info."""

import pytest

from src.security.auth import WhitelistAuthProvider


@pytest.mark.asyncio
async def test_admin_user_gets_admin_permission() -> None:
    """Admin user must have both 'basic' and 'admin' in permissions."""
    provider = WhitelistAuthProvider([42, 99], admin_user_ids=[42])
    info = await provider.get_user_info(42)
    assert info is not None
    assert "admin" in info["permissions"]
    assert "basic" in info["permissions"]


@pytest.mark.asyncio
async def test_non_admin_user_no_admin_permission() -> None:
    """Non-admin whitelisted user must NOT have 'admin' permission."""
    provider = WhitelistAuthProvider([42, 99], admin_user_ids=[42])
    info = await provider.get_user_info(99)
    assert info is not None
    assert "admin" not in info["permissions"]
    assert "basic" in info["permissions"]


@pytest.mark.asyncio
async def test_empty_admin_ids_means_no_admin() -> None:
    """When admin_user_ids is not provided, no user gets admin permission."""
    provider = WhitelistAuthProvider([42])
    info = await provider.get_user_info(42)
    assert info is not None
    assert "admin" not in info["permissions"]


@pytest.mark.asyncio
async def test_unauthenticated_user_returns_none() -> None:
    """User not in whitelist returns None even if in admin_user_ids."""
    provider = WhitelistAuthProvider([99], admin_user_ids=[42])
    info = await provider.get_user_info(42)
    assert info is None
