"""End-to-end orchestration of website extraction, LLM analysis and caching."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.config import Settings
from app.exceptions import AppError
from app.schemas import (
    AnalysisMetadata,
    ExtractionMetadata,
    LinkAnalysisResponse,
    LLMAnalysisPayload,
    LLMRunMetadata,
)
from app.services.cache import AnalysisCache, cache_key
from app.services.competitor_service import normalise_analysis
from app.services.llm_service import LLMService, LLMServiceError
from app.services.prompts import ANALYSIS_JSON_SCHEMA, SYSTEM_PROMPT, build_user_prompt
from app.services.website_extractor import WebsiteExtractionError, WebsiteExtractor
from app.utils.text import dedupe_preserve_order
from app.utils.validators import URLValidationError, validate_public_url

logger = logging.getLogger(__name__)

PROMPT_VERSION = "2026-11-23.v1"


class AnalysisService:
    def __init__(
        self,
        settings: Settings,
        extractor: WebsiteExtractor | None = None,
        llm: LLMService | None = None,
        cache: AnalysisCache | None = None,
    ):
        self.settings = settings
        self.extractor = extractor or WebsiteExtractor(settings)
        self.llm = llm or LLMService(settings)
        self.cache = cache or AnalysisCache(settings)

    async def analyze(self, url: str, *, request_id: str) -> LinkAnalysisResponse:
        try:
            validated = await validate_public_url(
                url, allow_private_hosts=self.settings.allow_private_hosts
            )
        except URLValidationError as exc:
            raise AppError(
                exc.message, code=exc.code, status_code=exc.status_code
            ) from exc

        key = cache_key(
            url=validated.url,
            provider=self.settings.llm_provider,
            model=self.settings.llm_model,
            prompt_version=PROMPT_VERSION,
            max_input_chars=self.settings.max_input_chars,
        )
        cached = await self.cache.get(key)
        if cached is not None:
            logger.info("Cache hit url=%s request_id=%s", validated.url, request_id)
            try:
                response = LinkAnalysisResponse.model_validate(cached)
            except Exception:
                logger.warning("Cached payload was invalid; regenerating.", exc_info=True)
            else:
                response.request_id = request_id
                response.metadata.llm.cached = True
                response.warnings = dedupe_preserve_order(
                    response.warnings + ["Result served from the analysis cache."]
                )
                return response

        try:
            extracted = await self.extractor.extract(validated.url)
        except URLValidationError as exc:
            raise AppError(
                exc.message, code=exc.code, status_code=exc.status_code
            ) from exc
        except WebsiteExtractionError as exc:
            raise AppError(
                exc.message,
                code=exc.code,
                status_code=exc.status_code,
                details=exc.details,
            ) from exc
        except Exception as exc:
            logger.exception(
                "Unexpected extraction failure request_id=%s url=%s", request_id, validated.url
            )
            raise AppError(
                "The website could not be analysed because extraction failed unexpectedly.",
                code="website_error",
                status_code=502,
            ) from exc

        if extracted.words < 120:
            logger.info(
                "Thin content url=%s words=%s request_id=%s",
                validated.url,
                extracted.words,
                request_id,
            )

        user_prompt = build_user_prompt(
            extracted, max_context_chars=self.settings.max_input_chars
        )
        page_excerpt = extracted.to_prompt_context(
            min(self.settings.max_input_chars, 6500)
        )

        try:
            payload, run = await self.llm.generate_structured(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                schema=ANALYSIS_JSON_SCHEMA,
                validator=LLMAnalysisPayload.model_validate,
                page_excerpt=page_excerpt,
            )
        except LLMServiceError as exc:
            raise AppError(
                exc.message,
                code=exc.code,
                status_code=exc.status_code,
                details=exc.details or None,
            ) from exc
        except Exception as exc:
            logger.exception(
                "Unexpected LLM failure request_id=%s url=%s", request_id, validated.url
            )
            raise AppError(
                "The LLM request failed unexpectedly.",
                code="llm_error",
                status_code=502,
            ) from exc

        payload, normalisation_warnings = normalise_analysis(payload, extracted)

        warnings = list(extracted.warnings) + normalisation_warnings
        if run.fallback_used:
            warnings.append(
                f"The primary LLM failed; the configured fallback ({run.provider}/{run.model}) "
                "produced this result."
            )
        if run.repair_attempts:
            warnings.append(
                f"The model output required {run.repair_attempts} structural repair attempt(s)."
            )
        if run.token_usage_estimated:
            warnings.append(
                "Token usage was estimated because the provider did not return complete usage metadata."
            )
        warnings = dedupe_preserve_order(warnings)

        extraction_metadata = ExtractionMetadata(
            requested_url=url,
            final_url=extracted.final_url,
            status_code=extracted.status_code,
            title=extracted.title,
            meta_description=extracted.meta_description,
            word_count=extracted.words,
            content_chars=len(extracted.content),
            truncated=extracted.truncated,
            fetched_at=extracted.fetched_at or datetime.now(UTC),
            warnings=extracted.warnings,
        )
        llm_metadata = LLMRunMetadata(
            provider=run.provider,
            model=run.model,
            input_tokens=run.input_tokens,
            output_tokens=run.output_tokens,
            total_tokens=run.input_tokens + run.output_tokens,
            estimated_cost_usd=run.estimated_cost_usd,
            pricing_source=run.pricing_source,
            pricing_note=run.pricing_note,
            latency_ms=run.latency_ms,
            cached=False,
            fallback_used=run.fallback_used,
            repair_attempts=run.repair_attempts,
            token_usage_estimated=run.token_usage_estimated,
        )
        response = LinkAnalysisResponse(
            success=True,
            request_id=request_id,
            website=extracted.final_url,
            brand=payload.brand,
            analysis=payload.analysis,
            metadata=AnalysisMetadata(
                extraction=extraction_metadata, llm=llm_metadata
            ),
            warnings=warnings,
        )

        await self.cache.set(key, response.model_dump(mode="json"))
        logger.info(
            "Analysis complete request_id=%s url=%s words=%s provider=%s model=%s "
            "input_tokens=%s output_tokens=%s cost_usd=%s latency_ms=%s",
            request_id,
            extracted.final_url,
            extracted.words,
            run.provider,
            run.model,
            run.input_tokens,
            run.output_tokens,
            run.estimated_cost_usd,
            run.latency_ms,
        )
        return response

    async def aclose(self) -> None:
        await self.cache.aclose()
