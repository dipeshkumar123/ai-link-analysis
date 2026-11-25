"""Multi-provider LLM client with structured output, repair and fallback."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

import httpx
from pydantic import ValidationError

from app.config import Settings, estimate_tokens, pricing_for
from app.services.prompts import (
    REPAIR_SYSTEM_PROMPT,
    build_repair_prompt,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")
API_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)
JSON_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


class LLMServiceError(Exception):
    """A sanitised LLM failure safe to map to an API response."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "llm_error",
        status_code: int = 502,
        retryable: bool = False,
        upstream_status: int | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.retryable = retryable
        self.upstream_status = upstream_status
        self.details = details or {}


@dataclass
class ProviderResponse:
    text: str
    input_tokens: int
    output_tokens: int
    token_usage_estimated: bool = False


@dataclass
class RunStats:
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    token_usage_estimated: bool = False
    repair_attempts: int = 0
    pricing_sources: set[str] = field(default_factory=set)
    pricing_notes: list[str] = field(default_factory=list)

    def add_call(
        self,
        *,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        estimated: bool,
    ) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.token_usage_estimated = self.token_usage_estimated or estimated
        pricing = pricing_for(provider, model)
        if pricing is None:
            self.pricing_sources.add("unavailable")
            return
        self.pricing_sources.add(pricing.source)
        self.estimated_cost_usd += (
            input_tokens / 1_000_000
        ) * pricing.input_per_million_usd + (
            output_tokens / 1_000_000
        ) * pricing.output_per_million_usd
        if pricing.note and pricing.note not in self.pricing_notes:
            self.pricing_notes.append(pricing.note)


@dataclass
class LLMRun:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    pricing_source: str | None
    pricing_note: str | None
    latency_ms: int
    fallback_used: bool
    repair_attempts: int
    token_usage_estimated: bool


class LLMService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._semaphore = asyncio.Semaphore(2)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def configuration_warnings(self) -> list[str]:
        warnings: list[str] = []
        targets = self._targets()
        if not targets:
            warnings.append("No LLM provider is configured.")
            return warnings
        for provider, model in targets:
            if provider != "ollama" and not self.settings.api_key_for(provider):
                warnings.append(f"No API key configured for provider '{provider}' (model '{model}').")
        return warnings

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        validator: Callable[[dict[str, Any]], T],
        page_excerpt: str,
    ) -> tuple[T, LLMRun]:
        started = time.perf_counter()
        targets = self._targets()
        if not targets:
            raise LLMServiceError(
                "No LLM provider is configured. Set LLM_PROVIDER and the provider API key.",
                code="llm_not_configured",
                status_code=503,
            )

        stats = RunStats()
        last_error: LLMServiceError | None = None
        for index, (provider, model) in enumerate(targets):
            try:
                async with self._semaphore:
                    result = await self._attempt_provider(
                        provider=provider,
                        model=model,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        schema=schema,
                        validator=validator,
                        page_excerpt=page_excerpt,
                        stats=stats,
                    )
                pricing = pricing_for(provider, model)
                latency_ms = int((time.perf_counter() - started) * 1000)
                pricing_note = "; ".join(stats.pricing_notes) or None
                if len(stats.pricing_sources) > 1:
                    pricing_note = (
                        (pricing_note + "; " if pricing_note else "")
                        + "Cost sums list-price estimates across all attempt(s)."
                    )
                return result, LLMRun(
                    provider=provider,
                    model=model,
                    input_tokens=stats.input_tokens,
                    output_tokens=stats.output_tokens,
                    estimated_cost_usd=round(stats.estimated_cost_usd, 8),
                    pricing_source=pricing.source if pricing else None,
                    pricing_note=pricing_note,
                    latency_ms=latency_ms,
                    fallback_used=index > 0,
                    repair_attempts=stats.repair_attempts,
                    token_usage_estimated=stats.token_usage_estimated,
                )
            except LLMServiceError as exc:
                last_error = exc
                logger.warning(
                    "LLM attempt failed provider=%s model=%s code=%s upstream=%s message=%s",
                    provider,
                    model,
                    exc.code,
                    exc.upstream_status,
                    exc.message,
                )
                if index + 1 < len(targets):
                    logger.info("Trying configured LLM fallback.")
                continue

        if last_error is not None:
            raise last_error
        raise LLMServiceError(
            "The LLM request failed.", code="llm_error", status_code=502
        )

    # ------------------------------------------------------------------
    # Attempt + repair loop
    # ------------------------------------------------------------------
    def _targets(self) -> list[tuple[str, str]]:
        primary = (self.settings.llm_provider, self.settings.llm_model)
        targets = [primary]
        if self.settings.llm_fallback_provider and self.settings.llm_fallback_model:
            fallback = (
                self.settings.llm_fallback_provider,
                self.settings.llm_fallback_model,
            )
            if fallback != primary:
                targets.append(fallback)
        return targets

    async def _attempt_provider(
        self,
        *,
        provider: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        validator: Callable[[dict[str, Any]], T],
        page_excerpt: str,
        stats: RunStats,
    ) -> T:
        response = await self._call_provider(
            provider=provider,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=schema,
        )
        stats.add_call(
            provider=provider,
            model=model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            estimated=response.token_usage_estimated,
        )

        parsed, error = self._parse_and_validate(response.text, validator)
        if parsed is not None:
            return parsed

        logger.info(
            "LLM output validation failed provider=%s model=%s error=%s",
            provider,
            model,
            (error or "unknown")[:800],
        )
        for _ in range(self.settings.llm_max_retries):
            stats.repair_attempts += 1
            logger.info("Repairing invalid LLM output provider=%s model=%s", provider, model)
            repair_prompt = build_repair_prompt(
                previous_output=response.text,
                validation_error=error or "Unknown validation failure",
                page_excerpt=page_excerpt,
            )
            response = await self._call_provider(
                provider=provider,
                model=model,
                system_prompt=REPAIR_SYSTEM_PROMPT,
                user_prompt=repair_prompt,
                schema=schema,
            )
            stats.add_call(
                provider=provider,
                model=model,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                estimated=response.token_usage_estimated,
            )
            parsed, error = self._parse_and_validate(response.text, validator)
            if parsed is not None:
                return parsed

        raise LLMServiceError(
            "The model returned an incomplete structured result. Please try again; if it "
            "persists, switch the configured model.",
            code="llm_invalid_output",
            status_code=502,
            retryable=True,
            details={"validation_error": (error or "unknown")[:600]},
        )

    def _parse_and_validate(
        self, text: str, validator: Callable[[dict[str, Any]], T]
    ) -> tuple[T | None, str | None]:
        try:
            payload = self._parse_json(text)
        except ValueError as exc:
            return None, f"Invalid JSON: {exc}"
        try:
            return validator(payload), None
        except ValidationError as exc:
            return None, self._format_validation_error(exc)
        except Exception as exc:  # defensive: validator should raise ValidationError
            return None, f"Validation failed: {exc}"[:1200]

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        cleaned = JSON_FENCE_RE.sub("", text.strip())
        decoder = json.JSONDecoder()
        for index, char in enumerate(cleaned):
            if char != "{":
                continue
            try:
                value, _ = decoder.raw_decode(cleaned[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        raise ValueError("no JSON object found in the model response")

    @staticmethod
    def _format_validation_error(exc: ValidationError) -> str:
        parts: list[str] = []
        for error in exc.errors()[:15]:
            location = ".".join(str(item) for item in error.get("loc", ()))
            message = error.get("msg", "invalid value")
            parts.append(f"{location}: {message}")
        return "; ".join(parts)[:1500]

    # ------------------------------------------------------------------
    # Provider dispatch
    # ------------------------------------------------------------------
    async def _call_provider(
        self,
        *,
        provider: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
    ) -> ProviderResponse:
        if provider == "gemini":
            return await self._call_gemini(model, system_prompt, user_prompt)
        if provider == "anthropic":
            return await self._call_anthropic(model, system_prompt, user_prompt)
        return await self._call_openai_compatible(
            provider, model, system_prompt, user_prompt, schema
        )

    def _require_key(self, provider: str) -> str | None:
        if provider == "ollama":
            return None
        key = self.settings.api_key_for(provider)
        if not key:
            raise LLMServiceError(
                f"No API key is configured for LLM provider '{provider}'.",
                code="llm_not_configured",
                status_code=503,
            )
        return key

    def _openai_compatible_url(self, provider: str) -> str:
        return f"{self.settings.base_url_for(provider)}/chat/completions"

    async def _call_openai_compatible(
        self,
        provider: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
    ) -> ProviderResponse:
        key = self._require_key(provider)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": API_USER_AGENT,
        }
        if key:
            headers["Authorization"] = f"Bearer {key}"
        if provider == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/dipeshkumar123/ai-link-analysis"
            headers["X-Title"] = "AI Link Analysis"

        supports_schema = not (provider in {"deepseek", "ollama"} or model.startswith("qwen/"))
        response_format: dict[str, Any]
        if supports_schema:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "link_analysis",
                    "strict": True,
                    "schema": schema,
                },
            }
        else:
            response_format = {"type": "json_object"}

        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "response_format": response_format,
        }
        if provider == "openai":
            body["max_completion_tokens"] = self.settings.llm_max_output_tokens
        elif provider == "groq":
            body["max_completion_tokens"] = self.settings.llm_max_output_tokens
            body["temperature"] = self.settings.llm_temperature
        else:
            body["max_tokens"] = self.settings.llm_max_output_tokens
            body["temperature"] = self.settings.llm_temperature

        if provider == "groq" and model.startswith("openai/gpt-oss"):
            body["reasoning_effort"] = self.settings.llm_reasoning_effort

        try:
            data = await self._post_json(
                provider=provider,
                url=self._openai_compatible_url(provider),
                headers=headers,
                payload=body,
            )
        except LLMServiceError as exc:
            # Some OpenAI-compatible backends advertise JSON mode but reject schemas.
            if exc.upstream_status == 400 and response_format["type"] == "json_schema":
                logger.warning(
                    "Provider %s rejected response_format json_schema; retrying with json_object.",
                    provider,
                )
                body["response_format"] = {"type": "json_object"}
                data = await self._post_json(
                    provider=provider,
                    url=self._openai_compatible_url(provider),
                    headers=headers,
                    payload=body,
                )
            else:
                raise

        return self._parse_openai_response(data, system_prompt, user_prompt)

    def _parse_openai_response(
        self, data: dict[str, Any], system_prompt: str, user_prompt: str
    ) -> ProviderResponse:
        choices = data.get("choices") or []
        if not choices:
            raise LLMServiceError(
                "The LLM provider returned no completion choices.",
                code="llm_empty_response",
                status_code=502,
                retryable=True,
            )
        choice = choices[0] or {}
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(
                str(part.get("text", "")) if isinstance(part, dict) else str(part)
                for part in content
            )
        if not isinstance(content, str) or not content.strip():
            raise LLMServiceError(
                "The LLM returned an empty response.",
                code="llm_empty_response",
                status_code=502,
                retryable=True,
            )
        finish_reason = str(choice.get("finish_reason") or "")
        if finish_reason in {"length", "max_tokens"}:
            raise LLMServiceError(
                "The LLM response was cut off before the JSON was complete. "
                "Reduce the page excerpt or raise LLM_MAX_OUTPUT_TOKENS.",
                code="llm_output_truncated",
                status_code=502,
                retryable=True,
            )
        usage = data.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        output_tokens = int(
            usage.get("completion_tokens") or usage.get("output_tokens") or 0
        )
        estimated = False
        if not input_tokens:
            input_tokens = estimate_tokens(system_prompt + "\n" + user_prompt)
            estimated = True
        if not output_tokens:
            output_tokens = estimate_tokens(content)
            estimated = True
        return ProviderResponse(
            text=content.strip(),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            token_usage_estimated=estimated,
        )

    async def _call_gemini(
        self, model: str, system_prompt: str, user_prompt: str
    ) -> ProviderResponse:
        key = self._require_key("gemini")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": API_USER_AGENT,
            "x-goog-api-key": key or "",
        }
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": self.settings.llm_temperature,
                "maxOutputTokens": self.settings.llm_max_output_tokens,
                "responseMimeType": "application/json",
            },
        }
        url = (
            f"{self.settings.gemini_base_url.rstrip('/')}/v1beta/models/"
            f"{model}:generateContent"
        )
        data = await self._post_json(
            provider="gemini", url=url, headers=headers, payload=payload
        )

        candidates = data.get("candidates") or []
        if not candidates:
            feedback = data.get("promptFeedback") or {}
            reason = feedback.get("blockReason") or "no candidates returned"
            raise LLMServiceError(
                f"Gemini returned no content ({reason}). The page or prompt may have been blocked.",
                code="llm_empty_response",
                status_code=502,
                retryable=False,
                details={"block_reason": str(reason)[:200]},
            )
        candidate = candidates[0] or {}
        parts = (candidate.get("content") or {}).get("parts") or []
        texts: list[str] = []
        for part in parts:
            if not isinstance(part, dict) or part.get("thought") is True:
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text)
        content = "\n".join(texts).strip()
        finish_reason = str(candidate.get("finishReason") or "")
        if finish_reason in {"MAX_TOKENS", "SAFETY", "RECITATION"}:
            raise LLMServiceError(
                f"Gemini stopped before completing the JSON (finishReason={finish_reason}).",
                code="llm_output_truncated"
                if finish_reason == "MAX_TOKENS"
                else "llm_blocked",
                status_code=502,
                retryable=finish_reason == "MAX_TOKENS",
            )
        if not content:
            raise LLMServiceError(
                "Gemini returned an empty response.",
                code="llm_empty_response",
                status_code=502,
                retryable=True,
            )
        usage = data.get("usageMetadata") or {}
        input_tokens = int(usage.get("promptTokenCount") or 0)
        output_tokens = int(usage.get("candidatesTokenCount") or 0)
        thoughts = int(usage.get("thoughtsTokenCount") or 0)
        if thoughts:
            output_tokens += thoughts
        total = int(usage.get("totalTokenCount") or 0)
        if total and not output_tokens:
            output_tokens = max(0, total - input_tokens)
        estimated = False
        if not input_tokens:
            input_tokens = estimate_tokens(system_prompt + "\n" + user_prompt)
            estimated = True
        if not output_tokens:
            output_tokens = estimate_tokens(content)
            estimated = True
        return ProviderResponse(
            text=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            token_usage_estimated=estimated,
        )

    async def _call_anthropic(
        self, model: str, system_prompt: str, user_prompt: str
    ) -> ProviderResponse:
        key = self._require_key("anthropic")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": API_USER_AGENT,
            "x-api-key": key or "",
            "anthropic-version": self.settings.anthropic_version,
        }
        payload = {
            "model": model,
            "max_tokens": self.settings.llm_max_output_tokens,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": user_prompt + "\n\nReturn only the JSON object.",
                }
            ],
        }
        data = await self._post_json(
            provider="anthropic",
            url=f"{self.settings.anthropic_base_url.rstrip('/')}/v1/messages",
            headers=headers,
            payload=payload,
        )
        blocks = data.get("content") or []
        texts = [
            str(block.get("text", ""))
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        content = "\n".join(texts).strip()
        stop_reason = str(data.get("stop_reason") or "")
        if stop_reason == "max_tokens":
            raise LLMServiceError(
                "Anthropic stopped before completing the JSON (max_tokens).",
                code="llm_output_truncated",
                status_code=502,
                retryable=True,
            )
        if not content:
            raise LLMServiceError(
                "Anthropic returned an empty response.",
                code="llm_empty_response",
                status_code=502,
                retryable=True,
            )
        usage = data.get("usage") or {}
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        estimated = False
        if not input_tokens:
            input_tokens = estimate_tokens(system_prompt + "\n" + user_prompt)
            estimated = True
        if not output_tokens:
            output_tokens = estimate_tokens(content)
            estimated = True
        return ProviderResponse(
            text=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            token_usage_estimated=estimated,
        )

    # ------------------------------------------------------------------
    # HTTP transport with bounded retries
    # ------------------------------------------------------------------
    async def _post_json(
        self,
        *,
        provider: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        attempts = max(1, self.settings.llm_max_retries + 1)
        timeout = httpx.Timeout(self.settings.llm_timeout_seconds, connect=10.0)
        async with httpx.AsyncClient(
            timeout=timeout, headers=headers, follow_redirects=False
        ) as client:
            for attempt in range(attempts):
                try:
                    response = await client.post(url, json=payload)
                except httpx.TimeoutException as exc:
                    if attempt + 1 < attempts:
                        await asyncio.sleep(1.0)
                        continue
                    raise LLMServiceError(
                        f"{provider} did not respond before the timeout.",
                        code="llm_timeout",
                        status_code=504,
                        retryable=True,
                    ) from exc
                except httpx.HTTPError as exc:
                    if attempt + 1 < attempts:
                        await asyncio.sleep(1.0)
                        continue
                    raise LLMServiceError(
                        f"{provider} could not be reached.",
                        code="llm_unavailable",
                        status_code=502,
                        retryable=True,
                        details={"reason": exc.__class__.__name__},
                    ) from exc

                if response.status_code < 400:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise LLMServiceError(
                            f"{provider} returned a non-JSON API response.",
                            code="llm_bad_response",
                            status_code=502,
                            retryable=True,
                        ) from exc

                error_message = self._error_message(response)
                if response.status_code == 429:
                    if attempt + 1 < attempts:
                        await asyncio.sleep(self._retry_after_seconds(response))
                        continue
                    raise LLMServiceError(
                        f"{provider} rate limit reached. Try again shortly.",
                        code="llm_rate_limited",
                        status_code=503,
                        retryable=True,
                        upstream_status=429,
                        details={"provider_message": error_message},
                    )
                if response.status_code >= 500:
                    if attempt + 1 < attempts:
                        await asyncio.sleep(1.0 * (attempt + 1))
                        continue
                    raise LLMServiceError(
                        f"{provider} is temporarily unavailable.",
                        code="llm_unavailable",
                        status_code=502,
                        retryable=True,
                        upstream_status=response.status_code,
                        details={"provider_message": error_message},
                    )
                if response.status_code in {401, 403}:
                    raise LLMServiceError(
                        f"{provider} authentication failed. Check the server's API key.",
                        code="llm_auth_error",
                        status_code=502,
                        retryable=False,
                        upstream_status=response.status_code,
                        details={"provider_message": error_message},
                    )
                if response.status_code == 404:
                    raise LLMServiceError(
                        f"{provider} model or endpoint was not found. "
                        "Check LLM_MODEL and the provider base URL.",
                        code="llm_model_not_found",
                        status_code=502,
                        retryable=False,
                        upstream_status=404,
                        details={"provider_message": error_message},
                    )
                raise LLMServiceError(
                    f"{provider} rejected the request: {error_message}",
                    code="llm_bad_request",
                    status_code=502,
                    retryable=False,
                    upstream_status=response.status_code,
                    details={"provider_message": error_message},
                )

        raise LLMServiceError(
            f"{provider} request failed.", code="llm_error", status_code=502
        )

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float:
        raw = response.headers.get("retry-after", "")
        try:
            return min(max(float(raw), 1.0), 8.0)
        except (TypeError, ValueError):
            return 2.0

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            data = response.json()
        except ValueError:
            return response.text.strip()[:400] or "no error message"
        error = data.get("error", data)
        if isinstance(error, dict):
            message = error.get("message") or error.get("detail") or error
        else:
            message = error
        return str(message)[:400]
