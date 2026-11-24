"""Post-processing and safety labelling for competitor and brand insights."""

from __future__ import annotations

from urllib.parse import urlsplit

from app.schemas import Competitor, LLMAnalysisPayload
from app.services.website_extractor import ExtractedWebsite
from app.utils.text import dedupe_preserve_order

COMPETITOR_DISCLAIMER = (
    "Competitor names, comparisons, strengths and gaps are AI-generated suggestions based on "
    "the submitted page and the model's public knowledge. They were not independently verified "
    "against paid market databases. Confirm any commercial claim before using it."
)


def _valid_optional_http_url(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    candidate = value.strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return candidate


def _brand_fallback(extracted: ExtractedWebsite) -> str:
    if extracted.site_name:
        return extracted.site_name.strip()
    if extracted.title:
        title = extracted.title.strip()
        for separator in (" | ", " - ", " — ", " · ", " :: "):
            if separator in title:
                first = title.split(separator, 1)[0].strip()
                if 2 <= len(first) <= 60:
                    return first
        if 2 <= len(title) <= 80:
            return title
    hostname = extracted.hostname.removeprefix("www.")
    stem = hostname.split(".")[0] if hostname else "Unknown brand"
    return stem.replace("-", " ").title() or "Unknown brand"


def _trim_seo(value: str, limit: int) -> tuple[str, bool]:
    cleaned = " ".join(value.split())
    if len(cleaned) <= limit:
        return cleaned, False
    candidate = cleaned[:limit]
    boundary = max(candidate.rfind(". "), candidate.rfind(" "), candidate.rfind(","))
    if boundary >= int(limit * 0.65):
        candidate = candidate[:boundary]
    return candidate.rstrip(" ,.;:-\u2013\u2014&|"), True


def normalise_analysis(
    payload: LLMAnalysisPayload, extracted: ExtractedWebsite
) -> tuple[LLMAnalysisPayload, list[str]]:
    """Normalise optional fields, enforce list lengths and add transparency warnings."""
    data = payload.model_copy(deep=True)
    warnings: list[str] = []

    brand = data.brand
    if not brand.name.strip():
        brand.name = _brand_fallback(extracted)
    if brand.website is not None and not brand.website.strip():
        brand.website = None
    if not brand.website:
        brand.website = extracted.final_url
    if brand.target_market is not None and not brand.target_market.strip():
        brand.target_market = None
    if not brand.main_offerings:
        brand.main_offerings = data.analysis.competitor_analysis.main_products_services[:6]
    brand.evidence = dedupe_preserve_order(brand.evidence)[:8]

    competitor_analysis = data.analysis.competitor_analysis
    cleaned_competitors = []
    seen_names: set[str] = set()
    own_name = brand.name.casefold()
    for competitor in competitor_analysis.competitors:
        name = competitor.brand_name.strip()
        key = name.casefold()
        if not name or key == own_name or key in seen_names:
            continue
        competitor.brand_name = name
        competitor.website = _valid_optional_http_url(competitor.website)
        if competitor.source not in {"AI-generated suggestion", "public knowledge"}:
            competitor.source = "AI-generated suggestion"
        seen_names.add(key)
        cleaned_competitors.append(competitor)
    competitor_analysis.competitors = cleaned_competitors[:5]
    if len(competitor_analysis.competitors) < 3:
        warnings.append(
            "Fewer than three reliable competitors were identified. Treat the competitor "
            "comparison as directional and verify it manually."
        )
    while len(competitor_analysis.competitors) < 3:
        index = len(competitor_analysis.competitors) + 1
        competitor_analysis.competitors.append(
            Competitor(
                brand_name=f"Unverified competitor candidate {index}",
                website=None,
                overview=(
                    "No verified competitor could be identified from the submitted page. "
                    "This labelled placeholder keeps the comparison structure complete."
                ),
                main_service="Unknown - verify manually",
                target_market="Unknown - verify manually",
                key_strength="Unknown - verify manually",
                weakness_or_gap="Unknown - verify manually",
                opportunity_for_your_brand="Verify this candidate before using the comparison.",
                source="AI-generated suggestion",
                confidence="low",
            )
        )
    if any(
        competitor.brand_name.startswith("Unverified competitor candidate")
        for competitor in competitor_analysis.competitors
    ):
        warnings.append(
            "Clearly labelled unverified placeholder competitor(s) were added because fewer "
            "than three reliable competitors could be identified."
        )
    competitor_analysis.disclaimer = COMPETITOR_DISCLAIMER
    competitor_analysis.main_products_services = dedupe_preserve_order(
        competitor_analysis.main_products_services
    )[:8]
    for field_name in (
        "competitor_strengths",
        "competitor_weaknesses",
        "competitive_advantages",
        "market_positioning_opportunities",
    ):
        values = dedupe_preserve_order(getattr(competitor_analysis, field_name))[:6]
        setattr(competitor_analysis, field_name, values)

    queries = data.analysis.target_search_queries[:5]
    for query in queries:
        query.platforms = list(dict.fromkeys(query.platforms))
    data.analysis.target_search_queries = queries

    services = data.analysis.top_services[:5]
    inferred = []
    for service in services:
        service.evidence = service.evidence.strip() if service.evidence else None
        service.source = service.source if service.source in {"website", "inferred"} else "website"
        if service.source == "inferred":
            inferred.append(service.service_name)
    data.analysis.top_services = services
    if inferred:
        warnings.append(
            "These services were inferred or expanded by the model rather than directly quoted "
            "from the page: " + ", ".join(inferred) + "."
        )

    seo = data.analysis.seo_improvements
    seo.recommended_title, title_trimmed = _trim_seo(seo.recommended_title, 60)
    seo.meta_description, meta_trimmed = _trim_seo(seo.meta_description, 155)
    if title_trimmed:
        warnings.append("The generated SEO title was trimmed to 60 characters.")
    if meta_trimmed:
        warnings.append("The generated meta description was trimmed to 155 characters.")
    seo.secondary_keywords = dedupe_preserve_order(seo.secondary_keywords)[:12]
    seo.long_tail_keywords = dedupe_preserve_order(seo.long_tail_keywords)[:12]
    seo.business_keywords = dedupe_preserve_order(seo.business_keywords)[:12]
    seo.supporting_content = seo.supporting_content[:8]
    seo.on_page_fixes = dedupe_preserve_order(seo.on_page_fixes)[:8]

    audience = data.analysis.target_audience
    if audience.location_focus is not None and not audience.location_focus.strip():
        audience.location_focus = None
    audience.primary_audience = audience.primary_audience[:5]
    audience.secondary_audience = audience.secondary_audience[:4]
    for field_name in (
        "industries",
        "business_types",
        "customer_profiles",
        "customer_needs",
        "customer_challenges",
        "interests",
        "recommended_segments",
    ):
        values = dedupe_preserve_order(getattr(audience, field_name))[:10]
        setattr(audience, field_name, values)
    if not audience.location_focus:
        warnings.append(
            "No explicit geographic focus was stated on the page; audience location was left blank."
        )

    warnings.append(
        "Competitor data is AI-generated. No Google, Facebook, Instagram, LinkedIn or X search "
        "volume data is reported because no official search-volume API was used."
    )
    return data, warnings
