import time
from collections.abc import Callable
from typing import Any

from app.routing.base import LatLng, Router, RouteResult


class TTLCache:
    def __init__(
        self,
        ttl_s: float,
        max_entries: int = 4096,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_s = ttl_s
        self._max_entries = max_entries
        self._clock = clock
        self._data: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self._clock() >= expires_at:
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        if len(self._data) >= self._max_entries:
            self._evict()
        self._data[key] = (self._clock() + self._ttl_s, value)

    def _evict(self) -> None:
        now = self._clock()
        for key in [key for key, (expires_at, _) in self._data.items() if expires_at <= now]:
            self._data.pop(key, None)
        while len(self._data) >= self._max_entries:
            self._data.pop(next(iter(self._data)))


class CachedRouter:
    """Caches route results keyed by coordinates rounded to ~100 m."""

    def __init__(self, inner: Router, ttl_s: float = 300.0, precision: int = 3) -> None:
        self._inner = inner
        self._cache = TTLCache(ttl_s)
        self._precision = precision

    def _coord(self, point: LatLng) -> str:
        lat = round(point.lat, self._precision)
        lng = round(point.lng, self._precision)
        return f"{lat:.{self._precision}f},{lng:.{self._precision}f}"

    async def route(self, origin: LatLng, destination: LatLng) -> RouteResult:
        key = f"route|{self._coord(origin)}|{self._coord(destination)}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        result = await self._inner.route(origin, destination)
        self._cache.set(key, result)
        return result

    async def matrix(
        self,
        origins: list[LatLng],
        destinations: list[LatLng],
    ) -> list[list[float]]:
        key = (
            "matrix|"
            + ";".join(self._coord(origin) for origin in origins)
            + "|"
            + ";".join(self._coord(destination) for destination in destinations)
        )
        cached = self._cache.get(key)
        if cached is not None:
            return [row[:] for row in cached]
        matrix = await self._inner.matrix(origins, destinations)
        self._cache.set(key, [row[:] for row in matrix])
        return matrix
