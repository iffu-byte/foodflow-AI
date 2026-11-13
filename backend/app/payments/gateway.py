"""Small Razorpay adapter; the secret remains exclusively on the API server."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.config import settings


class PaymentGatewayError(Exception):
    """A safe, customer-facing failure while talking to a payment provider."""


@dataclass(frozen=True)
class ProviderOrder:
    id: str
    amount_paise: int
    currency: str
    status: str


@dataclass(frozen=True)
class ProviderPayment:
    id: str
    order_id: str
    amount_paise: int
    currency: str
    status: str
    method: str | None


class PaymentGateway(Protocol):
    provider: str

    async def create_order(
        self, *, amount_paise: int, receipt: str, notes: dict[str, str]
    ) -> ProviderOrder: ...

    async def fetch_payment(self, payment_id: str) -> ProviderPayment: ...

    def verify_checkout_signature(
        self, *, provider_order_id: str, payment_id: str, signature: str
    ) -> bool: ...

    def verify_webhook_signature(self, *, raw_body: bytes, signature: str) -> bool: ...


class RazorpayGateway:
    provider = "razorpay"
    _base_url = "https://api.razorpay.com/v1"

    def __init__(
        self,
        *,
        key_id: str,
        key_secret: str,
        webhook_secret: str,
        timeout_s: float,
    ) -> None:
        self.key_id = key_id
        self._key_secret = key_secret
        self._webhook_secret = webhook_secret
        self._timeout_s = timeout_s

    async def create_order(
        self, *, amount_paise: int, receipt: str, notes: dict[str, str]
    ) -> ProviderOrder:
        payload = {
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt,
            "notes": notes,
        }
        body = await self._request("POST", "/orders", json=payload)
        return self._provider_order(body)

    async def fetch_payment(self, payment_id: str) -> ProviderPayment:
        body = await self._request("GET", f"/payments/{payment_id}")
        try:
            return ProviderPayment(
                id=str(body["id"]),
                order_id=str(body["order_id"]),
                amount_paise=int(body["amount"]),
                currency=str(body["currency"]),
                status=str(body["status"]),
                method=str(body["method"]) if body.get("method") else None,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PaymentGatewayError("payment provider returned an invalid payment") from exc

    def verify_checkout_signature(
        self, *, provider_order_id: str, payment_id: str, signature: str
    ) -> bool:
        payload = f"{provider_order_id}|{payment_id}".encode()
        expected = hmac.new(
            self._key_secret.encode(), payload, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def verify_webhook_signature(self, *, raw_body: bytes, signature: str) -> bool:
        if not self._webhook_secret:
            return False
        expected = hmac.new(
            self._webhook_secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                response = await client.request(
                    method,
                    f"{self._base_url}{path}",
                    auth=(self.key_id, self._key_secret),
                    **kwargs,
                )
        except httpx.HTTPError as exc:
            raise PaymentGatewayError("payment provider is temporarily unavailable") from exc
        if response.status_code >= 400:
            raise PaymentGatewayError("payment provider could not create the payment")
        try:
            body = response.json()
        except ValueError as exc:
            raise PaymentGatewayError("payment provider returned an invalid response") from exc
        if not isinstance(body, dict):
            raise PaymentGatewayError("payment provider returned an invalid response")
        return body

    @staticmethod
    def _provider_order(body: dict[str, Any]) -> ProviderOrder:
        try:
            return ProviderOrder(
                id=str(body["id"]),
                amount_paise=int(body["amount"]),
                currency=str(body["currency"]),
                status=str(body["status"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PaymentGatewayError("payment provider returned an invalid order") from exc


def get_gateway() -> PaymentGateway | None:
    if settings.payment_provider != "razorpay":
        return None
    return RazorpayGateway(
        key_id=settings.razorpay_key_id,
        key_secret=settings.razorpay_key_secret,
        webhook_secret=settings.razorpay_webhook_secret,
        timeout_s=settings.payment_timeout_s,
    )
