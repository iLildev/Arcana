"""Security primitives — symmetric encryption and HMAC helpers.

This package centralizes the cryptography used everywhere else in the
project so we have a single, reviewed surface for key handling, AEAD
envelopes, and HMACs. Nothing in this package should ever read or write
the database, so it stays trivial to unit-test.
"""

from zerobot.security.crypto import (
    CryptoError,
    Cryptor,
    generate_key,
    hmac_sha256,
)
from zerobot.security.keys import get_master_cryptor, get_phone_hmac_key

__all__ = [
    "CryptoError",
    "Cryptor",
    "generate_key",
    "get_master_cryptor",
    "get_phone_hmac_key",
    "hmac_sha256",
]
