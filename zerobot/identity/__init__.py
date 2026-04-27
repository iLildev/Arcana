"""Identity layer — phone verification, quotas, and Telegram session linking.

Built on top of :mod:`zerobot.security`. Every operation here expects a
SQLAlchemy ``AsyncSession`` from the caller; this package never opens
its own engine so it can be unit-tested with sqlite or postgres equally.
"""

from zerobot.identity.phone import (
    PhoneError,
    is_phone_verified,
    normalize_e164,
    phone_hash,
    record_phone_verification,
    unlink_phone,
)
from zerobot.identity.quota import QuotaError, check_bot_quota, set_bot_quota
from zerobot.identity.sessions import (
    SessionLinkError,
    is_linked,
    revoke_session,
    store_session,
    unwrap_session,
)

__all__ = [
    "PhoneError",
    "QuotaError",
    "SessionLinkError",
    "check_bot_quota",
    "is_linked",
    "is_phone_verified",
    "normalize_e164",
    "phone_hash",
    "record_phone_verification",
    "revoke_session",
    "set_bot_quota",
    "store_session",
    "unlink_phone",
    "unwrap_session",
]
