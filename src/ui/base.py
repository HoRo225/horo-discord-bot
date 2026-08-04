"""Components V2 面板的共用骨架。

單一訊息模型：使用者開啟面板後，之後所有導覽、操作與結果回饋都改寫同一則訊息，
不再每次操作都送出新的 ephemeral 訊息。

本模組刻意只依賴 discord 與 strings，不 import 任何具體面板，維持單向依賴。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import Any, ClassVar

import discord

from src import strings
from src.ui.common import error_notice, send_ephemeral

log = logging.getLogger(__name__)

PanelCallback = Callable[[discord.Interaction], Awaitable[None]]
PanelFactory = Callable[[str], Awaitable[discord.ui.LayoutView]]

# 可以直接被 bot 送出訊息的頻道型別。刻意不含 forum：
# 論壇頻道沒有 send()，必須先開討論串，選了只會在執行期炸掉。
POSTABLE_CHANNEL_TYPES: tuple[discord.ChannelType, ...] = (
    discord.ChannelType.text,
    discord.ChannelType.news,
)


async def defer_update(interaction: discord.Interaction) -> None:
    """為「就地更新」預留時間。

    元件與 Modal 的 interaction 在 thinking=False 時都會取得 deferred_message_update，
    不會產生新訊息，之後用 edit_original_response 改寫原訊息即可。
    """
    if not interaction.response.is_done():
        await interaction.response.defer()


async def open_panel(interaction: discord.Interaction, panel: discord.ui.LayoutView) -> None:
    """開一則新的 ephemeral 工作區。

    只有公開儀表板與斜線指令該用它；面板內部的操作一律改用 swap_panel，
    否則會在使用者的私訊區堆出一疊殘留面板。
    """
    if interaction.response.is_done():
        await interaction.followup.send(view=panel, ephemeral=True)
    else:
        await interaction.response.send_message(view=panel, ephemeral=True)


async def swap_panel(interaction: discord.Interaction, panel: discord.ui.LayoutView) -> None:
    """就地改寫目前這則訊息的內容。

    切換到 LayoutView 時必須把 content/embeds/attachments 明確清空，
    否則舊的 V1 欄位會殘留（discord.py 的 edit_message 文件有明載此限制）。
    """
    if interaction.response.is_done():
        await interaction.edit_original_response(
            content=None, embeds=[], attachments=[], view=panel
        )
    else:
        await interaction.response.edit_message(content=None, embeds=[], attachments=[], view=panel)


async def show_error(
    interaction: discord.Interaction, error: BaseException, rebuild: PanelFactory
) -> None:
    """把錯誤就地畫回面板。

    連重建面板都失敗時（例如資料庫斷線）退回獨立訊息，
    確保使用者至少看得到失敗原因，而不是面板毫無反應。
    """
    notice = error_notice(interaction, error)
    try:
        await swap_panel(interaction, await rebuild(notice))
    except Exception:
        log.exception("面板錯誤回寫失敗", extra={"guild_id": interaction.guild_id})
        await send_ephemeral(interaction, notice)


def button(
    label: str,
    custom_id: str,
    callback: PanelCallback,
    *,
    style: discord.ButtonStyle = discord.ButtonStyle.secondary,
    emoji: str | None = None,
    disabled: bool = False,
) -> discord.ui.Button:
    """建立按鈕並綁定 callback，取代「先建物件再指派 .callback」的三行式寫法。"""
    item = discord.ui.Button(
        label=label, custom_id=custom_id, style=style, emoji=emoji, disabled=disabled
    )
    item.callback = callback
    return item


def section(text: str, accessory: discord.ui.Button | discord.ui.Thumbnail) -> discord.ui.Section:
    """左側文字、右側附件（按鈕或縮圖）的區塊。"""
    return discord.ui.Section(discord.ui.TextDisplay(text), accessory=accessory)


class Panel(discord.ui.LayoutView):
    """面板骨架。

    子類別只描述「內容」（title/accent/body/rows），Container 的組裝由基底負責，
    避免每個面板重複同一份樣板碼。
    """

    title: ClassVar[str] = ""
    body: ClassVar[str | None] = None
    accent: ClassVar[discord.Colour] = discord.Colour.blurple()

    def __init__(
        self,
        bot: Any,
        *,
        notice: str | None = None,
        back: PanelCallback | None = None,
        timeout: float | None = 300,
    ) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot
        self.notice = notice
        self.back = back
        self.add_item(discord.ui.Container(*self._assemble(), accent_colour=self.accent))

    def _assemble(self) -> list[discord.ui.Item[Any]]:
        items: list[discord.ui.Item[Any]] = []
        if self.title:
            items.append(discord.ui.TextDisplay(self.title))
        if self.notice:
            items.append(discord.ui.TextDisplay(self.notice))
        if self.body:
            items.append(discord.ui.TextDisplay(self.body))
        items.extend(self.rows())
        if self.back is not None:
            items.append(discord.ui.Separator())
            items.append(
                discord.ui.ActionRow(button(strings.NAV_BACK, "cs:nav:back", self.back, emoji="◀"))
            )
        return items

    def rows(self) -> Iterable[discord.ui.Item[Any]]:
        """子類別回傳要放進 Container 的元件（ActionRow / Section / Separator …）。"""
        return ()


class PagedPanel(Panel):
    """帶分頁的面板。

    列表一律走這裡而不是把所有項目串成一大段文字，順帶避開 2000 字元上限。
    """

    page_size: ClassVar[int] = 25

    def __init__(
        self,
        bot: Any,
        items: Sequence[Any],
        *,
        page: int = 0,
        notice: str | None = None,
        back: PanelCallback | None = None,
        timeout: float | None = 300,
    ) -> None:
        self.items = list(items)
        self.page = min(max(0, page), self.page_count - 1)
        super().__init__(bot, notice=notice, back=back, timeout=timeout)

    @property
    def page_count(self) -> int:
        return max(1, -(-len(self.items) // self.page_size))

    @property
    def page_items(self) -> list[Any]:
        start = self.page * self.page_size
        return self.items[start : start + self.page_size]

    def _respawn(self, page: int) -> PagedPanel:
        """產生同型別但不同頁的面板。子類別若有額外建構參數需覆寫此方法。"""
        return type(self)(self.bot, self.items, page=page, notice=self.notice, back=self.back)

    async def _turn(self, interaction: discord.Interaction, delta: int) -> None:
        await swap_panel(interaction, self._respawn(self.page + delta))

    async def _previous(self, interaction: discord.Interaction) -> None:
        await self._turn(interaction, -1)

    async def _next(self, interaction: discord.Interaction) -> None:
        await self._turn(interaction, 1)

    def rows(self) -> Iterable[discord.ui.Item[Any]]:
        yield from self.page_rows(self.page_items)
        if self.page_count > 1:
            yield discord.ui.TextDisplay(
                strings.PAGE_INDICATOR.format(page=self.page + 1, total=self.page_count)
            )
            yield discord.ui.ActionRow(
                button(
                    strings.PREVIOUS_PAGE,
                    "cs:nav:prev",
                    self._previous,
                    disabled=self.page == 0,
                ),
                button(
                    strings.NEXT_PAGE,
                    "cs:nav:next",
                    self._next,
                    disabled=self.page >= self.page_count - 1,
                ),
            )

    def page_rows(self, items: list[Any]) -> Iterable[discord.ui.Item[Any]]:
        """子類別把當頁項目轉成元件。"""
        return ()
