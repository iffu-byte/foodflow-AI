import logging
from functools import lru_cache

from app.config import settings
from app.routing.base import LatLng, Router, RouteResult
from app.routing.cache import CachedRouter
from app.routing.haversine import HaversineRouter
from app.routing.osrm import OSRMRouter

logger = logging.getLogger(__name__)


class FallbackRouter:
    """Tries the primary provider, then the fallback on any failure."""

    def __init__(self, primary: Router, fallback: Router) -> None:
        self._primary = primary
        self._fallback = fallback

    async def route(self, origin: LatLng, destination: LatLng) -> RouteResult:
        try:
            return await self._primary.route(origin, destination)
        except Exception as exc:
            logger.warning(
                "routing provider failed (%s: %s); falling back",
                type(exc).__name__,
                exc,
            )
            return await self._fallback.route(origin, destination)

    async def matrix(
        self,
        origins: list[LatLng],
        destinations: list[LatLng],
    ) -> list[list[float]]:
        try:
            return await self._primary.matrix(origins, destinations)
        except Exception as exc:
            logger.warning(
                "routing matrix provider failed (%s: %s); falling back",
                type(exc).__name__,
                exc,
            )
            return await self._fallback.matrix(origins, destinations)


def build_router(
    provider: str | None = None,
    *,
    osrm_base_url: str | None = None,
    timeout_s: float | None = None,
    cache_ttl_s: float | None = None,
) -> Router:
    provider_name = (provider or settings.routing_provider).lower()
    fallback = HaversineRouter()

    base: Router
    if provider_name == "haversine":
        base = fallback
    elif provider_name == "osrm":
        base = FallbackRouter(
            OSRMRouter(
                base_url=osrm_base_url or settings.osrm_base_url,
                timeout_s=timeout_s if timeout_s is not None else settings.routing_timeout_s,
            ),
            fallback,
        )
    else:
        logger.warning("unknown routing provider %r; using haversine", provider_name)
        base = fallback

    return CachedRouter(
        base,
        ttl_s=cache_ttl_s if cache_ttl_s is not None else settings.routing_cache_ttl_s,
    )


@lru_cache
def get_router() -> Router:
    return build_router()
