"""Application configuration and LLM pricing metadata."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal[
    "groq",
    "openai",
    "gemini",
    "anthropic",
    "deepseek",
    "openrouter",
    "ollama",
]


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "AI Link Analysis API"
    app_version: str = "1.0.0"
    environment: str = "development"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 4000
    cors_origins: str = "*"

    # LLM selection
    llm_provider: ProviderName = "groq"
    llm_model: str = "openai/gpt-oss-120b"
    llm_fallback_provider: ProviderName | None = None
    llm_fallback_model: str | None = None
    llm_timeout_seconds: float = 90.0
    llm_temperature: float = 0.2
    llm_max_output_tokens: int = 3500
    llm_reasoning_effort: str = "low"
    llm_max_retries: int = 1

    # Provider credentials
    groq_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    deepseek_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    ollama_base_url: str = "http://localhost:11434/v1"

    # Provider endpoints
    groq_base_url: str = "https://api.groq.com/openai/v1"
    openai_base_url: str = "https://api.openai.com/v1"
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    gemini_base_url: str = "https://generativelanguage.googleapis.com"
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_version: str = "2023-06-01"

    # Website extraction
    fetch_timeout_seconds: float = 15.0
    max_page_bytes: int = 2_000_000
    max_redirects: int = 5
    max_input_chars: int = 6500
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0 Safari/537.36 LinkAnalysisBot/1.0"
    )
    allow_private_hosts: bool = False

    # API behaviour
    rate_limit_per_hour: int = 60
    cache_enabled: bool = True
    cache_ttl_seconds: int = 86_400
    cache_path: str = ""

    @field_validator("llm_fallback_provider", "llm_fallback_model", mode="before")
    @classmethod
    def empty_string_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("llm_reasoning_effort")
    @classmethod
    def validate_reasoning_effort(cls, value: str) -> str:
        allowed = {"low", "medium", "high"}
        normalised = value.strip().lower()
        if normalised not in allowed:
            raise ValueError(f"llm_reasoning_effort must be one of: {', '.join(sorted(allowed))}")
        return normalised

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def api_key_for(self, provider: str) -> str | None:
        mapping = {
            "groq": self.groq_api_key,
            "gemini": self.gemini_api_key,
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
            "deepseek": self.deepseek_api_key,
            "openrouter": self.openrouter_api_key,
        }
        secret = mapping.get(provider)
        if secret is None:
            return None
        value = secret.get_secret_value().strip()
        return value or None

    def base_url_for(self, provider: str) -> str:
        mapping = {
            "groq": self.groq_base_url,
            "openai": self.openai_base_url,
            "gemini": self.gemini_base_url,
            "anthropic": self.anthropic_base_url,
            "deepseek": self.deepseek_base_url,
            "openrouter": self.openrouter_base_url,
            "ollama": self.ollama_base_url,
        }
        return mapping[provider].rstrip("/")

    def resolved_cache_path(self) -> Path:
        if self.cache_path.strip():
            return Path(self.cache_path).expanduser()
        if os.getenv("VERCEL"):
            # Vercel functions can only write inside /tmp.
            return Path(tempfile.gettempdir()) / "ai-link-analysis-cache.sqlite3"
        return Path("data") / "cache.sqlite3"


@dataclass(frozen=True)
class ModelPricing:
    provider: str
    model: str
    input_per_million_usd: float
    output_per_million_usd: float
    context_window: int
    json_support: str
    source: str
    note: str = ""


PRICING_AS_OF = "2026-11-23"

# List prices verified against official provider pages on 2026-11-23.
# Prices are USD per 1M tokens. See docs/LLM_RESEARCH.md for sources.
MODEL_PRICING: dict[tuple[str, str], ModelPricing] = {
    ("groq", "openai/gpt-oss-120b"): ModelPricing(
        provider="groq",
        model="openai/gpt-oss-120b",
        input_per_million_usd=0.15,
        output_per_million_usd=0.60,
        context_window=131_072,
        json_support="Strict JSON Schema (structured outputs)",
        source="https://console.groq.com/docs/models",
        note="Free tier observed at 8,000 tokens/minute and 1,000 requests/day on 2026-11-23.",
    ),
    ("groq", "openai/gpt-oss-20b"): ModelPricing(
        provider="groq",
        model="openai/gpt-oss-20b",
        input_per_million_usd=0.075,
        output_per_million_usd=0.30,
        context_window=131_072,
        json_support="Strict JSON Schema (structured outputs)",
        source="https://console.groq.com/docs/models",
        note="Free tier observed at 8,000 tokens/minute and 1,000 requests/day on 2026-11-23.",
    ),
    ("groq", "qwen/qwen3.8-27b"): ModelPricing(
        provider="groq",
        model="qwen/qwen3.8-27b",
        input_per_million_usd=0.80,
        output_per_million_usd=4.00,
        context_window=131_072,
        json_support="JSON mode",
        source="https://console.groq.com/docs/models",
    ),
    ("gemini", "gemini-3.5-flash-lite"): ModelPricing(
        provider="gemini",
        model="gemini-3.5-flash-lite",
        input_per_million_usd=0.30,
        output_per_million_usd=2.50,
        context_window=1_048_576,
        json_support="JSON Schema structured output",
        source="https://ai.google.dev/gemini-api/docs/pricing",
        note="Free tier available; grounding/search not included.",
    ),
    ("gemini", "gemini-3.8-flash"): ModelPricing(
        provider="gemini",
        model="gemini-3.8-flash",
        input_per_million_usd=0.75,
        output_per_million_usd=3.75,
        context_window=1_048_576,
        json_support="JSON Schema structured output",
        source="https://ai.google.dev/gemini-api/docs/pricing",
        note="Promotional price through 2026-12-31; doubles on 2027-01-01.",
    ),
    ("anthropic", "claude-haiku-5-5"): ModelPricing(
        provider="anthropic",
        model="claude-haiku-5-5",
        input_per_million_usd=0.10,
        output_per_million_usd=0.50,
        context_window=1_000_000,
        json_support="Structured JSON output (json_schema)",
        source="https://www.anthropic.com/pricing",
        note="Listed rate applies to prompts up to 100K tokens; higher above that.",
    ),
    ("anthropic", "claude-sonnet-5-5"): ModelPricing(
        provider="anthropic",
        model="claude-sonnet-5-5",
        input_per_million_usd=2.00,
        output_per_million_usd=10.00,
        context_window=1_000_000,
        json_support="Structured JSON output (json_schema)",
        source="https://www.anthropic.com/pricing",
    ),
    ("openai", "gpt-6-luna"): ModelPricing(
        provider="openai",
        model="gpt-6-luna",
        input_per_million_usd=0.10,
        output_per_million_usd=0.50,
        context_window=1_050_000,
        json_support="Structured Outputs (JSON Schema)",
        source="https://platform.openai.com/docs/pricing",
        note="Long-context (>272K input) rates are higher.",
    ),
    ("openai", "gpt-6.1-terra"): ModelPricing(
        provider="openai",
        model="gpt-6.1-terra",
        input_per_million_usd=1.00,
        output_per_million_usd=5.00,
        context_window=1_050_000,
        json_support="Structured Outputs (JSON Schema)",
        source="https://platform.openai.com/docs/pricing",
    ),
    ("deepseek", "deepseek-flash"): ModelPricing(
        provider="deepseek",
        model="deepseek-flash",
        input_per_million_usd=0.15,
        output_per_million_usd=0.60,
        context_window=1_000_000,
        json_support="JSON object mode (not schema-constrained)",
        source="https://api-docs.deepseek.com/quick_start/pricing",
        note="Off-peak price; peak is $0.30 input / $1.20 output.",
    ),
    ("deepseek", "deepseek-v4-pro"): ModelPricing(
        provider="deepseek",
        model="deepseek-v4-pro",
        input_per_million_usd=0.66,
        output_per_million_usd=1.98,
        context_window=1_000_000,
        json_support="JSON object mode (not schema-constrained)",
        source="https://api-docs.deepseek.com/quick_start/pricing",
        note="Off-peak price; peak is $1.32 input / $3.96 output.",
    ),
    ("openrouter", "z-ai/glm-5.3-flash"): ModelPricing(
        provider="openrouter",
        model="z-ai/glm-5.3-flash",
        input_per_million_usd=0.0399,
        output_per_million_usd=0.0784,
        context_window=1_048_576,
        json_support="Provider-dependent structured output",
        source="https://openrouter.ai/api/v1/models",
    ),
    ("ollama", "qwen2.5:7b"): ModelPricing(
        provider="ollama",
        model="qwen2.5:7b",
        input_per_million_usd=0.0,
        output_per_million_usd=0.0,
        context_window=32_768,
        json_support="JSON mode",
        source="https://github.com/ollama/ollama",
        note="Local inference; no API token charge.",
    ),
}


def pricing_for(provider: str, model: str) -> ModelPricing | None:
    return MODEL_PRICING.get((provider, model))


def estimate_tokens(text: str) -> int:
    """Rough token estimate used only when a provider omits usage metadata."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
