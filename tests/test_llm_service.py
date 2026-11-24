from __future__ import annotations

from app.config import Settings, pricing_for
from app.schemas import LLMAnalysisPayload
from app.services.llm_service import LLMService, RunStats

from .conftest import LLM_PAYLOAD


def test_parse_json_accepts_fenced_output() -> None:
    text = '```json\n{"brand": {"name": "Acme"}}\n```'
    assert LLMService._parse_json(text) == {"brand": {"name": "Acme"}}


def test_parse_json_accepts_leading_prose() -> None:
    text = 'Here is the analysis:\n{"brand": {"name": "Acme"}}'
    assert LLMService._parse_json(text)["brand"]["name"] == "Acme"


def test_parse_and_validate_accepts_valid_payload() -> None:
    service = LLMService(Settings())
    parsed, error = service._parse_and_validate(
        __import__("json").dumps(LLM_PAYLOAD),
        LLMAnalysisPayload.model_validate,
    )
    assert parsed is not None
    assert error is None


def test_parse_and_validate_reports_validation_error() -> None:
    service = LLMService(Settings())
    parsed, error = service._parse_and_validate(
        '{"brand": {"name": "Acme"}}', LLMAnalysisPayload.model_validate
    )
    assert parsed is None
    assert error
    assert "analysis" in error


def test_run_stats_prices_groq_tokens() -> None:
    stats = RunStats()
    stats.add_call(
        provider="groq",
        model="openai/gpt-oss-120b",
        input_tokens=1_000_000,
        output_tokens=0,
        estimated=False,
    )
    assert stats.estimated_cost_usd == 0.15
    assert "https://console.groq.com/docs/models" in stats.pricing_sources


def test_unknown_model_has_no_pricing() -> None:
    assert pricing_for("groq", "unknown/model") is None


def test_targets_include_configured_fallback() -> None:
    settings = Settings(
        llm_fallback_provider="groq",
        llm_fallback_model="qwen/qwen3.8-27b",
    )
    targets = LLMService(settings)._targets()
    assert targets[0] == ("groq", "openai/gpt-oss-120b")
    assert ("groq", "qwen/qwen3.8-27b") in targets