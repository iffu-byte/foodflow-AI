from __future__ import annotations

import httpx


class ApiError(RuntimeError):
    def __init__(self, method: str, path: str, status_code: int, detail: str) -> None:
        super().__init__(f"{method} {path} -> {status_code}: {detail}")
        self.method = method
        self.path = path
        self.status_code = status_code
        self.detail = detail


class FoodFlowClient:
    def __init__(self, base_url: str, timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    async def __aenter__(self) -> "FoodFlowClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: object):
        response = await self._client.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise ApiError(method, path, response.status_code, response.text[:300])
        return response.json()

    async def list_restaurants(self) -> list[dict]:
        return await self._request("GET", "/restaurants")

    async def get_menu(self, restaurant_id: str) -> list[dict]:
        return await self._request("GET", f"/restaurants/{restaurant_id}/menu")

    async def list_customers(self) -> list[dict]:
        return await self._request("GET", "/customers")

    async def list_riders(self) -> list[dict]:
        return await self._request("GET", "/riders")

    async def create_order(self, payload: dict) -> dict:
        return await self._request("POST", "/orders", json=payload)

    async def accept_order(self, order_id: str) -> dict:
        return await self._request("POST", f"/restaurant/orders/{order_id}/accept")

    async def start_preparing(self, order_id: str) -> dict:
        return await self._request("POST", f"/restaurant/orders/{order_id}/preparing")

    async def mark_ready(self, order_id: str) -> dict:
        return await self._request("POST", f"/restaurant/orders/{order_id}/ready")

    async def list_candidates(self, order_id: str) -> list[dict]:
        return await self._request("GET", f"/orders/{order_id}/candidates")

    async def assign_order(self, order_id: str, rider_id: str | None = None) -> dict:
        payload = {"rider_id": rider_id} if rider_id is not None else {}
        return await self._request("POST", f"/orders/{order_id}/assign", json=payload)

    async def cancel_order(self, order_id: str, reason: str = "simulator abandoned") -> dict:
        return await self._request(
            "POST", f"/orders/{order_id}/cancel", json={"reason": reason}
        )

    async def update_status(self, order_id: str, status: str, rider_id: str) -> dict:
        return await self._request(
            "POST",
            f"/orders/{order_id}/status",
            json={"status": status, "rider_id": rider_id},
        )

    async def update_rider_location(self, rider_id: str, lat: float, lng: float) -> dict:
        return await self._request(
            "POST",
            f"/riders/{rider_id}/location",
            json={"lat": lat, "lng": lng},
        )
