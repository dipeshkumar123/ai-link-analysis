"""Website fetching, HTML extraction and SSRF-safe redirect handling."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup, Tag

from app.config import Settings
from app.utils.text import clean_whitespace, dedupe_preserve_order, truncate_text, word_count
from app.utils.validators import URLValidationError, validate_public_url

REDIRECT_STATUSES = {301, 302, 303, 307, 308}
HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")


class WebsiteExtractionError(Exception):
    """A user-safe extraction failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "website_error",
        status_code: int = 502,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details


@dataclass
class ExtractedWebsite:
    requested_url: str
    final_url: str
    status_code: int
    title: str | None = None
    meta_description: str | None = None
    site_name: str | None = None
    language: str | None = None
    canonical_url: str | None = None
    headings: list[str] = field(default_factory=list)
    meta_keywords: list[str] = field(default_factory=list)
    open_graph: dict[str, str] = field(default_factory=dict)
    structured_data: list[dict[str, Any]] = field(default_factory=list)
    link_labels: list[str] = field(default_factory=list)
    image_alts: list[str] = field(default_factory=list)
    content: str = ""
    words: int = 0
    truncated: bool = False
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    warnings: list[str] = field(default_factory=list)

    @property
    def hostname(self) -> str:
        return urlsplit(self.final_url).hostname or ""

    def to_prompt_context(self, max_chars: int = 9000) -> str:
        """Build a compact, LLM-friendly representation of the page."""
        header_parts = [
            f"WEBSITE URL: {self.final_url}",
            f"REQUESTED URL: {self.requested_url}",
            f"PAGE TITLE: {self.title or 'N/A'}",
            f"SITE NAME (og:site_name): {self.site_name or 'N/A'}",
            f"META DESCRIPTION: {self.meta_description or 'N/A'}",
            f"LANGUAGE: {self.language or 'N/A'}",
            f"CANONICAL URL: {self.canonical_url or 'N/A'}",
        ]
        if self.meta_keywords:
            header_parts.append(f"META KEYWORDS: {', '.join(self.meta_keywords[:15])}")

        headings = " | ".join(self.headings[:30]) if self.headings else "N/A"
        header_parts.append(f"HEADINGS (h1-h3): {truncate_text(headings, 1800, '')}")

        if self.structured_data:
            structured = json.dumps(
                self.structured_data[:8], ensure_ascii=False, separators=(",", ":")
            )
            header_parts.append(f"STRUCTURED DATA (JSON-LD): {truncate_text(structured, 2600, '')}")

        if self.link_labels:
            header_parts.append(
                "SERVICE / NAVIGATION LINK LABELS: " + " | ".join(self.link_labels[:30])
            )
        if self.image_alts:
            header_parts.append("IMAGE ALT TEXT: " + " | ".join(self.image_alts[:15]))

        header = "\n".join(header_parts)
        remaining = max(1200, max_chars - len(header) - 80)
        body = truncate_text(self.content, remaining)
        warnings = ""
        if self.warnings:
            warnings = "\nEXTRACTION WARNINGS: " + "; ".join(self.warnings)
        context = f"{header}\n\nVISIBLE WEBSITE CONTENT:\n{body}{warnings}"
        if len(context) > max_chars:
            context = truncate_text(context, max_chars)
        return context


def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:  # pragma: no cover - fallback for unusual environments
        return BeautifulSoup(html, "html.parser")


def _meta_content(soup: BeautifulSoup, *, name: str | None = None, prop: str | None = None) -> str | None:
    attrs: dict[str, str] = {}
    if name:
        attrs["name"] = name
    if prop:
        attrs["property"] = prop
    tag = soup.find("meta", attrs=attrs)
    if tag and tag.get("content"):
        return clean_whitespace(str(tag["content"])) or None
    return None


def _detect_encoding(content_type: str | None, payload: bytes) -> str:
    if content_type:
        match = re.search(r"charset=([\w\-]+)", content_type, re.IGNORECASE)
        if match:
            return match.group(1)
    head = payload[:4096].decode("ascii", errors="ignore")
    match = re.search(r"<meta[^>]+charset=[\"']?([\w\-]+)", head, re.IGNORECASE)
    if match:
        return match.group(1)
    return "utf-8"


def _flatten_jsonld(value: Any) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            objects.extend(_flatten_jsonld(item))
    elif isinstance(value, dict):
        if "@graph" in value:
            objects.extend(_flatten_jsonld(value["@graph"]))
        objects.append(value)
    return objects


def _shorten(value: Any, limit: int = 300) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return ", ".join(str(item) for item in value[:8])
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)[:limit]
    text = clean_whitespace(str(value))
    return truncate_text(text, limit, "") if text else None


def _summarise_jsonld(obj: dict[str, Any]) -> dict[str, Any] | None:
    interesting = {
        "@type",
        "name",
        "legalName",
        "description",
        "url",
        "areaServed",
        "serviceType",
        "knowsAbout",
        "sameAs",
        "priceRange",
        "telephone",
        "email",
        "address",
        "offers",
        "aggregateRating",
    }
    summary: dict[str, Any] = {}
    for key in interesting:
        if key in obj:
            value = _shorten(obj[key])
            if value:
                summary[key] = value
    if not summary.get("@type") and not summary.get("name") and not summary.get("description"):
        return None
    return summary


def _extract_structured_data(soup: BeautifulSoup) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw or not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        for obj in _flatten_jsonld(data):
            summary = _summarise_jsonld(obj)
            if summary and summary not in summaries:
                summaries.append(summary)
    return summaries[:10]


_BOILERPLATE_MARKERS = (
    "accept all cookies",
    "accept cookies",
    "cookie policy",
    "subscribe to our newsletter",
    "sign up for our newsletter",
    "all rights reserved",
    "privacy policy",
    "terms of service",
    "terms and conditions",
    "javascript is disabled",
    "enable javascript",
    "skip to main content",
    "follow us on",
    "share on facebook",
    "share on twitter",
)


def _is_boilerplate(line: str) -> bool:
    lowered = line.casefold()
    return any(marker in lowered for marker in _BOILERPLATE_MARKERS)


def _extract_main_content(soup: BeautifulSoup) -> tuple[str, list[str]]:
    target: Tag | BeautifulSoup = (
        soup.find("main")
        or soup.find("article")
        or soup.find(attrs={"role": "main"})
        or soup.find("body")
        or soup
    )
    for tag in target.find_all(
        ["nav", "footer", "aside", "script", "style", "noscript", "svg", "canvas", "form", "template"]
    ):
        tag.decompose()

    lines: list[str] = []
    for tag in target.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote", "dd", "td"]):
        text = clean_whitespace(tag.get_text(" ", strip=True))
        if len(text) >= 20 and not _is_boilerplate(text):
            lines.append(text)

    if len(lines) < 8:
        raw_lines = target.get_text("\n", strip=True).splitlines()
        lines = [
            clean_whitespace(line)
            for line in raw_lines
            if len(clean_whitespace(line)) >= 20 and not _is_boilerplate(clean_whitespace(line))
        ]

    deduped = dedupe_preserve_order(lines, min_length=20)
    return "\n".join(deduped[:260]), deduped


def parse_website_html(
    html: str,
    *,
    requested_url: str,
    final_url: str,
    status_code: int = 200,
    content_type: str | None = None,
    truncated: bool = False,
    settings: Settings | None = None,
) -> ExtractedWebsite:
    """Parse HTML into structured extraction data (also used by tests)."""
    settings = settings or Settings()
    soup = _soup(html)
    structured_data = _extract_structured_data(soup)
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        # Structured data is captured above; remove the raw scripts from visible text.
        tag.extract()

    title_tag = soup.find("title")
    title = clean_whitespace(title_tag.get_text(" ", strip=True)) if title_tag else None
    og_title = _meta_content(soup, prop="og:title")
    if not title:
        title = og_title

    meta_description = (
        _meta_content(soup, name="description")
        or _meta_content(soup, prop="og:description")
        or _meta_content(soup, name="twitter:description")
    )
    site_name = _meta_content(soup, prop="og:site_name")
    language_tag = soup.find("html")
    language = (
        clean_whitespace(str(language_tag.get("lang"))) if language_tag and language_tag.get("lang") else None
    )
    canonical_tag = soup.find("link", attrs={"rel": lambda value: value and "canonical" in value})
    canonical_url = clean_whitespace(str(canonical_tag.get("href"))) if canonical_tag and canonical_tag.get("href") else None
    meta_keywords = _meta_content(soup, name="keywords")
    keywords = (
        dedupe_preserve_order(re.split(r"[,;]", meta_keywords), min_length=2)
        if meta_keywords
        else []
    )

    open_graph: dict[str, str] = {}
    for meta in soup.find_all("meta"):
        prop = meta.get("property") or meta.get("name")
        content = meta.get("content")
        if prop and content and str(prop).startswith(("og:", "twitter:")):
            open_graph[str(prop)] = clean_whitespace(str(content))[:400]

    headings = dedupe_preserve_order(
        clean_whitespace(tag.get_text(" ", strip=True))
        for tag in soup.find_all(["h1", "h2", "h3"])
        if len(clean_whitespace(tag.get_text(" ", strip=True))) >= 3
    )[:30]

    link_labels: list[str] = []
    for anchor in soup.find_all("a", href=True):
        label = clean_whitespace(anchor.get_text(" ", strip=True))
        if 2 <= len(label) <= 100 and not label.casefold().startswith(("javascript:", "mailto:", "tel:")):
            link_labels.append(label)
    link_labels = dedupe_preserve_order(link_labels, min_length=2)[:40]

    image_alts = dedupe_preserve_order(
        (str(img.get("alt", "")) for img in soup.find_all("img", alt=True)), min_length=3
    )[:20]

    content, _lines = _extract_main_content(soup)

    words = word_count(content)
    warnings: list[str] = []
    if truncated:
        warnings.append("The page exceeded the download size limit and was truncated.")
    if words < 80:
        warnings.append(
            "Very little visible text was found. The page may rely on JavaScript; insights may be limited."
        )
    if not title:
        warnings.append("The page has no <title> element.")
    if not meta_description:
        warnings.append("The page has no meta description.")

    extracted = ExtractedWebsite(
        requested_url=requested_url,
        final_url=final_url,
        status_code=status_code,
        title=title,
        meta_description=meta_description,
        site_name=site_name,
        language=language,
        canonical_url=canonical_url,
        headings=headings,
        meta_keywords=keywords,
        open_graph=open_graph,
        structured_data=structured_data,
        link_labels=link_labels,
        image_alts=image_alts,
        content=content,
        words=words,
        truncated=truncated,
        warnings=warnings,
    )

    if words < 25 and not meta_description and not structured_data:
        raise WebsiteExtractionError(
            "The page has almost no readable content. It may be JavaScript-rendered, blocked, "
            "or not a normal HTML page. Try a public content page or the site's about/services page.",
            code="insufficient_content",
            status_code=422,
            details={"word_count": words, "content_type": content_type},
        )

    return extracted


class WebsiteExtractor:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }

    async def _get_client(self) -> tuple[httpx.AsyncClient, bool]:
        if self._client is not None:
            return self._client, False
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.settings.fetch_timeout_seconds, connect=8.0),
            headers=self._headers(),
            follow_redirects=False,
            max_redirects=0,
            verify=True,
        )
        return client, True

    async def extract(self, url: str) -> ExtractedWebsite:
        try:
            validated = await validate_public_url(
                url, allow_private_hosts=self.settings.allow_private_hosts
            )
        except URLValidationError:
            raise

        current_url = validated.url
        client, should_close = await self._get_client()
        try:
            for redirect_number in range(self.settings.max_redirects + 1):
                try:
                    current_validated = await validate_public_url(
                        current_url, allow_private_hosts=self.settings.allow_private_hosts
                    )
                except URLValidationError:
                    raise

                try:
                    async with client.stream("GET", current_validated.url) as response:
                        status = response.status_code
                        if status in REDIRECT_STATUSES:
                            location = response.headers.get("location")
                            if not location:
                                raise WebsiteExtractionError(
                                    "The website returned a redirect without a destination.",
                                    code="invalid_redirect",
                                )
                            if redirect_number >= self.settings.max_redirects:
                                raise WebsiteExtractionError(
                                    "The website redirected too many times.",
                                    code="too_many_redirects",
                                    status_code=502,
                                )
                            current_url = urljoin(str(response.url), location.strip())
                            continue

                        if status in {401, 403}:
                            raise WebsiteExtractionError(
                                f"The website blocked automated access (HTTP {status}). "
                                "Try a different public page on the same site.",
                                code="access_blocked",
                                status_code=422,
                                details={"upstream_status": status},
                            )
                        if status == 429:
                            raise WebsiteExtractionError(
                                "The website is rate-limiting requests (HTTP 429). Try again later.",
                                code="upstream_rate_limited",
                                status_code=502,
                                details={"upstream_status": status},
                            )
                        if status >= 400:
                            raise WebsiteExtractionError(
                                f"The website returned HTTP {status}.",
                                code="website_http_error",
                                status_code=502,
                                details={"upstream_status": status},
                            )

                        content_type = response.headers.get("content-type", "")
                        lowered_type = content_type.lower()
                        if lowered_type and not any(
                            allowed in lowered_type for allowed in HTML_CONTENT_TYPES
                        ):
                            raise WebsiteExtractionError(
                                "The URL did not return an HTML page "
                                f"(Content-Type: {content_type or 'unknown'}).",
                                code="unsupported_content_type",
                                status_code=422,
                            )

                        chunks: list[bytes] = []
                        total = 0
                        truncated = False
                        async for chunk in response.aiter_bytes():
                            total += len(chunk)
                            if total > self.settings.max_page_bytes:
                                allowed = self.settings.max_page_bytes - (total - len(chunk))
                                if allowed > 0:
                                    chunks.append(chunk[:allowed])
                                truncated = True
                                break
                            chunks.append(chunk)
                        payload = b"".join(chunks)

                        if not lowered_type:
                            head = payload[:2048].lower()
                            if b"<html" not in head and b"<!doctype html" not in head:
                                raise WebsiteExtractionError(
                                    "The URL did not return HTML content.",
                                    code="unsupported_content_type",
                                    status_code=422,
                                )

                        encoding = _detect_encoding(content_type, payload)
                        try:
                            html = payload.decode(encoding, errors="replace")
                        except LookupError:
                            html = payload.decode("utf-8", errors="replace")

                        return parse_website_html(
                            html,
                            requested_url=url,
                            final_url=str(response.url),
                            status_code=status,
                            content_type=content_type,
                            truncated=truncated,
                            settings=self.settings,
                        )
                except httpx.TimeoutException as exc:
                    raise WebsiteExtractionError(
                        "The website took too long to respond.",
                        code="website_timeout",
                        status_code=504,
                    ) from exc
                except httpx.HTTPError as exc:
                    raise WebsiteExtractionError(
                        "The website could not be fetched.",
                        code="website_fetch_failed",
                        status_code=502,
                        details={"reason": exc.__class__.__name__},
                    ) from exc

            raise WebsiteExtractionError(
                "The website redirected too many times.",
                code="too_many_redirects",
                status_code=502,
            )
        finally:
            if should_close:
                await client.aclose()
