"""AI 設定頁（觸發範圍與配額）與模型挑選頁。

兩頁的分工刻意不同：

* AI 頁是導覽的一站，四個常改的東西（頻道、身分組、模型、配額）都從這裡出發。
  頻道與身分組直接做成面板上的選擇器——它們是「選一選就好」的操作，
  塞進 Modal 只會多一次開窗；只有純數字的配額才留給 Modal。
* 模型頁是從 AI 頁點進去的挑選器，不進導覽（見 ModelPanel 的說明）。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, ClassVar

import discord

from src import strings
from src.database.models import GuildSettings
from src.ui.base import (
    POSTABLE_CHANNEL_TYPES,
    PagedPanel,
    button,
    defer_update,
    panel_action,
    swap_panel,
)
from src.ui.settings.nav import NAV_AI
from src.ui.settings.shared import (
    SettingsModal,
    SettingsPage,
    _channels,
    _defaults,
    _model_name,
    _roles,
    apply_setting,
)
from src.ui.status import Notice, badge

if TYPE_CHECKING:
    from src.bot import HoRoBot

# 摘要續行的縮排。狀態徽章只出現在第一行，後面幾行補兩個全形空格對齊，
# 三行才會讀成同一個區塊的內容，而不是三段各自獨立的敘述。
_INDENT = "　　"


class AIQuotaModal(SettingsModal):
    """只收兩個配額數字。

    頻道、身分組、模型都已經是面板上的元件，不必再擠進 Modal——這也讓元件數從
    5/5（滿載，再多一欄就開不起來）降到 2/5，之後要加欄位還有餘裕。
    """

    action = "settings_ai_quota"
    # 送出後回 AI 頁而不是總覽：使用者是從 AI 頁點進來的，改完就該留在原地繼續調整。
    origin: ClassVar[str] = NAV_AI

    def __init__(self, bot: HoRoBot, settings: GuildSettings) -> None:
        super().__init__(
            bot, settings, title=strings.SETTINGS_AI_QUOTA, custom_id="cs:settings:ai:quota:modal"
        )
        self.guild_quota = discord.ui.TextInput(
            default=str(settings.ai_daily_guild_quota), max_length=9
        )
        self.user_quota = discord.ui.TextInput(
            default=str(settings.ai_daily_user_quota), max_length=9
        )
        for text, component in (
            (strings.AI_GUILD_QUOTA, self.guild_quota),
            (strings.AI_USER_QUOTA, self.user_quota),
        ):
            self.add_item(discord.ui.Label(text=text, component=component))

    def values(self) -> dict[str, Any]:
        # int() 丟出的 ValueError 由 panel_action 統一翻成輸入格式錯誤，這裡不自己接。
        return {
            "ai_daily_guild_quota": int(str(self.guild_quota)),
            "ai_daily_user_quota": int(str(self.user_quota)),
        }


async def ai_page(
    bot: HoRoBot, interaction: discord.Interaction, *, notice: str | Notice | None = None
) -> AIPage:
    settings = await bot.settings_service.get(interaction.guild_id)
    return AIPage(bot, settings, notice=notice)


class AIPage(SettingsPage):
    title = f"## 🤖 {strings.SETTINGS_AI}"
    body = strings.SETTINGS_AI_BODY
    nav_key: ClassVar[str] = NAV_AI

    def rows(self) -> Iterable[discord.ui.Item[Any]]:
        yield discord.ui.TextDisplay(self._summary())
        # 兩個選擇器之間不放分隔線：它們回答的是同一個問題（誰、在哪裡能用 AI），
        # 分開反而會讓人以為要各自獨立設定。
        yield self._scope(
            discord.ui.ChannelSelect(
                custom_id="cs:settings:ai:channels",
                channel_types=list(POSTABLE_CHANNEL_TYPES),
                placeholder=strings.AI_CHANNELS_PLACEHOLDER,
                # min_values=0 不可省：否則使用者永遠清不掉白名單，只能愈加愈多。
                min_values=0,
                max_values=25,
                default_values=_defaults(self.settings.ai_channel_ids),
            ),
            action="settings_ai_channels",
            field="ai_channel_ids",
        )
        yield self._scope(
            discord.ui.RoleSelect(
                custom_id="cs:settings:ai:roles",
                placeholder=strings.AI_ROLES_PLACEHOLDER,
                min_values=0,
                max_values=25,
                default_values=_defaults(self.settings.ai_role_ids),
            ),
            action="settings_ai_roles",
            field="ai_role_ids",
        )
        # 這條線分的是「選了就生效」與「要另外開視窗」兩種操作，不是分模組。
        yield discord.ui.Separator()
        yield discord.ui.ActionRow(
            button(
                strings.SETTINGS_MODEL,
                "cs:settings:ai:model",
                self._models,
                style=discord.ButtonStyle.primary,
                emoji="🤖",
            ),
            button(strings.SETTINGS_AI_QUOTA, "cs:settings:ai:quota", self._quota, emoji="🔢"),
        )

    def _summary(self) -> str:
        """本頁現況：三行分別回答「用哪個模型」「誰能用」「一天能用幾次」。

        這裡展開頻道與身分組的 mention（總覽頁刻意只寫數量），因為本頁只有一個模組，
        字元預算花得起；而且使用者就是為了確認「到底是哪幾個」才點進來的。
        """
        current = self.settings
        model = _model_name(self.bot, current) or strings.SETTING_NOT_CONFIGURED
        lines = (
            f"{strings.AI_MODEL}：**{model}**",
            f"{_INDENT}{strings.AI_CHANNELS}：{_channels(current.ai_channel_ids)}"
            f"｜{strings.AI_ROLES}：{_roles(current.ai_role_ids)}",
            _INDENT
            + strings.AI_QUOTA_LINE.format(
                guild=current.ai_daily_guild_quota, user=current.ai_daily_user_quota
            ),
        )
        return badge(self.status(), "\n".join(lines))

    def _scope(
        self,
        select: discord.ui.ChannelSelect[Any] | discord.ui.RoleSelect[Any],
        *,
        action: str,
        field: str,
    ) -> discord.ui.ActionRow:
        """把「誰能用 AI」的選擇器接上存檔：選完即寫入，本頁沒有儲存鈕。

        頻道與身分組共用同一段接線：兩種選中值都只取 ``.id``，差別僅在欄位名，
        各寫一份 callback 只會多出兩處可以不同步的地方。
        """

        async def choose(interaction: discord.Interaction) -> None:
            # 不補通知：重畫後選擇器的 default_values 就是最新答案（見 shared.apply_setting）。
            await apply_setting(
                self.bot,
                interaction,
                origin=NAV_AI,
                action=action,
                values={field: [item.id for item in select.values]},
            )

        select.callback = choose
        return discord.ui.ActionRow(select)

    async def _models(self, interaction: discord.Interaction) -> None:
        async with panel_action(
            interaction, lambda notice: ai_page(self.bot, interaction, notice=notice)
        ):
            await swap_panel(interaction, await model_panel(self.bot, interaction))

    async def _quota(self, interaction: discord.Interaction) -> None:
        # 開 Modal 的 callback 不套 panel_action：send_modal 必須是該次互動的首個回應，
        # 而 panel_action 一進來就 defer（見 base.panel_action 的不適用清單）。
        await interaction.response.send_modal(AIQuotaModal(self.bot, self.settings))


async def model_panel(
    bot: HoRoBot, interaction: discord.Interaction, *, notice: str | Notice | None = None
) -> ModelPanel:
    models = await bot.ai_provider.list_models()

    async def back(target: discord.Interaction) -> None:
        await defer_update(target)
        await swap_panel(target, await ai_page(bot, target))

    return ModelPanel(bot, models, notice=notice, back=back)


class ModelPanel(PagedPanel):
    """AI 模型挑選器：從 AI 頁進來，選完或返回都回 AI 頁。

    它是唯一不掛導覽列的設定畫面，改用返回鈕，理由有二：

    1. 導覽選單列的是「設定分頁」，一個一次性的挑選器混進去會讓那份清單失去意義。
    2. 上游模型清單常有數十筆，本頁已經有分頁列；再疊一列導覽，
       同一畫面就會出現兩種語意不同的「切換」，使用者得先分辨哪個是哪個。
    """

    title = f"## 🤖 {strings.SETTINGS_MODEL}"
    # 維持中性紫，不套狀態色：挑選器沒有自己的「完成度」可言，
    # 模型設得好不好是 AI 頁的事，那裡才有徽章與狀態色。
    accent = discord.Colour.from_rgb(180, 150, 255)
    page_size = 25

    def page_rows(self, items: list[Any]) -> Iterable[discord.ui.Item[Any]]:
        # 存成實例屬性，_choose 才能像 shared._first() 一樣讀元件本身的 values，
        # 而不必伸手去掏 interaction.data 這種原始 payload。
        self.model_select = discord.ui.Select(
            placeholder=strings.AI_MODEL_PLACEHOLDER,
            options=[discord.SelectOption(label=model[:100], value=model[:100]) for model in items],
        )
        self.model_select.callback = self._choose
        yield discord.ui.ActionRow(self.model_select)

    async def _choose(self, interaction: discord.Interaction) -> None:
        model = self.model_select.values[0]
        # 這一下會離開本頁，新模型也不在回去後的任何元件上，所以必須補通知，
        # 否則使用者無從確認剛才選的是哪一個（見 shared.apply_setting 的取捨規則）。
        await apply_setting(
            self.bot,
            interaction,
            origin=NAV_AI,
            action="settings_ai_model",
            values={"ai_model": model},
            notice=Notice(strings.AI_MODEL_SAVED.format(model=model)),
        )
