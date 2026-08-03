from types import SimpleNamespace

from src import strings
from src.cogs.ai_chat import (
    ai_access_allowed,
    split_discord_message,
    truncate_ai_response,
)


def test_long_ai_response_is_split_within_discord_limit():
    chunks = split_discord_message(("這是一段測試文字 " * 500), limit=200)
    assert len(chunks) > 1
    assert all(0 < len(chunk) <= 200 for chunk in chunks)
    assert "".join(chunks).replace(" ", "") == ("這是一段測試文字 " * 500).replace(" ", "")


def test_ai_requires_both_whitelisted_channel_and_role():
    settings = SimpleNamespace(ai_channel_ids=[10], ai_role_ids=[20])
    assert ai_access_allowed(settings, 10, {20})
    assert not ai_access_allowed(settings, 11, {20})
    assert not ai_access_allowed(settings, 10, {21})


def test_ai_response_is_truncated_at_configured_limit():
    assert truncate_ai_response("abc", 3) == "abc"
    assert truncate_ai_response("abcdef", 3) == "abc" + strings.AI_RESPONSE_TRUNCATED
