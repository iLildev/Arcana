"""Sanity tests for the Builder Bot i18n bundle.

Guards against the most common drift problems:

* a key added in one language but not the others;
* a stray placeholder (``{name}``) that isn't supplied at call time;
* an unknown language code defaulting incorrectly.

The full Telegram message-handler tests live elsewhere — these tests
only cover the pure-Python translation layer.
"""

from __future__ import annotations

import pytest

from arcana.bots.builder_bot.locales import (
    DEFAULT_LANG,
    LANGUAGES,
    TRANSLATIONS,
    normalize_lang,
    t,
)


def test_default_language_is_supported() -> None:
    assert DEFAULT_LANG in LANGUAGES


@pytest.mark.parametrize("key", list(TRANSLATIONS))
def test_every_key_translated_in_every_language(key: str) -> None:
    """No language may have a missing or empty translation for any key."""
    bundle = TRANSLATIONS[key]
    missing = [lang for lang in LANGUAGES if not bundle.get(lang)]
    assert not missing, f"key {key!r} missing translations for: {missing}"


def test_normalize_lang_handles_regional_codes() -> None:
    assert normalize_lang("en-US") == "en"
    assert normalize_lang("AR") == "ar"
    assert normalize_lang("xx") == DEFAULT_LANG
    assert normalize_lang(None) == DEFAULT_LANG
    assert normalize_lang("") == DEFAULT_LANG


def test_t_falls_back_to_default_lang_for_unknown_lang() -> None:
    """Unknown lang codes yield the default-language text, not the key."""
    out = t("reset_done", lang="xx")
    assert out == TRANSLATIONS["reset_done"][DEFAULT_LANG]


def test_t_returns_marker_for_unknown_key() -> None:
    """Missing keys are obvious in the UI rather than crashing the bot."""
    assert t("does_not_exist", lang="en") == "[missing:does_not_exist]"


def test_t_substitutes_placeholders() -> None:
    out = t("balance_reply", lang="en", balance=42)
    assert "42" in out
    assert "{balance}" not in out


def test_t_swallows_missing_placeholders_gracefully() -> None:
    """A buggy caller forgetting a kwarg returns the raw template, not a 500."""
    out = t("balance_reply", lang="en")  # no `balance` kwarg
    assert "{balance}" in out


def test_help_full_includes_core_commands_in_every_language() -> None:
    """The user guide must mention every command we route on."""
    required = [
        "/start",
        "/help",
        "/balance",
        "/reset",
        "/lang",
        "/mybots",
        "/import",
    ]
    for lang in LANGUAGES:
        text = t("help_full", lang)
        for cmd in required:
            assert cmd in text, f"/{cmd!r} missing from help_full[{lang!r}]"


def test_default_language_is_english() -> None:
    """English is the platform's primary language; other locales remain supported."""
    assert DEFAULT_LANG == "en"


def test_normalize_lang_falls_back_to_english_for_unknown_codes() -> None:
    """Sanity check: switching the default away from Arabic must reach this helper."""
    assert normalize_lang("zz") == "en"
    assert normalize_lang(None) == "en"
