from __future__ import annotations

import asyncio

import pytest

import app.services.analysis_service as analysis_module
from app.config import Settings
from app.main import RateLimiter
from app.schemas import LLMAnalysisPayload
from app.services.analysis_service import AnalysisService
from app.services.llm_service import LLMRun, LLMServiceError
from app.services.website_extractor import WebsiteExtractionError, parse_website_html
from app.utils.validators import ValidatedURL

from .conftest import LLM_PAYLOAD, SAMPLE_HTML


def _extracted():
    return parse_website_html(
        SAMPLE_HTML,
        requested_url="https://www.dxora.com",
        final_url="https://www.dxora.com/",
        settings=Settings(),
    )


async def _fake_validate(url: str, *, allow_private_hosts: bool = False) -> ValidatedURL:
    from urllib.parse import urlsplit

    parsed = urlsplit(url)
    return ValidatedURL(
        url=url,
        scheme=parsed.scheme,
        hostname=parsed.hostname or "example.com",
        port=parsed.port,
    )


def _fake_llm_run(**_kwargs) -> tuple[LLMAnalysisPayload, LLMRun]:
    payload = LLMAnalysisPayload.model_validate(LLM_PAYLOAD)
    return payload, LLMRun(
        provider="groq",
        model="openai/gpt-oss-120b",
        input_tokens=1200,
        output_tokens=1800,
        estimated_cost_usd=0.00126,
        pricing_source="https://console.groq.com/docs/models",
        pricing_note=None,
        latency_ms=1250,
        fallback_used=False,
        repair_attempts=0,
        token_usage_estimated=False,
    )


def _patch_service(
    monkeypatch: pytest.MonkeyPatch,
    client,
    *,
    extract=None,
    llm=None,
) -> None:
    monkeypatch.setattr(analysis_module, "validate_public_url", _fake_validate)
    service = client.app.state.analysis_service
    if extract is not None:
        monkeypatch.setattr(service.extractor, "extract", extract)
    if llm is not None:
        monkeypatch.setattr(service.llm, "generate_structured", llm)


def test_link_analysis_success(client, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def fake_extract(url: str):
        captured["extract_url"] = url
        return _extracted()

    async def fake_llm(**kwargs):
        captured["prompt"] = kwargs["system_prompt"]
        captured["user_prompt"] = kwargs["user_prompt"]
        return _fake_llm_run()

    _patch_service(monkeypatch, client, extract=fake_extract, llm=fake_llm)

    response = client.post(
        "/link-analysis",
        json={"url": "https://www.dxora.com"},
        headers={"X-Request-ID": "test-request-123"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["request_id"] == "test-request-123"
    assert response.headers["X-Request-ID"] == "test-request-123"
    assert body["brand"]["name"] == "Dxora Technologies"
    assert body["website"] == "https://www.dxora.com/"
    assert len(body["analysis"]["competitor_analysis"]["competitors"]) == 3
    assert len(body["analysis"]["target_search_queries"]) == 5
    assert len(body["analysis"]["top_services"]) == 5
    assert body["metadata"]["extraction"]["word_count"] > 100
    assert body["metadata"]["llm"]["provider"] == "groq"
    assert body["metadata"]["llm"]["cached"] is False
    assert any("search" in warning.lower() for warning in body["warnings"])
    assert captured["extract_url"] == "https://www.dxora.com"
    assert "Return JSON only" in captured["prompt"]


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("http://127.0.0.1/admin", "blocked_ip"),
        ("http://localhost:8000", "blocked_host"),
        ("ftp://example.com/file", "unsupported_scheme"),
        ("https://user:password@example.com", "credentials_not_allowed"),
    ],
)
def test_rejects_invalid_or_unsafe_urls(client, url: str, code: str) -> None:
    response = client.post("/link-analysis", json={"url": url})
    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == code


def test_missing_url_is_a_validation_error(client) -> None:
    response = client.post("/link-analysis", json={})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_website_failure_maps_to_504(client, monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing_extract(url: str):
        raise WebsiteExtractionError(
            "The website did not respond in time.",
            code="website_timeout",
            status_code=504,
        )

    _patch_service(monkeypatch, client, extract=failing_extract)
    response = client.post("/link-analysis", json={"url": "https://slow.example"})
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "website_timeout"


def test_llm_failure_maps_to_502(client, monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing_llm(**_kwargs):
        raise LLMServiceError(
            "The model provider is temporarily unavailable.",
            code="llm_error",
            status_code=502,
        )

    _patch_service(monkeypatch, client, llm=failing_llm)
    response = client.post("/link-analysis", json={"url": "https://example.com"})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "llm_error"


def test_cache_hit_skips_extraction(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    settings = Settings(
        cache_enabled=True,
        cache_path=str(tmp_path / "cache.sqlite3"),
        cache_ttl_seconds=3600,
    )
    monkeypatch.setattr(analysis_module, "validate_public_url", _fake_validate)
    service = AnalysisService(settings)
    call_count = {"llm": 0, "extract": 0}

    async def fake_extract(url: str):
        call_count["extract"] += 1
        return _extracted()

    async def fake_llm(**_kwargs):
        call_count["llm"] += 1
        return _fake_llm_run()

    monkeypatch.setattr(service.extractor, "extract", fake_extract)
    monkeypatch.setattr(service.llm, "generate_structured", fake_llm)

    async def run():
        first = await service.analyze("https://www.dxora.com", request_id="first")
        second = await service.analyze("https://www.dxora.com", request_id="second")
        await service.aclose()
        return first, second

    first, second = asyncio.run(run())
    assert first.metadata.llm.cached is False
    assert second.metadata.llm.cached is True
    assert second.request_id == "second"
    assert call_count == {"extract": 1, "llm": 1}
    assert any("cache" in warning.lower() for warning in second.warnings)


def test_rate_limiter_blocks_after_limit() -> None:
    async def run() -> None:
        limiter = RateLimiter(1)
        assert (await limiter.check("203.0.113.5"))[0] is True
        allowed, retry_after = await limiter.check("203.0.113.5")
        assert allowed is False
        assert retry_after >= 1

    asyncio.run(run())


def test_rate_limit_response(client, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_extract(url: str):
        return _extracted()

    async def fake_llm(**_kwargs):
        return _fake_llm_run()

    _patch_service(monkeypatch, client, extract=fake_extract, llm=fake_llm)
    client.app.state.rate_limiter = RateLimiter(1)

    first = client.post("/link-analysis", json={"url": "https://www.dxora.com"})
    assert first.status_code == 200
    second = client.post("/link-analysis", json={"url": "https://www.dxora.com"})
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limited"
    assert second.headers["Retry-After"]


def test_meta_endpoints(client) -> None:
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200
    health = client.get("/health").json()
    assert health["status"] == "ok"
    api = client.get("/api").json()
    assert api["endpoint"] == "POST /link-analysis"
    page = client.get("/")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert "LinkLens" in page.text