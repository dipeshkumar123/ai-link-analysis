"""Prompt templates and the JSON schema used for structured LLM output."""

from __future__ import annotations

from datetime import date

from app.services.website_extractor import ExtractedWebsite


def _obj(properties: dict, *, description: str | None = None) -> dict:
    schema: dict = {
        "type": "object",
        "properties": properties,
        "required": list(properties.keys()),
        "additionalProperties": False,
    }
    if description:
        schema["description"] = description
    return schema


def _arr(items: dict, *, description: str | None = None) -> dict:
    schema: dict = {"type": "array", "items": items}
    if description:
        schema["description"] = description
    return schema


def _str(description: str | None = None) -> dict:
    return {"type": "string", **({"description": description} if description else {})}


BRAND_SCHEMA = _obj(
    {
        "name": _str("Brand name as shown on the website."),
        "category": _str("Main business category."),
        "summary": _str("Two to four sentence business overview based only on the page."),
        "website": _str("Canonical website URL, or an empty string if unknown."),
        "main_offerings": _arr(_str(), description="Main products or services stated on the page."),
        "target_market": _str("Primary market or geography, or an empty string."),
        "evidence": _arr(_str(), description="Short phrases from the page supporting the summary."),
    }
)

COMPETITOR_SCHEMA = _obj(
    {
        "brand_name": _str(),
        "website": _str("Competitor website, or an empty string if not confidently known."),
        "overview": _str(),
        "main_service": _str(),
        "target_market": _str(),
        "key_strength": _str(),
        "weakness_or_gap": _str(),
        "opportunity_for_your_brand": _str(),
        "source": {"type": "string", "enum": ["AI-generated suggestion", "public knowledge"]},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    }
)

SEARCH_QUERY_SCHEMA = _obj(
    {
        "query": _str("A realistic search query a potential customer would type."),
        "platforms": _arr(
            {"type": "string", "enum": ["Google", "Facebook", "Instagram", "LinkedIn", "X"]}
        ),
        "intent": _str("Search intent such as service discovery, comparison, or B2B research."),
        "business_relevance": _str("Why this query matters for the brand."),
        "target_audience": _str("The customer segment most likely to use the query."),
    }
)

SEO_CONTENT_SCHEMA = _obj(
    {
        "content_type": _str("e.g. service landing page, FAQ, blog post, location page."),
        "title": _str(),
        "description": _str(),
        "target_keyword": _str(),
        "priority": {"type": "string", "enum": ["high", "medium", "low"]},
    }
)

SEO_SCHEMA = _obj(
    {
        "primary_keyword": _str(),
        "secondary_keywords": _arr(_str()),
        "long_tail_keywords": _arr(_str()),
        "business_keywords": _arr(_str()),
        "recommended_title": _str("SEO title, ideally at most 60 characters."),
        "title_rationale": _str(),
        "meta_description": _str("Human-friendly meta description, ideally at most 155 characters."),
        "meta_description_rationale": _str(),
        "supporting_content": _arr(SEO_CONTENT_SCHEMA),
        "on_page_fixes": _arr(_str()),
    }
)

SERVICE_SCHEMA = _obj(
    {
        "service_name": _str(),
        "description": _str(),
        "target_industry": _str(),
        "target_customer": _str(),
        "main_benefit": _str(),
        "source": {"type": "string", "enum": ["website", "inferred"]},
        "evidence": _str("A short phrase from the website, or an empty string if inferred."),
    }
)

AUDIENCE_SCHEMA = _obj(
    {
        "audience": _str(),
        "business_type": _str(),
        "requirement": _str(),
        "customer_needs": _str(),
        "why_fit": _str(),
    }
)

COMPETITOR_ANALYSIS_SCHEMA = _obj(
    {
        "brand_overview": _str(),
        "main_category": _str(),
        "main_products_services": _arr(_str()),
        "competitors": _arr(COMPETITOR_SCHEMA),
        "competitor_strengths": _arr(_str()),
        "competitor_weaknesses": _arr(_str()),
        "competitive_advantages": _arr(_str()),
        "market_positioning_opportunities": _arr(_str()),
        "disclaimer": _str(),
    }
)

TARGET_AUDIENCE_SCHEMA = _obj(
    {
        "primary_audience": _arr(AUDIENCE_SCHEMA),
        "secondary_audience": _arr(AUDIENCE_SCHEMA),
        "industries": _arr(_str()),
        "business_types": _arr(_str()),
        "customer_profiles": _arr(_str()),
        "location_focus": _str("Geographic focus, or an empty string if not stated."),
        "customer_needs": _arr(_str()),
        "customer_challenges": _arr(_str()),
        "interests": _arr(_str()),
        "recommended_segments": _arr(_str()),
    }
)

ANALYSIS_JSON_SCHEMA: dict = _obj(
    {
        "brand": BRAND_SCHEMA,
        "analysis": _obj(
            {
                "competitor_analysis": COMPETITOR_ANALYSIS_SCHEMA,
                "target_search_queries": _arr(SEARCH_QUERY_SCHEMA),
                "seo_improvements": SEO_SCHEMA,
                "top_services": _arr(SERVICE_SCHEMA),
                "target_audience": TARGET_AUDIENCE_SCHEMA,
            }
        ),
    }
)

RESPONSE_SHAPE = """
{
  "brand": {
    "name": "string", "category": "string", "summary": "string", "website": "string",
    "main_offerings": ["string"], "target_market": "string", "evidence": ["string"]
  },
  "analysis": {
    "competitor_analysis": {
      "brand_overview": "string", "main_category": "string",
      "main_products_services": ["string"],
      "competitors": [{
        "brand_name": "string", "website": "string", "overview": "string",
        "main_service": "string", "target_market": "string", "key_strength": "string",
        "weakness_or_gap": "string", "opportunity_for_your_brand": "string",
        "source": "AI-generated suggestion | public knowledge", "confidence": "low | medium | high"
      }],
      "competitor_strengths": ["string"], "competitor_weaknesses": ["string"],
      "competitive_advantages": ["string"], "market_positioning_opportunities": ["string"],
      "disclaimer": "string"
    },
    "target_search_queries": [{
      "query": "string", "platforms": ["Google | Facebook | Instagram | LinkedIn | X"],
      "intent": "string", "business_relevance": "string", "target_audience": "string"
    }],
    "seo_improvements": {
      "primary_keyword": "string", "secondary_keywords": ["string"],
      "long_tail_keywords": ["string"], "business_keywords": ["string"],
      "recommended_title": "string", "title_rationale": "string",
      "meta_description": "string", "meta_description_rationale": "string",
      "supporting_content": [{
        "content_type": "string", "title": "string", "description": "string",
        "target_keyword": "string", "priority": "high | medium | low"
      }],
      "on_page_fixes": ["string"]
    },
    "top_services": [{
      "service_name": "string", "description": "string", "target_industry": "string",
      "target_customer": "string", "main_benefit": "string",
      "source": "website | inferred", "evidence": "string"
    }],
    "target_audience": {
      "primary_audience": [{
        "audience": "string", "business_type": "string", "requirement": "string",
        "customer_needs": "string", "why_fit": "string"
      }],
      "secondary_audience": [{
        "audience": "string", "business_type": "string", "requirement": "string",
        "customer_needs": "string", "why_fit": "string"
      }],
      "industries": ["string"], "business_types": ["string"],
      "customer_profiles": ["string"], "location_focus": "string",
      "customer_needs": ["string"], "customer_challenges": ["string"],
      "interests": ["string"], "recommended_segments": ["string"]
    }
  }
}
""".strip()

SYSTEM_PROMPT = f"""
You are a senior B2B market-research, competitor-intelligence and technical-SEO analyst.
You receive the visible content and metadata of ONE public website page. Analyse only that
page and return one JSON object in the required shape.

NON-NEGOTIABLE RULES
1. The submitted page is the primary evidence. Do not invent revenue, employee counts, prices,
   rankings, traffic, search volume or customer names. Never report search volume.
2. Competitors: name 3 to 5 real companies that plausibly compete in the same category and
   market. Use your public knowledge, mark every competitor as "AI-generated suggestion"
   (or "public knowledge" only when you are confident), and set confidence honestly. If you are
   not confident about a competitor's website, use an empty string. Do not fabricate URLs.
3. Search queries: exactly 5 realistic queries a potential buyer would use. Map each to one or
   more of Google, Facebook, Instagram, LinkedIn and X. Do not add volume or ranking claims.
4. SEO: keywords must fit the actual offer. The recommended title should be at most 60
   characters and the meta description at most 155 characters. Supporting content must be
   specific and actionable, not generic filler.
5. Services: exactly 5. Use services actually stated on the page where possible and set
   source="website" with a short evidence phrase. Use source="inferred" only for a clearly
   labelled, highly relevant recommendation, and leave evidence empty.
6. Target audience: at least 2 primary segments and 1 secondary segment. Describe needs and
   requirements, not demographics alone. Use an empty string for location_focus if the page
   does not state a geography.
7. Be specific and concise. Every list item should be different and useful. Empty strings are
   allowed only where the schema says a value may be unknown.
8. Return JSON only. No markdown fences, commentary, headings or trailing text.

REQUIRED JSON SHAPE (all fields are required):
{RESPONSE_SHAPE}
""".strip()

REPAIR_SYSTEM_PROMPT = f"""
You repair JSON for a website-analysis API. The previous answer failed schema validation or
could not be parsed. Preserve its factual content, fix the structure and list lengths, and
return ONLY a valid JSON object. Do not add markdown, commentary or new invented facts.
Do not add search volumes, revenue figures or other invented metrics.

REQUIRED JSON SHAPE (all fields are required):
{RESPONSE_SHAPE}
""".strip()


def build_user_prompt(extracted: ExtractedWebsite, *, max_context_chars: int = 9000) -> str:
    context = extracted.to_prompt_context(max_context_chars)
    today = date.today().isoformat()
    return f"""Analyse the website below and generate all five required sections.

Today's date: {today}
Brand-name candidates: title={extracted.title or 'N/A'!r};
og:site_name={extracted.site_name or 'N/A'!r}; hostname={extracted.hostname!r}

{context}

Return the JSON object now. Exactly 5 target_search_queries, exactly 5 top_services,
3-5 competitors, at least 2 primary audience segments, and at least 1 secondary segment.
""".strip()


def build_repair_prompt(
    *, previous_output: str, validation_error: str, page_excerpt: str
) -> str:
    return f"""The previous JSON could not be accepted.

Validation errors:
{validation_error[:1500]}

Previous output:
{previous_output[:8000]}

Grounded page excerpt (use only this and the previous output; do not invent facts):
{page_excerpt[:2500]}

Fix the JSON. Return only valid JSON with exactly 5 search queries, exactly 5 services,
3-5 competitors, at least 2 primary audience segments and 1 secondary segment. Preserve the
existing analysis and correct only what is necessary.
""".strip()
