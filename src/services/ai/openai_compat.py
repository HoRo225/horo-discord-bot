from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

from src.services.ai.base import AIProvider, AIUpstreamError, ChatMessage

log = logging.getLogger(__name__)


class OpenAICompatibleProvider(AIProvider):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout: float = 45,
        max_retries: int = 2,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.max_retries = max_retries
        self._session = session
        self._owns_session = session is None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
            self._owns_session = True
        return self._session

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        for attempt in range(self.max_retries + 1):
            try:
                async with self.session.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=self._headers(),
                    json=payload,
                ) as response:
                    raw = await response.text()
                    if response.status == 429 or response.status >= 500:
                        if attempt < self.max_retries:
                            retry_after = response.headers.get("Retry-After", "")
                            try:
                                delay = (
                                    min(float(retry_after), 5.0)
                                    if retry_after
                                    else 0.5 * 2**attempt
                                )
                            except ValueError:
                                delay = 0.5 * 2**attempt
                            await asyncio.sleep(delay)
                            continue
                        raise AIUpstreamError(f"AI 上游狀態碼 {response.status}", retryable=True)
                    if response.status >= 400:
                        raise AIUpstreamError(f"AI 上游狀態碼 {response.status}")
                    try:
                        data = json.loads(raw)
                    except (json.JSONDecodeError, TypeError) as exc:
                        raise AIUpstreamError("AI 上游回傳非 JSON 格式") from exc
                    if not isinstance(data, dict):
                        raise AIUpstreamError("AI 上游回傳格式不正確")
                    return data
            except (TimeoutError, aiohttp.ClientConnectionError) as exc:
                if attempt < self.max_retries:
                    await asyncio.sleep(0.5 * 2**attempt)
                    continue
                log.warning("AI 上游連線逾時或中斷：%s", type(exc).__name__)
                raise AIUpstreamError("AI 上游連線失敗", retryable=True) from exc
        raise AIUpstreamError("AI 上游重試失敗", retryable=True)

    async def list_models(self) -> list[str]:
        data = await self._request_json("GET", "/models")
        raw_models = data.get("data")
        if not isinstance(raw_models, list):
            raise AIUpstreamError("AI 模型清單格式不正確")
        models = sorted(
            {
                item.get("id")
                for item in raw_models
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
        )
        if not models:
            raise AIUpstreamError("AI 上游沒有可用模型")
        return models

    async def chat(self, *, model: str, messages: list[ChatMessage]) -> str:
        if not model:
            raise AIUpstreamError("未設定 AI 模型")
        data = await self._request_json(
            "POST",
            "/chat/completions",
            payload={
                "model": model,
                "messages": [
                    {"role": message.role, "content": message.content} for message in messages
                ],
                "stream": False,
            },
        )
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIUpstreamError("AI 回應缺少文字內容") from exc
        if not isinstance(content, str) or not content.strip():
            raise AIUpstreamError("AI 回應內容為空")
        return content.strip()

    async def close(self) -> None:
        if self._owns_session and self._session is not None and not self._session.closed:
            await self._session.close()
