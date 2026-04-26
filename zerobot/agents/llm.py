"""Anthropic Claude client wired to the Replit AI Integrations proxy.

Environment variables (auto-provisioned by the Replit AI Integrations setup):

* ``AI_INTEGRATIONS_ANTHROPIC_BASE_URL``
* ``AI_INTEGRATIONS_ANTHROPIC_API_KEY``
"""

from __future__ import annotations

import os
from functools import lru_cache

from anthropic import AsyncAnthropic

# Recommended model for the Builder Agent (best agentic / coding performance).
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 8192


class LLMConfigError(RuntimeError):
    """Raised when required Anthropic env vars are missing or empty."""


@lru_cache(maxsize=1)
def get_client() -> AsyncAnthropic:
    """Return a process-wide ``AsyncAnthropic`` client.

    Raises :class:`LLMConfigError` if the required env vars are not set.
    """
    base_url = os.environ.get("AI_INTEGRATIONS_ANTHROPIC_BASE_URL")
    api_key = os.environ.get("AI_INTEGRATIONS_ANTHROPIC_API_KEY")
    if not base_url or not api_key:
        raise LLMConfigError(
            "Anthropic AI integration env vars are missing. "
            "Run setupReplitAIIntegrations for provider 'anthropic'."
        )
    return AsyncAnthropic(base_url=base_url, api_key=api_key)
