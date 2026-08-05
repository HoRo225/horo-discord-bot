from __future__ import annotations

import logging
from datetime import UTC, datetime

from src import strings
from src.services.ai.base import AIProvider, ChatMessage
from src.services.ai.governance import (
    ConversationMemory,
    InMemoryRateLimiter,
    redact_sensitive,
)
from src.services.ai.quota import AIUsageService
from src.services.common import DomainError

log = logging.getLogger(__name__)


class AIDisabledError(DomainError):
    """伺服器與全域都沒有可用模型。"""


class AIRateLimitedError(DomainError):
    """使用者的個人冷卻時間還沒到。"""


def truncate_ai_response(content: str, max_characters: int) -> str:
    if len(content) <= max_characters:
        return content
    return content[:max_characters] + strings.AI_RESPONSE_TRUNCATED


class AIConversationService:
    """把一句使用者輸入變成一段可直接送出的回覆，過程中負責配額、記憶與遮罩。

    刻意不注入 SettingsService：呼叫端為了判斷「這則訊息該不該回」本來就得先讀
    settings，這裡再讀一次等於每則訊息多開一次 DB 交易，因此改由呼叫端把需要的
    三個窄值傳進來。
    """

    def __init__(
        self,
        *,
        provider: AIProvider,
        quota: AIUsageService,
        memory: ConversationMemory,
        rate_limiter: InMemoryRateLimiter,
        default_model: str,
        max_response_chars: int,
        known_secrets: tuple[str, ...] = (),
    ) -> None:
        self.provider = provider
        self.quota = quota
        self.memory = memory
        self.rate_limiter = rate_limiter
        self.default_model = default_model
        self.max_response_chars = max_response_chars
        self.known_secrets = known_secrets

    async def respond(
        self,
        *,
        guild_id: int,
        channel_id: int,
        user_id: int,
        prompt: str,
        guild_model: str | None,
        guild_quota: int,
        user_quota: int,
        now: datetime | None = None,
    ) -> str:
        # 整段流程共用同一個時間點：配額是按台北日期分列的，若讓 reserve 與
        # release 各自重算「今天」，跨午夜失敗的請求會扣在昨天、退在今天。
        current = now or datetime.now(UTC)
        model = guild_model or self.default_model
        if not model:
            raise AIDisabledError(strings.AI_DISABLED)
        if not self.rate_limiter.allow(guild_id, user_id):
            raise AIRateLimitedError(strings.AI_RATE_LIMIT)

        # 提示詞刻意在扣配額之前組好：這樣 reserve 與 chat 之間不存在任何會失敗的
        # 程式碼，補償邏輯就只需要涵蓋 chat 這一個呼叫。
        safe_prompt = self._redact(prompt or strings.AI_EMPTY_PROMPT)
        request_messages = [
            ChatMessage("system", strings.AI_SYSTEM_PROMPT),
            *self.memory.get(guild_id, channel_id),
            ChatMessage("user", safe_prompt),
        ]

        await self.quota.reserve(
            guild_id=guild_id,
            user_id=user_id,
            guild_quota=guild_quota,
            user_quota=user_quota,
            now=current,
        )
        try:
            response = await self.provider.chat(model=model, messages=request_messages)
        except BaseException:
            # 用 BaseException 而非 Exception：互動逾時或使用者取消會讓這個 task
            # 收到 CancelledError（繼承自 BaseException），那同樣沒有真的用掉配額。
            await self._safe_release(guild_id, user_id, now=current)
            raise

        response = truncate_ai_response(self._redact(response), self.max_response_chars)
        self.memory.add(guild_id, channel_id, ChatMessage("user", safe_prompt))
        self.memory.add(guild_id, channel_id, ChatMessage("assistant", response))
        # 字數記帳從「送出 Discord 成功後」提前到回傳前：字數只是統計欄位、不參與
        # 配額判定（配額看的是 request_count），換得「送訊息完全不碰配額」的乾淨邊界。
        try:
            await self.quota.record_characters(
                guild_id=guild_id,
                user_id=user_id,
                character_count=len(response),
                now=current,
            )
        except Exception:
            log.exception("記錄 AI 回應字數失敗", extra={"guild_id": guild_id})
        return response

    def _redact(self, text: str) -> str:
        return redact_sensitive(text, known_secrets=self.known_secrets)

    async def _safe_release(self, guild_id: int, user_id: int, *, now: datetime) -> None:
        """補償失敗不該蓋掉原始的上游錯誤，所以只記錄不外拋。"""
        try:
            await self.quota.release(guild_id=guild_id, user_id=user_id, now=now)
        except Exception:
            log.exception("回退 AI 配額失敗", extra={"guild_id": guild_id})
