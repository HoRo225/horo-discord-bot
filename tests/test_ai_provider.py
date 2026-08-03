from __future__ import annotations

import pytest
from aiohttp import web

from src.services.ai import AIUpstreamError, ChatMessage, OpenAICompatibleProvider


async def _serve(app: web.Application):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}/v1"


async def test_openai_compatible_models_chat_and_429_retry():
    calls = 0

    async def models(_request):
        return web.json_response({"data": [{"id": "z-model"}, {"id": "a-model"}]})

    async def chat(request):
        nonlocal calls
        calls += 1
        assert request.headers["Authorization"] == "Bearer secret"
        if calls == 1:
            return web.json_response({"error": "busy"}, status=429, headers={"Retry-After": "0"})
        payload = await request.json()
        assert payload["model"] == "a-model"
        return web.json_response({"choices": [{"message": {"content": "  測試成功  "}}]})

    app = web.Application()
    app.router.add_get("/v1/models", models)
    app.router.add_post("/v1/chat/completions", chat)
    runner, base_url = await _serve(app)
    provider = OpenAICompatibleProvider(
        base_url=base_url, api_key="secret", timeout=2, max_retries=1
    )
    try:
        assert await provider.list_models() == ["a-model", "z-model"]
        result = await provider.chat(model="a-model", messages=[ChatMessage("user", "你好")])
        assert result == "測試成功"
        assert calls == 2
    finally:
        await provider.close()
        await runner.cleanup()


async def test_openai_compatible_rejects_invalid_json_without_leaking_body():
    async def invalid(_request):
        return web.Response(text="secret-upstream-body", content_type="text/plain")

    app = web.Application()
    app.router.add_get("/v1/models", invalid)
    runner, base_url = await _serve(app)
    provider = OpenAICompatibleProvider(
        base_url=base_url, api_key="top-secret", timeout=2, max_retries=0
    )
    try:
        with pytest.raises(AIUpstreamError) as captured:
            await provider.list_models()
        assert "secret-upstream-body" not in str(captured.value)
        assert "top-secret" not in str(captured.value)
    finally:
        await provider.close()
        await runner.cleanup()
