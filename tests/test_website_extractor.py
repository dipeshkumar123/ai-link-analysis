from __future__ import annotations

import pytest

from app.config import Settings
from app.services.website_extractor import (
    WebsiteExtractionError,
    parse_website_html,
)

SAMPLE_HTML = """<!doctype html><html><head>
<title>Sample Studio | Web and AI</title>
<meta name="description" content="Sample Studio builds web and AI products.">
</head><body><h1>Sample Studio</h1>
<p>Sample Studio designs and builds digital products for growing businesses.</p>
<p>We combine product strategy, design and engineering to launch reliable websites.</p>
<p>Our team helps startups and established companies with custom development projects.</p>
<p>We focus on accessible, fast and secure experiences that support measurable growth.</p>
<p>Clients work with us from discovery through launch and ongoing iteration.</p>
</body></html>"""


def test_parse_extracts_metadata_headings_links_and_content() -> None:
    html = SAMPLE_HTML.replace(
        "<h1>Sample Studio</h1>",
        '<h1>Sample Studio</h1><nav><a href="/work">Selected work</a></nav>',
    )
    result = parse_website_html(
        html,
        requested_url="https://sample.test/",
        final_url="https://sample.test/",
        settings=Settings(),
    )
    assert result.title == "Sample Studio | Web and AI"
    assert result.meta_description == "Sample Studio builds web and AI products."
    assert "Sample Studio" in result.headings
    assert "Selected work" in result.link_labels
    assert "digital products" in result.content
    assert result.words > 40


def test_parse_removes_script_content_from_visible_text() -> None:
    html = SAMPLE_HTML.replace(
        "</head>",
        '<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"Sample Studio"}</script></head>',
    )
    result = parse_website_html(
        html,
        requested_url="https://sample.test/",
        final_url="https://sample.test/",
        settings=Settings(),
    )
    assert result.structured_data
    assert result.structured_data[0]["name"] == "Sample Studio"
    assert "schema.org" not in result.content


def test_thin_page_without_meta_is_rejected() -> None:
    with pytest.raises(WebsiteExtractionError) as exc:
        parse_website_html(
            "<html><body><p>Hello</p></body></html>",
            requested_url="https://thin.test/",
            final_url="https://thin.test/",
            settings=Settings(),
        )
    assert exc.value.code in {"thin_content", "insufficient_content"}


def test_prompt_context_is_bounded() -> None:
    long_html = SAMPLE_HTML.replace(
        "</body>", "<p>" + ("Long paragraph about digital products. " * 200) + "</p></body>"
    )
    result = parse_website_html(
        long_html,
        requested_url="https://sample.test/",
        final_url="https://sample.test/",
        settings=Settings(),
    )
    context = result.to_prompt_context(max_chars=2500)
    assert len(context) <= 2500
    assert "PAGE TITLE" in context