"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings, get_settings
from app.exceptions import AppError
from app.schemas import (
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
    LinkAnalysisRequest,
    LinkAnalysisResponse,
)
from app.services.analysis_service import AnalysisService
from app.utils.logging import configure_logging

logger = logging.getLogger(__name__)


class RateLimiter:
    """In-process sliding-window limiter. Use a shared store for multi-instance deployments."""

    def __init__(self, limit_per_hour: int):
        self.limit = max(0, limit_per_hour)
        self.window_seconds = 3600
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> tuple[bool, int]:
        if self.limit <= 0:
            return True, 0
        now = time.monotonic()
        cutoff = now - self.window_seconds
        async with self._lock:
            bucket = self._buckets[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                retry_after = max(1, int(self.window_seconds - (now - bucket[0])))
                return False, retry_after
            bucket.append(now)
            return True, 0


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip", "")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.debug)
    app.state.settings = settings
    app.state.rate_limiter = RateLimiter(settings.rate_limit_per_hour)
    app.state.analysis_service = AnalysisService(settings)
    for warning in app.state.analysis_service.llm.configuration_warnings():
        logger.warning("LLM configuration: %s", warning)
    logger.info(
        "Starting %s %s environment=%s llm=%s/%s",
        settings.app_name,
        settings.app_version,
        settings.environment,
        settings.llm_provider,
        settings.llm_model,
    )
    try:
        yield
    finally:
        await app.state.analysis_service.aclose()


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Analyse a public website URL with an LLM and return five structured insights: "
        "competitor/brand comparison, target search queries, SEO improvements, top services, "
        "and target audience. Competitor and search-query output is clearly labelled and does "
        "not invent search-volume metrics."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    incoming = request.headers.get("x-request-id", "").strip()
    request_id = incoming if 8 <= len(incoming) <= 128 else uuid.uuid4().hex
    request.state.request_id = request_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "Unhandled exception method=%s path=%s request_id=%s",
            request.method,
            request.url.path,
            request_id,
        )
        raise
    duration_ms = int((time.perf_counter() - started) * 1000)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-Ms"] = str(duration_ms)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    logger.info(
        "request method=%s path=%s status=%s duration_ms=%s request_id=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        request_id,
    )
    return response


async def rate_limit_dependency(request: Request) -> None:
    limiter: RateLimiter = request.app.state.rate_limiter
    allowed, retry_after = await limiter.check(_client_ip(request))
    if not allowed:
        raise AppError(
            "Rate limit exceeded. Please wait before analysing another website.",
            code="rate_limited",
            status_code=429,
            details={"retry_after_seconds": retry_after},
        )


def get_analysis_service(request: Request) -> AnalysisService:
    return request.app.state.analysis_service


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    headers = {}
    if exc.status_code == 429 and exc.details:
        retry_after = exc.details.get("retry_after_seconds")
        if retry_after:
            headers["Retry-After"] = str(retry_after)
    payload = ErrorResponse(
        success=False,
        request_id=getattr(request.state, "request_id", None),
        error=ErrorDetail(code=exc.code, message=exc.message, details=exc.details),
    )
    return JSONResponse(
        status_code=exc.status_code, content=payload.model_dump(mode="json"), headers=headers
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = []
    for error in exc.errors():
        errors.append(
            {
                "location": ".".join(str(part) for part in error.get("loc", ())),
                "message": error.get("msg", "invalid value"),
                "type": error.get("type", "validation_error"),
            }
        )
    payload = ErrorResponse(
        success=False,
        request_id=getattr(request.state, "request_id", None),
        error=ErrorDetail(
            code="invalid_request",
            message="Request validation failed.",
            details={"errors": errors},
        ),
    )
    return JSONResponse(status_code=422, content=payload.model_dump(mode="json"))


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    payload = ErrorResponse(
        success=False,
        request_id=getattr(request.state, "request_id", None),
        error=ErrorDetail(
            code="not_found" if exc.status_code == 404 else "http_error",
            message=str(exc.detail),
        ),
    )
    return JSONResponse(status_code=exc.status_code, content=payload.model_dump(mode="json"))


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "Unhandled application error request_id=%s", getattr(request.state, "request_id", None)
    )
    payload = ErrorResponse(
        success=False,
        request_id=getattr(request.state, "request_id", None),
        error=ErrorDetail(
            code="internal_error",
            message="The analysis could not be completed. Please try again later.",
        ),
    )
    return JSONResponse(status_code=500, content=payload.model_dump(mode="json"))


@app.get("/", tags=["meta"], summary="Service information")
async def root() -> dict:
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "description": "AI-powered website link analysis API",
        "docs": "/docs",
        "health": "/health",
        "endpoint": "POST /link-analysis",
        "llm": {"provider": settings.llm_provider, "model": settings.llm_model},
    }


@app.get("/health", tags=["meta"], response_model=HealthResponse, summary="Health check")
async def health() -> HealthResponse:
    current: Settings = get_settings()
    return HealthResponse(
        status="ok",
        version=current.app_version,
        environment=current.environment,
        llm_provider=current.llm_provider,
        llm_model=current.llm_model,
        cache_enabled=current.cache_enabled,
    )


@app.post(
    "/link-analysis",
    tags=["analysis"],
    response_model=LinkAnalysisResponse,
    summary="Analyse a website URL",
    description=(
        "Fetches a public HTML page, extracts its content with SSRF protections, sends a compact "
        "evidence bundle to the configured LLM, validates the structured JSON, and returns "
        "competitor, search-query, SEO, service and audience insights."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Invalid or unsafe URL"},
        422: {"model": ErrorResponse, "description": "Invalid request or unusable page content"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        502: {"model": ErrorResponse, "description": "Website or LLM upstream failure"},
        504: {"model": ErrorResponse, "description": "Website or LLM timeout"},
        500: {"model": ErrorResponse, "description": "Unexpected server error"},
    },
)
async def link_analysis(
    payload: LinkAnalysisRequest,
    request: Request,
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
    _: Annotated[None, Depends(rate_limit_dependency)] = None,
) -> LinkAnalysisResponse:
    request_id = request.state.request_id
    return await service.analyze(payload.url, request_id=request_id)


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
