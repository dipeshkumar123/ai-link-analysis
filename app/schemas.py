"""Pydantic request/response models for the link analysis API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Platform = Literal["Google", "Facebook", "Instagram", "LinkedIn", "X"]
ServiceSource = Literal["website", "inferred"]

ALLOWED_PLATFORMS = {"Google", "Facebook", "Instagram", "LinkedIn", "X"}


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LinkAnalysisRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"url": "https://www.dxora.com"}}
    )

    url: str = Field(
        ...,
        min_length=4,
        max_length=2048,
        description="Public website URL to analyse (http or https).",
        examples=["https://www.dxora.com"],
    )

    @field_validator("url")
    @classmethod
    def strip_url(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("url must not be empty")
        return cleaned


class BrandInfo(BaseModel):
    name: str = Field(..., min_length=1, max_length=120, description="Brand name found on the site.")
    category: str = Field(..., min_length=2, max_length=160, description="Main business category.")
    summary: str = Field(
        ..., min_length=20, max_length=800, description="Short business overview based on the page."
    )
    website: str | None = Field(default=None, description="Canonical website URL.")
    main_offerings: list[str] = Field(
        default_factory=list, description="Main products or services stated on the site."
    )
    target_market: str | None = Field(default=None, description="Primary market/geography if evident.")
    evidence: list[str] = Field(
        default_factory=list,
        description="Short phrases from the website that support the brand summary.",
    )


class Competitor(BaseModel):
    brand_name: str = Field(..., min_length=1, max_length=120)
    website: str | None = Field(default=None, description="Competitor website if known.")
    overview: str = Field(..., min_length=10, max_length=500)
    main_service: str = Field(..., min_length=2, max_length=200)
    target_market: str = Field(..., min_length=2, max_length=200)
    key_strength: str = Field(..., min_length=5, max_length=300)
    weakness_or_gap: str = Field(..., min_length=5, max_length=300)
    opportunity_for_your_brand: str = Field(..., min_length=5, max_length=300)
    source: str = Field(
        default="AI-generated suggestion",
        description="Competitors are AI suggestions unless independently verified.",
    )
    confidence: Literal["low", "medium", "high"] = "medium"


class CompetitorAnalysis(BaseModel):
    brand_overview: str = Field(..., min_length=20, max_length=800)
    main_category: str = Field(..., min_length=2, max_length=160)
    main_products_services: list[str] = Field(default_factory=list, min_length=1)
    competitors: list[Competitor] = Field(default_factory=list)
    competitor_strengths: list[str] = Field(default_factory=list)
    competitor_weaknesses: list[str] = Field(default_factory=list)
    competitive_advantages: list[str] = Field(default_factory=list)
    market_positioning_opportunities: list[str] = Field(default_factory=list)
    disclaimer: str = Field(
        default=(
            "Competitor names and comparisons are AI-generated suggestions from the model's "
            "knowledge plus the submitted page. Verify them independently before commercial use."
        )
    )


class SearchQueryResult(BaseModel):
    query: str = Field(..., min_length=3, max_length=200)
    platforms: list[Platform] = Field(..., min_length=1, max_length=5)
    intent: str = Field(..., min_length=2, max_length=120)
    business_relevance: str = Field(..., min_length=5, max_length=300)
    target_audience: str = Field(..., min_length=3, max_length=200)

    @field_validator("platforms", mode="before")
    @classmethod
    def normalise_platforms(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            return value
        aliases = {
            "google search": "Google",
            "google": "Google",
            "facebook": "Facebook",
            "instagram": "Instagram",
            "linkedin": "LinkedIn",
            "x (twitter)": "X",
            "twitter": "X",
            "x": "X",
        }
        normalised: list[str] = []
        for item in value:
            key = str(item).strip().lower()
            canonical = aliases.get(key)
            if canonical and canonical not in normalised:
                normalised.append(canonical)
        return normalised


class SeoContentSuggestion(BaseModel):
    content_type: str = Field(..., min_length=2, max_length=80)
    title: str = Field(..., min_length=3, max_length=160)
    description: str = Field(..., min_length=10, max_length=500)
    target_keyword: str | None = Field(default=None, max_length=120)
    priority: Literal["high", "medium", "low"] = "medium"


class SeoImprovements(BaseModel):
    primary_keyword: str = Field(..., min_length=2, max_length=120)
    secondary_keywords: list[str] = Field(default_factory=list)
    long_tail_keywords: list[str] = Field(default_factory=list)
    business_keywords: list[str] = Field(default_factory=list)
    recommended_title: str = Field(..., min_length=10, max_length=100)
    title_rationale: str = Field(..., min_length=10, max_length=300)
    meta_description: str = Field(..., min_length=50, max_length=220)
    meta_description_rationale: str = Field(..., min_length=10, max_length=300)
    supporting_content: list[SeoContentSuggestion] = Field(default_factory=list)
    on_page_fixes: list[str] = Field(default_factory=list)


class Service(BaseModel):
    service_name: str = Field(..., min_length=2, max_length=150)
    description: str = Field(..., min_length=10, max_length=500)
    target_industry: str = Field(..., min_length=2, max_length=160)
    target_customer: str = Field(..., min_length=2, max_length=160)
    main_benefit: str = Field(..., min_length=5, max_length=300)
    source: ServiceSource = Field(
        default="website",
        description="'website' when directly stated; 'inferred' when recommended by the analyst.",
    )
    evidence: str | None = Field(
        default=None, max_length=300, description="Short supporting phrase from the page, if any."
    )

    @field_validator("source", mode="before")
    @classmethod
    def normalise_source(cls, value: Any) -> Any:
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"website", "inferred"}:
                return lowered
        return value


class AudienceSegment(BaseModel):
    audience: str = Field(..., min_length=2, max_length=160)
    business_type: str = Field(..., min_length=2, max_length=160)
    requirement: str = Field(..., min_length=5, max_length=300)
    customer_needs: str = Field(..., min_length=5, max_length=300)
    why_fit: str = Field(..., min_length=5, max_length=300)


class TargetAudience(BaseModel):
    primary_audience: list[AudienceSegment] = Field(..., min_length=2)
    secondary_audience: list[AudienceSegment] = Field(..., min_length=1)
    industries: list[str] = Field(..., min_length=1)
    business_types: list[str] = Field(..., min_length=1)
    customer_profiles: list[str] = Field(..., min_length=1)
    location_focus: str | None = Field(
        default=None, description="Geographic focus if stated; otherwise null."
    )
    customer_needs: list[str] = Field(..., min_length=1)
    customer_challenges: list[str] = Field(..., min_length=1)
    interests: list[str] = Field(..., min_length=1)
    recommended_segments: list[str] = Field(..., min_length=1)


class AnalysisSections(BaseModel):
    competitor_analysis: CompetitorAnalysis
    target_search_queries: list[SearchQueryResult] = Field(..., min_length=5)
    seo_improvements: SeoImprovements
    top_services: list[Service] = Field(..., min_length=5)
    target_audience: TargetAudience


class LLMAnalysisPayload(BaseModel):
    """Validated shape that the LLM must return."""

    brand: BrandInfo
    analysis: AnalysisSections


class ExtractionMetadata(BaseModel):
    requested_url: str
    final_url: str
    status_code: int
    title: str | None = None
    meta_description: str | None = None
    word_count: int = 0
    content_chars: int = 0
    truncated: bool = False
    fetched_at: datetime = Field(default_factory=_utcnow)
    warnings: list[str] = Field(default_factory=list)


class LLMRunMetadata(BaseModel):
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    pricing_source: str | None = None
    pricing_note: str | None = None
    latency_ms: int
    cached: bool = False
    fallback_used: bool = False
    repair_attempts: int = 0
    token_usage_estimated: bool = False


class AnalysisMetadata(BaseModel):
    extraction: ExtractionMetadata
    llm: LLMRunMetadata


class LinkAnalysisResponse(BaseModel):
    success: bool = True
    request_id: str
    website: str
    brand: BrandInfo
    analysis: AnalysisSections
    metadata: AnalysisMetadata
    warnings: list[str] = Field(default_factory=list)


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    success: bool = False
    request_id: str | None = None
    error: ErrorDetail


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    llm_provider: str
    llm_model: str
    cache_enabled: bool
