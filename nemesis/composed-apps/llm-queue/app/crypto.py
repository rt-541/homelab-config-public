"""Symmetric encryption for secrets persisted at rest (per-job LiteLLM keys).

A job is submitted now but run later by a worker, so the submitter's virtual key
must be stored between the two. Store it Fernet-encrypted, keyed by JOB_KEY_SECRET
(a urlsafe-base64 32-byte key, generated with `Fernet.generate_key()`), and scrub
it once the job reaches a terminal state.
"""
from __future__ import annotations

import base64
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


def _fernet() -> Fernet:
    secret = os.environ.get("JOB_KEY_SECRET")
    if not secret:
        raise RuntimeError("JOB_KEY_SECRET is not set; cannot encrypt per-job keys")
    return Fernet(secret.encode())


def _validate_token(token: str) -> None:
    """Reject tokens whose base64 encoding is not canonical.

    base64.urlsafe_b64decode strips trailing padding and silently ignores extra
    characters that fall in the padding region, so ``token + "x"`` can decode
    to the exact same bytes as ``token``.  Fernet's own HMAC check therefore
    passes, giving a false sense of tamper-detection.  We close this gap by
    verifying that the token re-encodes to itself after a decode/re-encode
    round-trip, which rejects any spurious trailing characters.
    """
    try:
        raw = base64.urlsafe_b64decode(token + "==")
        canonical = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        if token.rstrip("=") != canonical:
            raise InvalidToken
    except Exception:
        raise InvalidToken


def encrypt(plaintext: Optional[str]) -> Optional[str]:
    if plaintext is None:
        return None
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: Optional[str]) -> Optional[str]:
    if token is None:
        return None
    _validate_token(token)
    return _fernet().decrypt(token.encode()).decode()
