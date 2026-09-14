import pytest
from cryptography.fernet import InvalidToken

from app import crypto


def test_round_trip():
    token = crypto.encrypt("sk-secret-123")
    assert token != "sk-secret-123"
    assert crypto.decrypt(token) == "sk-secret-123"


def test_encrypt_none_is_none():
    assert crypto.encrypt(None) is None
    assert crypto.decrypt(None) is None


def test_tampered_token_raises():
    token = crypto.encrypt("sk-secret-123")
    with pytest.raises(InvalidToken):
        crypto.decrypt(token + "x")
