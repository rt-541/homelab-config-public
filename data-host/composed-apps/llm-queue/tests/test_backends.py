import httpx
import pytest

from app import backends


def test_registry_has_three_aliases():
    assert set(backends.known_aliases()) == {"fast", "background", "reasoning"}


def test_tier_mapping():
    assert backends.tier_for("fast") == "gpu"
    assert backends.tier_for("background") == "cpu"
    assert backends.tier_for("reasoning") == "cpu"


def test_unknown_alias_raises():
    with pytest.raises(KeyError):
        backends.get_backend("nope")


def test_registry_for_prompt_shape():
    reg = backends.registry_for_prompt()
    assert any(e["alias"] == "fast" for e in reg)
    e = reg[0]
    assert {"alias", "name", "backend", "strengths", "speed", "max_context_tokens", "notes"} <= set(e)


@pytest.mark.asyncio
async def test_run_posts_and_extracts_text():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = request.read()
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "hello world"}}]
        })

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        out = await backends.run("fast", "say hi", {"temperature": 0.1}, api_key="sk-test", client=client)
    assert out == "hello world"
    assert captured["url"].endswith("/chat/completions")
    assert b"temperature" in captured["json"]


@pytest.mark.asyncio
async def test_run_raises_on_no_choices():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(RuntimeError):
            await backends.run("fast", "hi", api_key="sk-test", client=client)


@pytest.mark.asyncio
async def test_run_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await backends.run("fast", "hi", api_key="sk-test", client=client)


@pytest.mark.asyncio
async def test_run_calls_gateway_with_caller_key(monkeypatch):
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"choices": [{"message": {"content": "hi"}}]}

    class FakeClient:
        def __init__(self, *a, **k):
            pass
        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["model"] = json["model"]
            return FakeResp()
        async def aclose(self):
            pass

    monkeypatch.setattr(backends, "GATEWAY_URL", "http://gw:4000")
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    out = await backends.run("fast", "hello", api_key="sk-good-1")
    assert out == "hi"
    assert captured["url"] == "http://gw:4000/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-good-1"
    assert captured["model"] == "fast"  # alias IS the gateway model-group name


@pytest.mark.asyncio
async def test_run_requires_api_key():
    with pytest.raises(RuntimeError):
        await backends.run("fast", "hello")  # no api_key -> must raise


@pytest.mark.asyncio
async def test_run_unknown_alias_raises():
    with pytest.raises(KeyError):
        await backends.run("nope", "hello", api_key="sk-good-1")
