"""Metered access to paid AI and maps providers.

Every call made through this module is logged in ``ai_usage`` with an estimated
cost, and a daily budget stops paid calls before they run once it is spent.
Callers always have a local fallback, so an exhausted budget, a missing key or
a provider outage degrades a feature instead of breaking a screen.
"""

import base64
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domain.models import AiUsage

logger = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Published list prices at the time of writing, used only for the cost meter.
GEMINI_INPUT_USD_PER_TOKEN = 0.10 / 1_000_000
GEMINI_OUTPUT_USD_PER_TOKEN = 0.40 / 1_000_000
PLACES_COST_USD = {
    "places_text_search": 0.032,
    "places_details": 0.020,
    "places_photo": 0.007,
}


@dataclass(frozen=True)
class GeminiResult:
    data: dict
    input_tokens: int
    output_tokens: int
    cost_usd: float


def _start_of_day() -> datetime:
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


async def spent_today(session: AsyncSession) -> float:
    value = await session.scalar(
        select(func.coalesce(func.sum(AiUsage.est_cost_usd), 0.0)).where(
            AiUsage.created_at >= _start_of_day()
        )
    )
    return float(value or 0.0)


async def within_budget(session: AsyncSession, expected_cost: float = 0.0) -> bool:
    return await spent_today(session) + expected_cost <= settings.ai_daily_budget_usd


def record(
    session: AsyncSession,
    *,
    provider: str,
    purpose: str,
    cache_hit: bool = False,
    ok: bool = True,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    detail: str = "",
) -> None:
    """Queue a usage row; the caller's transaction commits it."""
    session.add(
        AiUsage(
            provider=provider,
            purpose=purpose,
            cache_hit=cache_hit,
            ok=ok,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            est_cost_usd=round(cost_usd, 6),
            detail=detail[:200],
        )
    )


def gemini_enabled() -> bool:
    return bool(settings.gemini_api_key)


def google_maps_enabled() -> bool:
    return bool(settings.google_maps_api_key)


async def gemini_json(
    session: AsyncSession,
    *,
    purpose: str,
    prompt: str,
    image_bytes: bytes | None = None,
    mime_type: str = "image/jpeg",
    timeout_s: float = 20.0,
) -> GeminiResult | None:
    """Ask Gemini for a JSON object. Returns None when unavailable or over budget."""
    if not gemini_enabled():
        return None
    if not await within_budget(session, 0.001):
        record(session, provider="gemini", purpose=purpose, ok=False, detail="daily budget spent")
        return None

    parts: list[dict] = [{"text": prompt}]
    if image_bytes is not None:
        parts.append(
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                }
            }
        )
    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(
                GEMINI_URL.format(model=settings.gemini_model),
                headers={"x-goog-api-key": settings.gemini_api_key},
                json=body,
            )
        response.raise_for_status()
        payload = response.json()
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("Gemini returned a non-object JSON value")
        usage = payload.get("usageMetadata", {})
        input_tokens = int(usage.get("promptTokenCount", 0))
        output_tokens = int(usage.get("candidatesTokenCount", 0))
        cost = (
            input_tokens * GEMINI_INPUT_USD_PER_TOKEN
            + output_tokens * GEMINI_OUTPUT_USD_PER_TOKEN
        )
        record(
            session,
            provider="gemini",
            purpose=purpose,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            detail=settings.gemini_model,
        )
        return GeminiResult(data, input_tokens, output_tokens, cost)
    except Exception as exc:  # noqa: BLE001 - every failure falls back locally
        logger.warning("gemini %s call failed: %s", purpose, exc)
        record(session, provider="gemini", purpose=purpose, ok=False, detail=str(exc)[:200])
        return None


async def usage_summary(session: AsyncSession) -> dict:
    since = _start_of_day()
    rows = (
        await session.execute(
            select(
                AiUsage.provider,
                AiUsage.purpose,
                func.count(),
                func.sum(case((AiUsage.cache_hit.is_(True), 1), else_=0)),
                func.coalesce(func.sum(AiUsage.input_tokens), 0),
                func.coalesce(func.sum(AiUsage.output_tokens), 0),
                func.coalesce(func.sum(AiUsage.est_cost_usd), 0.0),
            )
            .where(AiUsage.created_at >= since)
            .group_by(AiUsage.provider, AiUsage.purpose)
            .order_by(AiUsage.provider, AiUsage.purpose)
        )
    ).all()
    lines = []
    total_calls = total_hits = 0
    total_cost = 0.0
    for provider, purpose, calls, hits, tokens_in, tokens_out, cost in rows:
        hits = int(hits or 0)
        lines.append(
            {
                "provider": provider,
                "purpose": purpose,
                "calls": int(calls),
                "cache_hits": hits,
                "input_tokens": int(tokens_in),
                "output_tokens": int(tokens_out),
                "est_cost_usd": round(float(cost), 4),
            }
        )
        total_calls += int(calls)
        total_hits += hits
        total_cost += float(cost)
    return {
        "since": since,
        "budget_usd": settings.ai_daily_budget_usd,
        "spent_usd": round(total_cost, 4),
        "remaining_usd": round(max(0.0, settings.ai_daily_budget_usd - total_cost), 4),
        "calls": total_calls,
        "cache_hits": total_hits,
        "cache_hit_rate": round(total_hits / total_calls, 3) if total_calls else None,
        "gemini_enabled": gemini_enabled(),
        "google_maps_enabled": google_maps_enabled(),
        "lines": lines,
    }
