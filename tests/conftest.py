from __future__ import annotations

import copy
import os

# The test suite must never read a developer's real .env values.
os.environ["LLM_PROVIDER"] = "groq"
os.environ["LLM_MODEL"] = "openai/gpt-oss-120b"
os.environ["LLM_FALLBACK_PROVIDER"] = ""
os.environ["LLM_FALLBACK_MODEL"] = ""
os.environ["GROQ_API_KEY"] = "test-groq-key"
os.environ["CACHE_ENABLED"] = "false"
os.environ["RATE_LIMIT_PER_HOUR"] = "1000"
os.environ["ENVIRONMENT"] = "test"
os.environ["MAX_INPUT_CHARS"] = "9000"

import pytest  # noqa: E402

SAMPLE_HTML = """<!doctype html>
<html lang="en">
<head>
  <title>Dxora Technologies | AI Software Development</title>
  <meta name="description" content="Dxora builds AI-powered web and mobile products for startups and growing businesses.">
  <meta property="og:site_name" content="Dxora Technologies">
  <link rel="canonical" href="https://www.dxora.com/">
  <script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"Dxora Technologies","description":"A digital product studio."}</script>
</head>
<body>
  <header><nav><a href="/services">Services</a> <a href="/about">About</a></nav></header>
  <main>
    <h1>AI-powered software development</h1>
    <p>We design and build web platforms, mobile applications and AI products for ambitious teams.</p>
    <h2>Custom web development</h2>
    <p>Our engineering team delivers fast, accessible and secure websites for businesses that need to grow.</p>
    <p>We combine product strategy, user research and modern engineering to ship reliable digital experiences.</p>
    <h2>Mobile application development</h2>
    <p>We create native and cross-platform mobile applications that help companies reach customers wherever they are.</p>
    <p>From discovery to launch, we work as an extension of your product team and focus on measurable outcomes.</p>
    <h2>AI and automation</h2>
    <p>We help organisations adopt practical AI features, automate repetitive workflows and make better use of their data.</p>
    <p>Our process includes technical audits, rapid prototypes and production-ready implementation with clear documentation.</p>
    <h2>Why teams choose Dxora</h2>
    <p>Clients value transparent communication, senior engineering and a product mindset that prioritises business results.</p>
    <p>We support startups and established companies that want dependable partners for their next digital initiative.</p>
  </main>
  <footer><p>© 2026 Dxora Technologies. All rights reserved.</p></footer>
</body>
</html>"""


LLM_PAYLOAD = {
    "brand": {
        "name": "Dxora Technologies",
        "category": "Software Development & AI Solutions",
        "summary": "Dxora Technologies designs and builds web, mobile and AI products for startups and growing businesses.",
        "website": "https://www.dxora.com",
        "main_offerings": ["Web development", "Mobile applications", "AI solutions"],
        "target_market": "Startups and growing businesses",
        "evidence": ["AI-powered software development", "Custom web development"],
    },
    "analysis": {
        "competitor_analysis": {
            "brand_overview": "Dxora is a digital product studio focused on web, mobile and AI delivery for growth-stage companies.",
            "main_category": "Software development",
            "main_products_services": ["Web development", "Mobile applications", "AI solutions"],
            "competitors": [
                {
                    "brand_name": "Northstar Digital",
                    "website": "https://example.com/northstar",
                    "overview": "A digital agency offering web and product design services to growing companies.",
                    "main_service": "Custom web development",
                    "target_market": "Small and mid-sized businesses",
                    "key_strength": "Strong brand design and long client relationships",
                    "weakness_or_gap": "Limited in-house AI engineering capability",
                    "opportunity_for_your_brand": "Lead with production AI delivery rather than design alone",
                    "source": "AI-generated suggestion",
                    "confidence": "low",
                },
                {
                    "brand_name": "Bright Labs",
                    "website": None,
                    "overview": "A product engineering consultancy serving funded startups and enterprise teams.",
                    "main_service": "Product engineering",
                    "target_market": "Funded startups",
                    "key_strength": "Experienced senior engineering bench",
                    "weakness_or_gap": "Higher delivery cost and slower onboarding",
                    "opportunity_for_your_brand": "Compete on transparent pricing and faster starts",
                    "source": "AI-generated suggestion",
                    "confidence": "medium",
                },
                {
                    "brand_name": "CodeForge Studio",
                    "website": "https://example.org/codeforge",
                    "overview": "An offshore software development studio with web and mobile delivery teams.",
                    "main_service": "Offshore development",
                    "target_market": "Cost-sensitive businesses",
                    "key_strength": "Competitive delivery rates",
                    "weakness_or_gap": "Communication and quality consistency concerns",
                    "opportunity_for_your_brand": "Emphasise senior local collaboration",
                    "source": "AI-generated suggestion",
                    "confidence": "low",
                },
            ],
            "competitor_strengths": ["Established brands", "Senior engineering", "Competitive pricing"],
            "competitor_weaknesses": ["Limited AI delivery", "Higher cost", "Inconsistent communication"],
            "competitive_advantages": ["Combined web, mobile and AI delivery", "Transparent communication"],
            "market_positioning_opportunities": ["Own the AI-first product studio niche", "Target funded startups"],
            "disclaimer": "AI-generated suggestions.",
        },
        "target_search_queries": [
            {
                "query": "AI software development company",
                "platforms": ["Google", "LinkedIn"],
                "intent": "Commercial investigation",
                "business_relevance": "Matches the core AI development offer.",
                "target_audience": "Startups and SMBs",
            },
            {
                "query": "custom web development agency",
                "platforms": ["Google"],
                "intent": "Commercial investigation",
                "business_relevance": "Matches the custom web development offer.",
                "target_audience": "Growing businesses",
            },
            {
                "query": "mobile app development partner",
                "platforms": ["Google", "LinkedIn"],
                "intent": "Commercial investigation",
                "business_relevance": "Matches the mobile application offer.",
                "target_audience": "Product teams",
            },
            {
                "query": "hire AI engineers for startup",
                "platforms": ["LinkedIn", "X"],
                "intent": "Transactional",
                "business_relevance": "Reaches founders looking for AI delivery help.",
                "target_audience": "Startup founders",
            },
            {
                "query": "digital product studio for AI",
                "platforms": ["Google", "Facebook", "Instagram"],
                "intent": "Awareness",
                "business_relevance": "Supports category education and brand discovery.",
                "target_audience": "Non-technical founders",
            },
        ],
        "seo_improvements": {
            "primary_keyword": "AI software development company",
            "secondary_keywords": ["custom software development", "mobile app development", "AI solutions"],
            "long_tail_keywords": [
                "AI software development for startups",
                "AI product development partner",
                "custom web development agency",
            ],
            "business_keywords": [
                "digital product studio",
                "AI engineering partner",
                "custom software consultancy",
            ],
            "recommended_title": "AI Software Development Company | Dxora Technologies",
            "title_rationale": "Leads with the primary keyword and includes the brand name.",
            "meta_description": "Dxora builds AI-powered web, mobile and automation products for startups and growing businesses. Talk to our engineering team about your next product.",
            "meta_description_rationale": "States the offer, audience and next step within the visible snippet limit.",
            "supporting_content": [
                {
                    "content_type": "Service landing page",
                    "title": "AI product development",
                    "description": "A dedicated page explaining how Dxora builds AI-powered products.",
                    "target_keyword": "AI product development",
                    "priority": "high",
                },
                {
                    "content_type": "Case study",
                    "title": "AI workflow automation case study",
                    "description": "A proof-led page showing measurable outcomes from an AI automation project.",
                    "target_keyword": "AI workflow automation",
                    "priority": "high",
                },
                {
                    "content_type": "Blog post",
                    "title": "How startups can adopt AI responsibly",
                    "description": "An educational article for non-technical founders evaluating AI adoption.",
                    "target_keyword": "AI adoption for startups",
                    "priority": "medium",
                },
                {
                    "content_type": "Comparison page",
                    "title": "In-house team vs product studio",
                    "description": "A transparent comparison that addresses a common buyer question.",
                    "target_keyword": "in-house team vs agency",
                    "priority": "medium",
                },
            ],
            "on_page_fixes": [
                "Use one clear H1 on every service page.",
                "Add internal links from service pages to relevant case studies.",
                "Add descriptive alt text to product and case-study images.",
            ],
        },
        "top_services": [
            {
                "service_name": "AI product development",
                "description": "Designs and ships AI-enabled products from prototype to production.",
                "target_industry": "SaaS and technology",
                "target_customer": "Startup founders",
                "main_benefit": "Faster path to a validated AI product.",
                "source": "website",
                "evidence": "AI and automation",
            },
            {
                "service_name": "Custom web development",
                "description": "Builds fast, accessible and secure web platforms for growing businesses.",
                "target_industry": "Professional services",
                "target_customer": "Marketing leaders",
                "main_benefit": "A reliable website that supports growth.",
                "source": "website",
                "evidence": "Custom web development",
            },
            {
                "service_name": "Mobile application development",
                "description": "Creates native and cross-platform mobile products for customer-facing teams.",
                "target_industry": "Consumer and retail",
                "target_customer": "Product managers",
                "main_benefit": "Reach customers on the devices they use most.",
                "source": "website",
                "evidence": "Mobile application development",
            },
            {
                "service_name": "AI workflow automation",
                "description": "Automates repetitive internal workflows with practical AI and integration work.",
                "target_industry": "Operations-heavy businesses",
                "target_customer": "Operations leaders",
                "main_benefit": "Reduce manual work and operational errors.",
                "source": "inferred",
                "evidence": "AI and automation",
            },
            {
                "service_name": "Product discovery and strategy",
                "description": "Helps teams validate opportunities before committing to a full build.",
                "target_industry": "Funded startups",
                "target_customer": "Founders and product leads",
                "main_benefit": "Reduce the risk of building the wrong product.",
                "source": "inferred",
                "evidence": "product strategy",
            },
        ],
        "target_audience": {
            "primary_audience": [
                {
                    "audience": "Funded startups",
                    "business_type": "SaaS startup",
                    "requirement": "Launch an AI or web product quickly.",
                    "customer_needs": "Speed, senior engineering and clear communication.",
                    "why_fit": "Matches the product studio offer.",
                },
                {
                    "audience": "Growing SMBs",
                    "business_type": "Professional services",
                    "requirement": "Modernise their digital presence.",
                    "customer_needs": "A dependable partner and predictable delivery.",
                    "why_fit": "Fits the web development offer.",
                },
            ],
            "secondary_audience": [
                {
                    "audience": "Enterprise innovation teams",
                    "business_type": "Corporate",
                    "requirement": "Prototype AI use cases before scaling.",
                    "customer_needs": "Technical credibility and documentation.",
                    "why_fit": "Supports AI discovery and implementation.",
                }
            ],
            "industries": ["SaaS", "Professional services", "Retail"],
            "business_types": ["Startups", "SMBs", "Enterprises"],
            "customer_profiles": ["Founders", "Product managers", "Marketing leaders"],
            "location_focus": "Global remote-first",
            "customer_needs": ["Faster launches", "Senior engineering", "Clear communication"],
            "customer_challenges": ["Limited in-house engineering", "Unclear AI roadmap"],
            "interests": ["AI", "Product strategy", "Digital transformation"],
            "recommended_segments": ["Funded SaaS startups", "Growth-stage SMBs"],
        },
    },
}


@pytest.fixture
def sample_payload() -> dict:
    return copy.deepcopy(LLM_PAYLOAD)


@pytest.fixture
def sample_html() -> str:
    return SAMPLE_HTML


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client