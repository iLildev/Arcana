"""Unit tests for AES-GCM envelope + HMAC helpers."""

from __future__ import annotations

import os

import pytest

from zerobot.security.crypto import (
    CryptoError,
    Cryptor,
    generate_key,
    hmac_sha256,
)
from zerobot.security.keys import (
    get_master_cryptor,
    get_phone_hmac_key,
    reset_key_cache,
)


def test_round_trip_str() -> None:
    key = generate_key()
    cr = Cryptor(key)
    plaintext = "hello world 🌍"
    envelope = cr.encrypt_str(plaintext)
    assert cr.decrypt_str(envelope) == plaintext


def test_round_trip_bytes_with_aad() -> None:
    cr = Cryptor(generate_key())
    pt = b"\x00\x01\x02 secret payload"
    aad = b"user-42"
    env = cr.encrypt(pt, aad=aad)
    assert cr.decrypt(env, aad=aad) == pt


def test_aad_mismatch_fails_decryption() -> None:
    cr = Cryptor(generate_key())
    env = cr.encrypt(b"x", aad=b"user-1")
    with pytest.raises(CryptoError):
        cr.decrypt(env, aad=b"user-2")


def test_envelope_includes_version_byte() -> None:
    cr = Cryptor(generate_key(), key_version=7)
    env = cr.encrypt(b"abc")
    assert env[0] == 7  # first byte == version


def test_decrypt_rejects_wrong_version() -> None:
    key = generate_key()
    env = Cryptor(key, key_version=1).encrypt(b"hi")
    with pytest.raises(CryptoError, match="key version"):
        Cryptor(key, key_version=2).decrypt(env)


def test_short_envelope_rejected() -> None:
    cr = Cryptor(generate_key())
    with pytest.raises(CryptoError, match="too short"):
        cr.decrypt(b"\x01\x02")


def test_bad_key_size_rejected() -> None:
    with pytest.raises(CryptoError, match="32 bytes"):
        Cryptor(b"too short")


def test_two_encryptions_differ() -> None:
    cr = Cryptor(generate_key())
    a = cr.encrypt(b"same")
    b = cr.encrypt(b"same")
    # Same plaintext but different nonces → different ciphertexts.
    assert a != b
    assert cr.decrypt(a) == cr.decrypt(b) == b"same"


def test_hmac_is_deterministic_and_distinguishes() -> None:
    key = b"k" * 32
    a = hmac_sha256(key, b"+447700900000")
    b = hmac_sha256(key, b"+447700900000")
    c = hmac_sha256(key, b"+447700900001")
    assert a == b
    assert a != c
    assert len(a) == 64  # hex digest of SHA-256


def test_hmac_rejects_empty_key() -> None:
    with pytest.raises(CryptoError, match="non-empty"):
        hmac_sha256(b"", b"x")


def test_dev_keys_are_stable_across_calls() -> None:
    """Without env vars, the resolver gives a deterministic dev key."""
    os.environ.pop("MASTER_ENCRYPTION_KEY", None)
    os.environ.pop("PHONE_HMAC_KEY", None)
    reset_key_cache()
    cr1 = get_master_cryptor()
    cr2 = get_master_cryptor()
    assert cr1 is cr2  # cached singleton
    h1 = get_phone_hmac_key()
    h2 = get_phone_hmac_key()
    assert h1 == h2
