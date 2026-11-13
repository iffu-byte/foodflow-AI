import logging

import httpx

from app.routing.base import LatLng, RouteResult, RoutingError

logger = logging.getLogger(__name__)


class OSRMRouter:
    name = "osrm"

    def __init__(
        self,
        base_url: str = "http://localhost:5000",
        timeout_s: float = 2.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._client = client

    async def _get(self, path: str, params: dict[str, str]) -> dict:
        url = f"{self._base_url}{path}"
        if self._client is not None:
            response = await self._client.get(url, params=params)
        else:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _coords(points: list[LatLng]) -> str:
        return ";".join(f"{point.lng:.6f},{point.lat:.6f}" for point in points)

    @staticmethod
    def _check(data: dict) -> None:
        if data.get("code") != "Ok":
            raise RoutingError(f"OSRM error: {data.get('code')}")

    async def route(self, origin: LatLng, destination: LatLng) -> RouteResult:
        data = await self._get(
            f"/route/v1/driving/{self._coords([origin, destination])}",
            {
                "overview": "full",
                "geometries": "geojson",
                "alternatives": "false",
                "steps": "false",
            },
        )
        self._check(data)
        routes = data.get("routes") or []
        if not routes:
            raise RoutingError("OSRM returned no routes")

        route = routes[0]
        polyline = [(lat, lng) for lng, lat in route["geometry"]["coordinates"]]
        return RouteResult(
            duration_s=float(route["duration"]),
            distance_m=float(route["distance"]),
            polyline=polyline,
            provider=self.name,
        )

    async def matrix(
        self,
        origins: list[LatLng],
        destinations: list[LatLng],
    ) -> list[list[float]]:
        if not origins or not destinations:
            return []

        points = origins + destinations
        origin_count = len(origins)
        sources = ";".join(str(index) for index in range(origin_count))
        targets = ";".join(
            str(index) for index in range(origin_count, origin_count + len(destinations))
        )

        data = await self._get(
            f"/table/v1/driving/{self._coords(points)}",
            {
                "annotations": "duration",
                "sources": sources,
                "destinations": targets,
            },
        )
        self._check(data)
        durations = data.get("durations")
        if durations is None:
            raise RoutingError("OSRM returned no duration matrix")

        return [
            [float(value) if value is not None else float("inf") for value in row]
            for row in durations
        ]
