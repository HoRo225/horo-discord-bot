from __future__ import annotations

from types import SimpleNamespace

import discord

from src import strings
from src.cogs.event_log import EventLogCog


class CountingSettingsService:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.calls = 0

    async def get(self, _guild_id):
        self.calls += 1
        return self.settings


class RecordingChannel(discord.abc.Messageable):
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def _get_channel(self):  # discord.abc.Messageable 的抽象方法
        return self

    async def send(self, content=None, **_kwargs):
        self.sent.append(content)


def _guild(channel):
    return SimpleNamespace(id=1, get_channel=lambda _id: channel)


def _member(guild):
    return SimpleNamespace(guild=guild, __str__=lambda _self: "阿宅#0001")


async def test_logging_an_event_reads_settings_exactly_once():
    """_log() 以前會自己再查一次 settings，讓每個被記錄的事件多開一次 DB 交易。"""
    channel = RecordingChannel()
    service = CountingSettingsService(
        SimpleNamespace(log_channel_id=42, log_member_events=True, log_message_events=True)
    )
    cog = EventLogCog(SimpleNamespace(settings_service=service))
    guild = _guild(channel)

    await cog.on_member_join(SimpleNamespace(guild=guild))

    assert service.calls == 1
    assert len(channel.sent) == 1
    assert strings.EVENT_MEMBER_JOINED.split("{")[0] in channel.sent[0]


async def test_no_log_channel_configured_sends_nothing():
    channel = RecordingChannel()
    service = CountingSettingsService(
        SimpleNamespace(log_channel_id=None, log_member_events=True, log_message_events=True)
    )
    cog = EventLogCog(SimpleNamespace(settings_service=service))

    await cog.on_member_join(SimpleNamespace(guild=_guild(channel)))

    assert channel.sent == []
