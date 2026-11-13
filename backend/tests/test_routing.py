import httpx
import pytest

from app.domain.geo import haversine_km
from app.routing.base import LatLng, RouteResult, RoutingError
from app.routing.cache import CachedRouter, TTLCache
from app.routing.haversine import DETOUR_FACTOR, HaversineRouter
from app.routing.osrm import OSRMRouter
from app.routing.service import FallbackRouter, build_router

ORIGIN = LatLng(17.4401, 78.3489)
DESTINATION = LatLng(17.4460, 78.3540)


class CountingRouter:
    def __init__(self) -> None:
        self.route_calls = 0
        self.matrix_calls = 0

    async def route(self, origin: LatLng, destination: LatLng) -> RouteResult:
        self.route_calls += 1
        return RouteResult(
            duration_s=100.0,
            distance_m=1000.0,
            polyline=[(origin.lat, origin.lng), (destination.lat, destination.lng)],
            provider="fake",
        )

    async def matrix(
        self,
        origins: list[LatLng],
        destinations: list[LatLng],
    ) -> list[list[float]]:
        self.matrix_calls += 1
        return [[0.0 for _ in destinations] for _ in origins]


class FailingRouter:
    async def route(self, origin: LatLng, destination: LatLng) -> RouteResult:
        raise httpx.ConnectError("osrm down")

    async def matrix(
        self,
        origins: list[LatLng],
        destinations: list[LatLng],
    ) -> list[list[float]]:
        raise httpx.ConnectError("osrm down")


async def test_haversine_route_applies_detour_and_is_available_offline() -> None:
    router = HaversineRouter(hour_of_day=lambda: 12)

    result = await router.route(ORIGIN, DESTINATION)

    crow_km = haversine_km(ORIGIN.lat, ORIGIN.lng, DESTINATION.lat, DESTINATION.lng)
    assert result.provider == "haversine"
    assert result.distance_m == pytest.approx(crow_km * 1000 * DETOUR_FACTOR, rel=0.001)
    assert result.duration_s > 0
    assert result.polyline == [(ORIGIN.lat, ORIGIN.lng), (DESTINATION.lat, DESTINATION.lng)]


async def test_haversine_traffic_profile_slows_rush_hour() -> None:
    rush = await HaversineRouter(hour_of_day=lambda: 18).route(ORIGIN, DESTINATION)
    midday = await HaversineRouter(hour_of_day=lambda: 13).route(ORIGIN, DESTINATION)
    night = await HaversineRouter(hour_of_day=lambda: 2).route(ORIGIN, DESTINATION)

    assert rush.duration_s > midday.duration_s > night.duration_s


async def test_haversine_matrix_shape_and_symmetry() -> None:
    router = HaversineRouter(hour_of_day=lambda: 12)

    matrix = await router.matrix([ORIGIN, DESTINATION], [ORIGIN, DESTINATION])

    assert len(matrix) == 2
    assert len(matrix[0]) == 2
    assert matrix[0][0] == 0
    assert matrix[1][1] == 0
    assert matrix[0][1] == pytest.approx(matrix[1][0], rel=1e-6)
    assert matrix[0][1] > 0


async def test_osrm_route_parses_geojson_geometry() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == (
            "/route/v1/driving/78.348900,17.440100;78.354000,17.446000"
        )
        assert request.url.params.get("geometries") == "geojson"
        return httpx.Response(
            200,
            json={
                "code": "Ok",
                "routes": [
                    {
                        "duration": 640.5,
                        "distance": 3200.0,
                        "geometry": {
                            "coordinates": [
                                [78.3489, 17.4401],
                                [78.3540, 17.4460],
                            ]
                        },
                    }
                ],
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://osrm"
    )
    router = OSRMRouter(base_url="http://osrm", client=client)
    try:
        result = await router.route(ORIGIN, DESTINATION)
    finally:
        await client.aclose()

    assert result.provider == "osrm"
    assert result.duration_s == pytest.approx(640.5)
    assert result.distance_m == pytest.approx(3200.0)
    assert result.polyline == [(17.4401, 78.3489), (17.4460, 78.3540)]


async def test_osrm_matrix_uses_table_endpoint_and_handles_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/table/v1/driving/" in request.url.path
        assert request.url.params.get("sources") == "0;1"
        assert request.url.params.get("destinations") == "2;3"
        return httpx.Response(
            200,
            json={"code": "Ok", "durations": [[0.0, 120.5], [None, 0.0]]},
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://osrm"
    )
    router = OSRMRouter(base_url="http://osrm", client=client)
    try:
        matrix = await router.matrix([ORIGIN, DESTINATION], [ORIGIN, DESTINATION])
    finally:
        await client.aclose()

    assert matrix[0][1] == pytest.approx(120.5)
    assert matrix[1][0] == float("inf")


async def test_osrm_raises_on_error_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "NoRoute"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://osrm"
    )
    router = OSRMRouter(base_url="http://osrm", client=client)
    try:
        with pytest.raises(RoutingError):
            await router.route(ORIGIN, DESTINATION)
    finally:
        await client.aclose()


async def test_fallback_router_switches_to_haversine() -> None:
    router = FallbackRouter(FailingRouter(), HaversineRouter(hour_of_day=lambda: 12))

    route = await router.route(ORIGIN, DESTINATION)
    matrix = await router.matrix([ORIGIN], [DESTINATION])

    assert route.provider == "haversine"
    assert matrix[0][0] > 0


async def test_build_router_osrm_with_unreachable_server_falls_back() -> None:
    router = build_router(
        "osrm",
        osrm_base_url="http://127.0.0.1:9",
        timeout_s=0.2,
        cache_ttl_s=60,
    )

    result = await router.route(ORIGIN, DESTINATION)

    assert result.provider == "haversine"


async def test_unknown_provider_defaults_to_haversine() -> None:
    router = build_router("does-not-exist", cache_ttl_s=60)

    result = await router.route(ORIGIN, DESTINATION)

    assert result.provider == "haversine"


async def test_cached_router_rounds_coordinates_and_caches() -> None:
    inner = CountingRouter()
    router = CachedRouter(inner, ttl_s=60)

    first = await router.route(ORIGIN, DESTINATION)
    second = await router.route(
        LatLng(ORIGIN.lat + 0.00001, ORIGIN.lng),
        LatLng(DESTINATION.lat, DESTINATION.lng + 0.00001),
    )
    assert inner.route_calls == 1
    assert first == second

    await router.matrix([ORIGIN], [DESTINATION])
    await router.matrix([LatLng(ORIGIN.lat + 0.00001, ORIGIN.lng)], [DESTINATION])
    assert inner.matrix_calls == 1


async def test_cached_matrix_returns_isolated_copies() -> None:
    router = CachedRouter(CountingRouter(), ttl_s=60)

    first = await router.matrix([ORIGIN], [DESTINATION])
    first[0][0] = 999.0
    second = await router.matrix([ORIGIN], [DESTINATION])

    assert second[0][0] == 0.0


def test_ttl_cache_expires_entries() -> None:
    now = [100.0]
    cache = TTLCache(ttl_s=5, clock=lambda: now[0])

    cache.set("key", "value")
    assert cache.get("key") == "value"

    now[0] += 6
    assert cache.get("key") is None
