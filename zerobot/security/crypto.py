"""AES-GCM AEAD + HMAC-SHA256 helpers.

We use a tiny versioned envelope so we can rotate keys later without a
data migration: ``version_byte || 12-byte nonce || ciphertext``. The
``version`` is a single byte (1..255), which is enough for the
foreseeable future. AAD (additional authenticated data) is supported for
binding ciphertexts to a context (e.g. the user_id) so a leaked blob
can't be replayed against a different user.
"""

from __future__ import annotations

import hashlib
import hmac
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# 96-bit nonce is the AES-GCM standard length. Anything else is a footgun.
NONCE_SIZE = 12
# 32-byte master key (AES-256). We always use 256-bit for forward safety.
KEY_SIZE = 32


class CryptoError(Exception):
    """Raised on any low-level crypto failure (bad key, bad envelope, …)."""


class Cryptor:
    """Versioned AES-GCM cryptor.

    A single instance owns one key + its version number. To rotate keys,
    instantiate a new ``Cryptor`` with a fresh version and update the
    key resolver in :mod:`zerobot.security.keys`. Old envelopes can still
    be decrypted by keeping the previous instance around.
    """

    def __init__(self, master_key: bytes, key_version: int = 1) -> None:
        if not isinstance(master_key, bytes | bytearray):
            raise CryptoError("master_key must be bytes")
        if len(master_key) != KEY_SIZE:
            raise CryptoError(f"master_key must be exactly {KEY_SIZE} bytes (got {len(master_key)})")
        if not (1 <= key_version <= 255):
            raise CryptoError("key_version must be in 1..255")
        self._key = bytes(master_key)
        self._version = key_version
        self._aead = AESGCM(self._key)

    # ── encryption ─────────────────────────────────────────────────────────

    def encrypt(self, plaintext: bytes, aad: bytes = b"") -> bytes:
        """Encrypt *plaintext* and return a self-describing envelope."""
        if not isinstance(plaintext, bytes | bytearray):
            raise CryptoError("plaintext must be bytes")
        nonce = os.urandom(NONCE_SIZE)
        ct = self._aead.encrypt(nonce, bytes(plaintext), aad or None)
        return bytes([self._version]) + nonce + ct

    def encrypt_str(self, plaintext: str, aad: bytes = b"") -> bytes:
        """Convenience wrapper that UTF-8 encodes *plaintext* first."""
        return self.encrypt(plaintext.encode("utf-8"), aad)

    # ── decryption ─────────────────────────────────────────────────────────

    def decrypt(self, envelope: bytes, aad: bytes = b"") -> bytes:
        """Decrypt an envelope produced by :meth:`encrypt` (any matching version)."""
        if not isinstance(envelope, bytes | bytearray):
            raise CryptoError("envelope must be bytes")
        if len(envelope) < 1 + NONCE_SIZE + 16:  # version + nonce + min tag
            raise CryptoError("envelope too short")
        version = envelope[0]
        if version != self._version:
            raise CryptoError(
                f"envelope encrypted with key version {version}, "
                f"but this Cryptor only handles {self._version}"
            )
        nonce = envelope[1 : 1 + NONCE_SIZE]
        ct = envelope[1 + NONCE_SIZE :]
        try:
            return self._aead.decrypt(nonce, bytes(ct), aad or None)
        except Exception as exc:  # noqa: BLE001 - any AEAD failure is opaque
            raise CryptoError("decryption failed (bad key, tampered, or wrong AAD)") from exc

    def decrypt_str(self, envelope: bytes, aad: bytes = b"") -> str:
        """Decrypt and UTF-8 decode in one shot."""
        return self.decrypt(envelope, aad).decode("utf-8")

    @property
    def version(self) -> int:
        """The key version used by this cryptor (for storage debugging)."""
        return self._version


# ── helpers ────────────────────────────────────────────────────────────────


def hmac_sha256(key: bytes, message: bytes) -> str:
    """Return the hex digest of ``HMAC-SHA256(key, message)``.

    Used for searchable hashes of sensitive values (e.g. phone numbers)
    so we can dedupe / look up without ever storing the plaintext.
    """
    if not isinstance(key, bytes | bytearray) or not key:
        raise CryptoError("hmac key must be non-empty bytes")
    return hmac.new(bytes(key), message, hashlib.sha256).hexdigest()


def generate_key() -> bytes:
    """Generate a fresh 32-byte master key suitable for :class:`Cryptor`."""
    return os.urandom(KEY_SIZE)
