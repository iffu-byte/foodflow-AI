import asyncio

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from redis.asyncio import from_url as redis_from_url
from sqlalchemy import text

from app.config import settings
from app.db import get_sessionmaker

router = APIRouter(tags=["system"])


class CheckResult(BaseModel):
    name: str
    ok: bool
    detail: str | None = None


async def _check_db() -> None:
    async with get_sessionmaker()() as session:
        await session.execute(text("SELECT 1"))


async def _check_redis() -> None:
    client = redis_from_url(settings.redis_url)
    try:
        await client.ping()
    finally:
        await client.aclose()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


@router.get("/readyz")
async def readyz(response: Response) -> dict[str, object]:
    checks: list[CheckResult] = []
    for name, check in (("database", _check_db), ("redis", _check_redis)):
        try:
            await asyncio.wait_for(check(), timeout=2.0)
            checks.append(CheckResult(name=name, ok=True))
        except Exception as exc:
            checks.append(CheckResult(name=name, ok=False, detail=type(exc).__name__))

    ready = all(check.ok for check in checks)
    response.status_code = (
        status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return {
        "status": "ready" if ready else "degraded",
        "checks": [check.model_dump() for check in checks],
    }
