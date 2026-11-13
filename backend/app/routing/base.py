from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class LatLng:
    lat: float
    lng: float


@dataclass(frozen=True, slots=True)
class RouteResult:
    duration_s: float
    distance_m: float
    polyline: list[tuple[float, float]] = field(default_factory=list)
    provider: str = "haversine"


class RoutingError(RuntimeError):
    """Raised when a routing provider cannot answer a request."""


@runtime_checkable
class Router(Protocol):
    async def route(self, origin: LatLng, destination: LatLng) -> RouteResult: ...

    async def matrix(
        self,
        origins: list[LatLng],
        destinations: list[LatLng],
    ) -> list[list[float]]: ...
