"""BotFather automation — manage a planted bot's profile from inside ZeroBot.

Phase 1.ج (Bot API portion): everything reachable through the public
Telegram Bot API using a bot token. The MTProto-only operations
(profile photo, deletion, token rotation) ship in a follow-up phase
once the user-session linking flow is wired to the Mini App.
"""

from zerobot.botfather.client import BotCommand, BotFatherClient, BotFatherError
from zerobot.botfather.service import (
    BotProfile,
    fetch_bot_profile,
    update_bot_profile,
)

__all__ = [
    "BotCommand",
    "BotFatherClient",
    "BotFatherError",
    "BotProfile",
    "fetch_bot_profile",
    "update_bot_profile",
]
