"""面板狀態的語意層。

面板到處都在表達「已設定／未設定／需注意／失敗」，若讓每個面板自己挑符號與顏色，
同一種狀態很快就會在不同面板長出不同樣子。集中在這裡之後，呼叫端只說語意，
符號與顏色由本模組決定。

本模組只依賴 discord 與 strings，不認識任何面板，因此可被 ui 底下任何模組匯入。
"""

from __future__ import annotations

import enum
from collections.abc import Iterable
from dataclasses import dataclass

import discord

from src import strings


class StatusKind(enum.IntEnum):
    """數值即嚴重度，worst() 直接取 max。"""

    OK = 0
    OFF = 1
    WARN = 2
    ERROR = 3


BADGES: dict[StatusKind, str] = {
    StatusKind.OK: strings.STATUS_BADGE_OK,
    StatusKind.OFF: strings.STATUS_BADGE_OFF,
    StatusKind.WARN: strings.STATUS_BADGE_WARN,
    StatusKind.ERROR: strings.STATUS_BADGE_ERROR,
}

# Container 的 accent 是一條實色窄邊條，深色主題襯在近黑、淺色主題襯在近白上，
# 因此避開兩端：太亮的色（如 emerald-400）在白底幾乎消失，Discord 內建的
# green()/red() 在深色底又偏濁。這裡取 Tailwind 500 級距的中間調，兩種背景都撐得住。
# 另外四色的「色相」本身就分得開（綠／灰／橘／紅），不必靠亮度分辨；
# 真正承載語意的是 BADGES 的符號，顏色只是加強，色覺障礙者不會因此讀不到狀態。
ACCENTS: dict[StatusKind, discord.Colour] = {
    StatusKind.OK: discord.Colour.from_rgb(16, 185, 129),
    StatusKind.OFF: discord.Colour.from_rgb(148, 163, 184),
    StatusKind.WARN: discord.Colour.from_rgb(245, 158, 11),
    StatusKind.ERROR: discord.Colour.from_rgb(239, 68, 68),
}


def badge(kind: StatusKind, text: str) -> str:
    """在文字前加上狀態徽章。"""
    return f"{BADGES[kind]} {text}"


def worst(kinds: Iterable[StatusKind]) -> StatusKind:
    """把一組子項狀態摺疊成單一總結：只要有一項壞掉，總結就該是壞的。"""
    return max(kinds, default=StatusKind.OK)


@dataclass(frozen=True, slots=True)
class Notice:
    """帶語意的面板通知。

    語意化是 opt-in：純 str 通知維持原樣不加工，只有明確包成 Notice 的才會多出
    徽章與 accent 顏色。這條界線讓既有呼叫端不必改動，也避免文字被偷偷加前綴。
    """

    text: str
    kind: StatusKind = StatusKind.OK
