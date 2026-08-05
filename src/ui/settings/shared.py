"""settings 五個頁面共用的骨架、狀態計算與收尾流程。

抽成獨立模組是為了讓總覽與四個領域頁都能匯入同一份共用邏輯，
同時維持單向依賴：`__init__ → {五個頁面} → shared → nav → ui.base`，
頁面模組彼此互不相依，需要面板工廠表（PANELS）時一律在 callback 內延遲匯入。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, ClassVar

import discord

from src import strings
from src.database.models import GuildSettings
from src.ui.base import Panel, defer_update, panel_action, swap_panel
from src.ui.common import is_admin
from src.ui.settings.nav import NAV_HOME, nav_row
from src.ui.status import ACCENTS, Notice, StatusKind

if TYPE_CHECKING:
    from src.bot import HoRoBot


def _mention(channel_id: int | None) -> str:
    return f"<#{channel_id}>" if channel_id else strings.SETTING_NOT_CONFIGURED


def _roles(role_ids: Sequence[int]) -> str:
    return "、".join(f"<@&{role_id}>" for role_id in role_ids) or strings.SETTING_NOT_CONFIGURED


def _channels(channel_ids: Sequence[int]) -> str:
    return "、".join(f"<#{cid}>" for cid in channel_ids) or strings.SETTING_NOT_CONFIGURED


def _defaults(ids: Sequence[int]) -> list[discord.Object]:
    """把已儲存的 ID 轉成選擇器的預設值，讓使用者一開啟就看到現況。"""
    return [discord.Object(id=item) for item in ids]


def _first(select: discord.ui.ChannelSelect) -> int | None:
    """取單選頻道選擇器的結果；未選則視為停用（None）。"""
    return select.values[0].id if select.values else None


def _model_name(bot: HoRoBot, settings: GuildSettings) -> str:
    """伺服器沒指定就退回全域預設，順序與 cogs.ai_chat 實際送出請求時一致。"""
    return settings.ai_model or bot.settings.ai_default_model or ""


def module_statuses(bot: HoRoBot, settings: GuildSettings) -> dict[str, StatusKind]:
    """把各模組的設定完整度摺疊成單一狀態，讓主面板一眼看得出誰還沒設好。

    只有 AI 有中間態：它實際要「頻道 ∩ 身分組」都命中才會回應
    （見 cogs.ai_chat.ai_access_allowed），模型則允許退回全域預設。
    因此完全沒碰過視為未啟用（OFF，安靜）；碰了卻缺一角是「設了也不會動」，
    必須跳 WARN，否則管理員會以為 AI 已經開好了。

    log 與 poll 沒有中間態：欄位空著就是關閉（poll 空白代表僅管理員可建立），
    economy 四個欄位都有資料庫預設值，開箱即可用，因此恆為 OK。
    """
    scoped = bool(settings.ai_channel_ids or settings.ai_role_ids)
    complete = bool(settings.ai_channel_ids and settings.ai_role_ids and _model_name(bot, settings))
    return {
        "log": StatusKind.OK if settings.log_channel_id else StatusKind.OFF,
        "economy": StatusKind.OK,
        "poll": StatusKind.OK if settings.poll_creator_role_ids else StatusKind.OFF,
        "ai": (StatusKind.OK if complete else StatusKind.WARN) if scoped else StatusKind.OFF,
    }


class SettingsPage(Panel):
    """設定子頁的共同骨架：記住自己是哪一頁、擋非管理員、自動補上導覽列。

    由基底一次保證四個不變量，五個子類都不可能忘：

    1. 每頁底部一定有導覽列，任兩頁之間永遠只差一次點選。
    2. 導覽列前面一定有一條分隔線，「設定內容」與「換頁」不會糊成同一區。
    3. accent 一定在 Container 建構前定案（accent_colour 是建構當下取值，事後改沒用）。
    4. 一定擋掉非管理員，包括在別人開著的面板上誤觸的情況。

    子類別必須維持 ``(bot, settings, **kwargs)`` 的建構簽名：``interaction_check``
    要用 ``type(self)`` 就地重畫本頁，多出必填參數會讓那條路徑炸掉。
    """

    nav_key: ClassVar[str] = NAV_HOME

    def __init__(self, bot: HoRoBot, settings: GuildSettings, **kwargs: Any) -> None:
        self.settings = settings
        self.statuses = module_statuses(bot, settings)
        # 只在沒有通知時上狀態色：通知講的是「剛剛那個動作」，比靜態的模組狀態更該被看見，
        # 其顏色由 base.Panel 依 Notice 決定。
        if kwargs.get("notice") is None:
            self.accent = ACCENTS[self.status()]
        super().__init__(bot, **kwargs)

    def status(self) -> StatusKind:
        """本頁的狀態，決定 accent 顏色。

        nav_key 與 module_statuses() 的鍵刻意同字串，這裡才能一行取得。
        總覽頁例外：NAV_HOME 不是任何模組，直接查會 KeyError，
        所以它必須覆寫本方法改成 worst(self.statuses.values())。
        """
        return self.statuses[self.nav_key]

    def _assemble(self) -> list[discord.ui.Item[Any]]:
        items = super()._assemble()
        items.append(discord.ui.Separator())
        items.append(nav_row(self.bot, self.nav_key))
        return items

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if is_admin(interaction):
            return True
        # 就地把本頁重畫成帶錯誤通知的版本：單一訊息模型下，誤觸不該在對話區另外堆訊息。
        await defer_update(interaction)
        await swap_panel(
            interaction,
            type(self)(
                self.bot, self.settings, notice=Notice(strings.ADMIN_ONLY, StatusKind.ERROR)
            ),
        )
        return False


async def apply_setting(
    bot: HoRoBot,
    interaction: discord.Interaction,
    *,
    origin: str,
    action: str,
    values: dict[str, Any],
    notice: str | Notice | None = None,
) -> None:
    """寫入設定並就地重畫面板：各頁「選了／按了就存」的共同收尾。

    origin 是收尾後要顯示的頁（nav key）；成功與失敗都畫這一頁，
    使用者不會因為存檔失敗就被丟到別的地方。

    notice 的取捨規則：

    * 操作後仍停在同一頁、且新狀態直接寫在元件上 → **不補通知**。
      選擇器重畫後 default_values 就是答案，再貼一句「設定已儲存」只是噪音。
    * 會離開這一頁、或新狀態不在畫面元件上 → **補通知**，
      否則使用者無從確認剛才那一下有沒有生效。
    """
    # 延遲匯入：PANELS 在套件 __init__，而 __init__ 又要匯入各頁面模組（它們匯入本模組），
    # 放在模組層會在啟動時循環爆炸，故收在 callback 內。
    from src.ui.settings import PANELS

    async def rebuild(text: str | Notice | None = None) -> discord.ui.LayoutView:
        return await PANELS[origin](bot, interaction, notice=text)

    async with panel_action(interaction, rebuild):
        # 元件的 interaction 雖然已被 SettingsPage.interaction_check 擋過一次，
        # 但寫入前再確認一次才不必假設呼叫端一定掛在那個基底上。
        if not is_admin(interaction):
            await swap_panel(
                interaction, await rebuild(Notice(strings.ADMIN_ONLY, StatusKind.ERROR))
            )
            return
        await bot.settings_service.update(
            interaction.guild_id,
            interaction.user.id,
            action=action,
            values=values,
        )
        await swap_panel(interaction, await rebuild(notice))


class SettingsModal(discord.ui.Modal):
    """設定類 Modal 的共同收尾：權限二次檢查、寫入、就地更新面板。"""

    def __init__(
        self, bot: HoRoBot, settings: GuildSettings, *, title: str, custom_id: str
    ) -> None:
        super().__init__(title=title, timeout=300, custom_id=custom_id)
        self.bot = bot
        self.settings = settings

    def values(self) -> dict[str, Any]:
        raise NotImplementedError

    action = "settings"
    # 送出後要回哪一頁。做成 ClassVar 而不是建構參數，理由有三：與既有的 action 同模式，
    # 讀 Modal 的類別定義就看得完它的收尾行為；呼叫端零改動，不可能忘記傳；
    # 也避免用 closure 捕捉一個生命週期比面板還長的舊 interaction。
    origin: ClassVar[str] = NAV_HOME

    async def on_submit(self, interaction: discord.Interaction) -> None:
        # 延遲匯入：PANELS 在套件 __init__，而 __init__ 又要匯入各頁面模組（它們匯入本模組），
        # 放在模組層會在啟動時循環爆炸，故收在 callback 內。
        from src.ui.settings import PANELS

        async def rebuild(notice: str | Notice) -> discord.ui.LayoutView:
            return await PANELS[self.origin](self.bot, interaction, notice=notice)

        # 欄位格式錯誤丟出的 ValueError 由 panel_action 統一翻成 INVALID_INPUT，
        # 因此這裡不再自己接一次。
        async with panel_action(interaction, rebuild):
            # Modal 的 interaction 不會經過開啟它的面板檢查，這道防線必須留著。
            if not is_admin(interaction):
                await swap_panel(
                    interaction, await rebuild(Notice(strings.ADMIN_ONLY, StatusKind.ERROR))
                )
                return
            await self.bot.settings_service.update(
                interaction.guild_id,
                interaction.user.id,
                action=self.action,
                values=self.values(),
            )
            await swap_panel(interaction, await rebuild(Notice(strings.SUCCESS)))
