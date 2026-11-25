from __future__ import annotations

from app.config import Settings
from app.schemas import LLMAnalysisPayload
from app.services.competitor_service import COMPETITOR_DISCLAIMER, normalise_analysis
from app.services.website_extractor import parse_website_html

from .conftest import SAMPLE_HTML


def _extracted():
    return parse_website_html(
        SAMPLE_HTML,
        requested_url="https://www.dxora.com/",
        final_url="https://www.dxora.com/",
        settings=Settings(),
    )


def test_normalise_adds_disclaimer_and_no_search_volume_warning(sample_payload) -> None:
    payload = LLMAnalysisPayload.model_validate(sample_payload)
    result, warnings = normalise_analysis(payload, _extracted())
    assert result.analysis.competitor_analysis.disclaimer == COMPETITOR_DISCLAIMER
    joined = " ".join(warnings)
    assert "AI-generated" in joined
    assert "search" in joined.lower()


def test_normalise_removes_own_brand_from_competitors(sample_payload) -> None:
    sample_payload["analysis"]["competitor_analysis"]["competitors"].append(
        {
            "brand_name": "Dxora Technologies",
            "website": None,
            "overview": "The submitted brand itself should not be a competitor.",
            "main_service": "Software development",
            "target_market": "Startups",
            "key_strength": "Direct page knowledge",
            "weakness_or_gap": "Not a competitor",
            "opportunity_for_your_brand": "Not applicable for the submitted brand",
            "source": "AI-generated suggestion",
            "confidence": "high",
        }
    )
    payload = LLMAnalysisPayload.model_validate(sample_payload)
    result, _ = normalise_analysis(payload, _extracted())
    names = [competitor.brand_name.casefold() for competitor in result.analysis.competitor_analysis.competitors]
    assert "dxora technologies" not in names
    assert len(names) == 3


def test_normalise_warns_about_inferred_services(sample_payload) -> None:
    payload = LLMAnalysisPayload.model_validate(sample_payload)
    result, warnings = normalise_analysis(payload, _extracted())
    assert any(s.source == "inferred" for s in result.analysis.top_services)
    assert any("inferred" in warning.lower() for warning in warnings)


def test_normalise_caps_query_and_service_lists(sample_payload) -> None:
    extra_queries = []
    for index in range(8):
        extra_queries.append(
            {
                "query": f"additional query {index} for testing",
                "platforms": ["Google"],
                "intent": "Commercial investigation",
                "business_relevance": "This is an extra query used to test list caps.",
                "target_audience": "Test audience",
            }
        )
    sample_payload["analysis"]["target_search_queries"].extend(extra_queries)
    payload = LLMAnalysisPayload.model_validate(sample_payload)
    result, _ = normalise_analysis(payload, _extracted())
    assert len(result.analysis.target_search_queries) == 5


def test_normalise_pads_missing_competitors(sample_payload) -> None:
    sample_payload["analysis"]["competitor_analysis"]["competitors"] = sample_payload[
        "analysis"
    ]["competitor_analysis"]["competitors"][:1]
    payload = LLMAnalysisPayload.model_validate(sample_payload)
    result, warnings = normalise_analysis(payload, _extracted())
    competitors = result.analysis.competitor_analysis.competitors
    assert len(competitors) == 3
    assert competitors[-1].brand_name.startswith("Unverified competitor candidate")
    assert any("placeholder" in warning.lower() for warning in warnings)


def test_normalise_fills_sparse_optional_lists(sample_payload) -> None:
    competitor_analysis = sample_payload["analysis"]["competitor_analysis"]
    competitor_analysis["competitor_strengths"] = ["One strength"]
    competitor_analysis["competitor_weaknesses"] = []
    competitor_analysis["competitive_advantages"] = []
    competitor_analysis["market_positioning_opportunities"] = []

    seo = sample_payload["analysis"]["seo_improvements"]
    seo["secondary_keywords"] = []
    seo["long_tail_keywords"] = []
    seo["business_keywords"] = []
    seo["supporting_content"] = seo["supporting_content"][:3]
    seo["on_page_fixes"] = []

    payload = LLMAnalysisPayload.model_validate(sample_payload)
    result, _ = normalise_analysis(payload, _extracted())

    cleaned = result.analysis.competitor_analysis
    assert len(cleaned.competitor_strengths) >= 2
    assert len(cleaned.competitor_weaknesses) >= 2
    assert len(cleaned.competitive_advantages) >= 2
    assert len(cleaned.market_positioning_opportunities) >= 2

    seo_result = result.analysis.seo_improvements
    assert seo_result.secondary_keywords
    assert seo_result.long_tail_keywords
    assert seo_result.business_keywords
    assert len(seo_result.supporting_content) == 3
    assert seo_result.on_page_fixes