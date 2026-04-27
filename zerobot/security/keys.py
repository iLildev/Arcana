"""Resolve symmetric keys from environment variables.

Production deployments **must** set ``MASTER_ENCRYPTION_KEY`` and
``PHONE_HMAC_KEY`` (both base64-encoded). For local dev / unit tests we
fall back to deterministic keys derived from the ``ADMIN_TOKEN`` (or a
constant if even that is unset), and log a loud warning so this can
never accidentally ship to prod.

Key generation utility::

    python -c "import base64,os; print(base64.b64encode(os.urandom(32)).decode())"
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from functools import lru_cache

from zerobot.security.crypto import KEY_SIZE, Cryptor

log = logging.getLogger(__name__)

# Sentinels used for the dev/test fallback. **Never relied on in production.**
_DEV_FALLBACK_SALT = b"zerobot-dev-fallback-do-not-use-in-prod"
_KEY_VERSION = 1


def _decode_b64_key(raw: str, expected_len: int | None = None) -> bytes:
    """Decode a base64 (or base64url) key, raising on size mismatch."""
    raw = raw.strip()
    try:
        # Accept both standard and url-safe alphabets.
        key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except Exception:  # noqa: BLE001
        try:
            key = base64.b64decode(raw + "=" * (-len(raw) % 4))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"value is not valid base64: {exc}") from exc
    if expected_len is not None and len(key) != expected_len:
        raise ValueError(f"decoded key has wrong length ({len(key)} != {expected_len})")
    return key


def _dev_derived_key(label: bytes) -> bytes:
    """Deterministic dev-only key: SHA-256 over ``label || ADMIN_TOKEN || salt``."""
    seed = (
        label
        + b"|"
        + os.environ.get("ADMIN_TOKEN", "dev-admin-token").encode("utf-8")
        + b"|"
        + _DEV_FALLBACK_SALT
    )
    return hashlib.sha256(seed).digest()


@lru_cache(maxsize=1)
def get_master_cryptor() -> Cryptor:
    """Return the application-wide :class:`Cryptor` (singleton, cached)."""
    raw = os.environ.get("MASTER_ENCRYPTION_KEY", "").strip()
    if raw:
        key = _decode_b64_key(raw, expected_len=KEY_SIZE)
    else:
        log.warning(
            "MASTER_ENCRYPTION_KEY is not set; using a deterministic dev key. "
            "Generate one with: "
            "python -c 'import base64,os; print(base64.b64encode(os.urandom(32)).decode())'"
        )
        key = _dev_derived_key(b"master")
    return Cryptor(key, key_version=_KEY_VERSION)


@lru_cache(maxsize=1)
def get_phone_hmac_key() -> bytes:
    """Return the HMAC key used to deduplicate phones (singleton, cached)."""
    raw = os.environ.get("PHONE_HMAC_KEY", "").strip()
    if raw:
        return _decode_b64_key(raw)  # any length ≥ 16B is fine for HMAC
    log.warning(
        "PHONE_HMAC_KEY is not set; using a deterministic dev key. "
        "Generate one with the same command as MASTER_ENCRYPTION_KEY."
    )
    return _dev_derived_key(b"phone-hmac")


def reset_key_cache() -> None:
    """Clear the cached singletons (for tests that mutate env vars)."""
    get_master_cryptor.cache_clear()
    get_phone_hmac_key.cache_clear()
