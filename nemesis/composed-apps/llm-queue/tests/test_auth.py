import hashlib
import pytest
from app import auth


@pytest.mark.asyncio
async def test_valid_key_yields_hash_owner():
    owner = await auth.owner_for_token("sk-good-123")
    assert owner == "k:" + hashlib.sha256(b"sk-good-123").hexdigest()[:32]


@pytest.mark.asyncio
async def test_invalid_key_returns_none():
    assert await auth.owner_for_token("sk-bad") is None


@pytest.mark.asyncio
async def test_missing_token_returns_none():
    assert await auth.owner_for_token(None) is None
