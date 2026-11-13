from collections.abc import Callable
from datetime import datetime

from app.domain.geo import haversine_km
from app.routing.base import LatLng, RouteResult

DETOUR_FACTOR = 1.3
BASE_SPEED_KMH = 24.0


def traffic_speed_factor(hour: int) -> float:
    if 7 <= hour < 10 or 17 <= hour < 21:
        return 0.55
    if 10 <= hour < 17:
        return 0.8
    return 1.0


def travel_speed_kmh(hour: int) -> float:
    return BASE_SPEED_KMH * traffic_speed_factor(hour)


class HaversineRouter:
    """Straight-line router with a detour factor and a simple traffic profile.

    This is the always-available fallback. OSRM/ORS refine the distance and
    geometry; the learned traffic correction (Phase 4, Model B) refines the
    duration.
    """

    name = "haversine"

    def __init__(self, hour_of_day: Callable[[], int] | None = None) -> None:
        self._hour_of_day = hour_of_day or (lambda: datetime.now().astimezone().hour)

    def _duration_s(self, crow_km: float, hour: int) -> tuple[float, float]:
        distance_m = crow_km * 1000 * DETOUR_FACTOR
        speed_mps = travel_speed_kmh(hour) * 1000 / 3600
        return distance_m / speed_mps, distance_m

    async def route(self, origin: LatLng, destination: LatLng) -> RouteResult:
        hour = self._hour_of_day()
        crow_km = haversine_km(origin.lat, origin.lng, destination.lat, destination.lng)
        duration_s, distance_m = self._duration_s(crow_km, hour)
        return RouteResult(
            duration_s=duration_s,
            distance_m=distance_m,
            polyline=[(origin.lat, origin.lng), (destination.lat, destination.lng)],
            provider=self.name,
        )

    async def matrix(
        self,
        origins: list[LatLng],
        destinations: list[LatLng],
    ) -> list[list[float]]:
        hour = self._hour_of_day()
        return [
            [
                self._duration_s(
                    haversine_km(origin.lat, origin.lng, destination.lat, destination.lng),
                    hour,
                )[0]
                for destination in destinations
            ]
            for origin in origins
        ]
