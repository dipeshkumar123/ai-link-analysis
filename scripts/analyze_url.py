"""Convenience CLI for local smoke tests.

Usage:
    python scripts/analyze_url.py https://example.com
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid

from app.config import get_settings
from app.services.analysis_service import AnalysisService


async def main(url: str) -> int:
    service = AnalysisService(get_settings())
    try:
        result = await service.analyze(url, request_id=uuid.uuid4().hex)
        print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
        return 0
    finally:
        await service.aclose()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/analyze_url.py <url>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(main(sys.argv[1])))
