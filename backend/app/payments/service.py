"""Payment use-cases.  This module is the only caller of provider adapters."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domain.exceptions import BadRequestError, ConflictError, NotFoundError
from app.domain.models import Order, OrderEvent, OrderStatus, PaymentAttempt, PaymentWebhookReceipt
from app.payments import gateway


@dataclass(frozen=True)
class CheckoutSession:
    provider: str
    provider_order_id: str
    key_id: str
    amount_paise: int
    currency: str
    display_name: str
    description: str
    is_test_mode: bool


@dataclass(frozen=True)
class PaymentResult:
    order: Order
    event: OrderEvent | None
    became_paid: bool


def configuration() -> dict[str, object]:
    return {
        "provider": settings.payment_provider,
        "online_payments_enabled": settings.payment_provider == "razorpay",
        "is_test_mode": settings.razorpay_key_id.startswith("rzp_test_")
        if settings.payment_provider == "razorpay"
        else True,
    }


async def start_checkout(session: AsyncSession, order: Order) -> tuple[CheckoutSession, OrderEvent]:
    """Create a provider order using the trusted total, never client input."""
    provider = gateway.get_gateway()
    if provider is None or settings.payment_provider != "razorpay":
        raise BadRequestError("online payments are not configured")
    if order.payment_method != "RAZORPAY":
        raise BadRequestError("this order does not use online payment")

    amount_paise = _to_paise(order.total_price)
    try:
        provider_order = await provider.create_order(
            amount_paise=amount_paise,
            receipt=(order.order_number or str(order.id))[:40],
            notes={"foodflow_order_id": str(order.id), "foodflow_order": order.order_number or ""},
        )
    except gateway.PaymentGatewayError as exc:
        raise BadRequestError(str(exc)) from exc
    if (
        provider_order.amount_paise != amount_paise
        or provider_order.currency.upper() != "INR"
        or provider_order.status not in {"created", "attempted"}
    ):
        raise BadRequestError("payment provider returned an unexpected order")

    attempt = PaymentAttempt(
        order_id=order.id,
        provider=provider.provider,
        status="CREATED",
        amount=order.total_price,
        currency="INR",
        provider_order_id=provider_order.id,
        provider_payload={"provider_order_status": provider_order.status},
    )
    event = OrderEvent(
        order_id=order.id,
        type="payment_initiated",
        payload={
            "provider": provider.provider,
            "provider_order_id": provider_order.id,
            "amount": str(order.total_price),
            "currency": "INR",
        },
    )
    session.add_all([attempt, event])
    return (
        CheckoutSession(
            provider="razorpay",
            provider_order_id=provider_order.id,
            key_id=settings.razorpay_key_id,
            amount_paise=amount_paise,
            currency="INR",
            display_name="FoodFlow AI",
            description=f"Order {order.order_number or order.id}",
            is_test_mode=settings.razorpay_key_id.startswith("rzp_test_"),
        ),
        event,
    )


async def resume_checkout(session: AsyncSession, *, order: Order) -> CheckoutSession:
    attempt = await _attempt_for_order(session, order.id)
    if order.payment_method != "RAZORPAY" or order.payment_status != "PENDING":
        raise ConflictError("this order does not need an online payment")
    if order.status in {OrderStatus.CANCELLED, OrderStatus.FAILED}:
        raise ConflictError("a cancelled order cannot be paid")
    if attempt is None or attempt.provider != "razorpay" or not attempt.provider_order_id:
        raise NotFoundError("payment session not found")
    return CheckoutSession(
        provider="razorpay",
        provider_order_id=attempt.provider_order_id,
        key_id=settings.razorpay_key_id,
        amount_paise=_to_paise(attempt.amount),
        currency=attempt.currency,
        display_name="FoodFlow AI",
        description=f"Order {order.order_number or order.id}",
        is_test_mode=settings.razorpay_key_id.startswith("rzp_test_"),
    )


async def verify_checkout(
    session: AsyncSession,
    *,
    order_id: UUID,
    provider_order_id: str,
    payment_id: str,
    signature: str,
) -> PaymentResult:
    provider = gateway.get_gateway()
    if provider is None:
        raise BadRequestError("online payments are not configured")
    order = await session.get(Order, order_id, with_for_update=True)
    if order is None:
        raise NotFoundError("order not found")
    attempt = await _attempt_for_order(session, order_id, for_update=True)
    if (
        attempt is None
        or attempt.provider != provider.provider
        or attempt.provider_order_id != provider_order_id
    ):
        raise BadRequestError("payment order does not match this order")
    if not provider.verify_checkout_signature(
        provider_order_id=provider_order_id, payment_id=payment_id, signature=signature
    ):
        raise BadRequestError("payment signature could not be verified")
    if order.payment_status == "PAID":
        if attempt.provider_payment_id == payment_id:
            return PaymentResult(order, None, False)
        raise ConflictError("this order has already been paid")
    try:
        provider_payment = await provider.fetch_payment(payment_id)
    except gateway.PaymentGatewayError as exc:
        raise BadRequestError(str(exc)) from exc
    _assert_provider_payment(attempt, provider_payment)
    if provider_payment.status != "captured":
        attempt.status = provider_payment.status.upper()
        attempt.signature_verified = True
        attempt.provider_payment_id = payment_id
        raise ConflictError("payment is not captured yet; please wait a moment")
    event, became_paid = _record_captured_payment(
        session,
        order=order,
        attempt=attempt,
        payment_id=payment_id,
        method=provider_payment.method,
        source="checkout_callback",
    )
    return PaymentResult(order, event, became_paid)


async def process_razorpay_webhook(
    session: AsyncSession,
    *,
    raw_body: bytes,
    signature: str,
    event_id: str | None,
) -> PaymentResult | None:
    provider = gateway.get_gateway()
    if provider is None or provider.provider != "razorpay":
        raise NotFoundError("payment provider is not enabled")
    if not provider.verify_webhook_signature(raw_body=raw_body, signature=signature):
        raise BadRequestError("invalid payment webhook signature")
    try:
        payload = json.loads(raw_body)
        event_type = str(payload["event"])
    except (ValueError, KeyError, TypeError) as exc:
        raise BadRequestError("invalid payment webhook payload") from exc
    stable_event_id = event_id or hashlib.sha256(raw_body).hexdigest()
    previous = await session.scalar(
        select(PaymentWebhookReceipt).where(
            PaymentWebhookReceipt.provider == "razorpay",
            PaymentWebhookReceipt.provider_event_id == stable_event_id,
        )
    )
    if previous is not None:
        return None
    session.add(
        PaymentWebhookReceipt(
            provider="razorpay",
            provider_event_id=stable_event_id,
            event_type=event_type,
        )
    )
    if event_type != "payment.captured":
        return None
    try:
        entity = payload["payload"]["payment"]["entity"]
        provider_order_id = str(entity["order_id"])
        payment_id = str(entity["id"])
        provider_payment = gateway.ProviderPayment(
            id=payment_id,
            order_id=provider_order_id,
            amount_paise=int(entity["amount"]),
            currency=str(entity["currency"]),
            status=str(entity["status"]),
            method=str(entity["method"]) if entity.get("method") else None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise BadRequestError("invalid captured-payment webhook") from exc
    attempt = await session.scalar(
        select(PaymentAttempt)
        .where(
            PaymentAttempt.provider == "razorpay",
            PaymentAttempt.provider_order_id == provider_order_id,
        )
        .with_for_update()
    )
    if attempt is None:
        return None
    order = await session.get(Order, attempt.order_id, with_for_update=True)
    if order is None:
        return None
    _assert_provider_payment(attempt, provider_payment)
    event, became_paid = _record_captured_payment(
        session,
        order=order,
        attempt=attempt,
        payment_id=payment_id,
        method=provider_payment.method,
        source="webhook",
    )
    return PaymentResult(order, event, became_paid)


async def _attempt_for_order(
    session: AsyncSession, order_id: UUID, *, for_update: bool = False
) -> PaymentAttempt | None:
    stmt = select(PaymentAttempt).where(PaymentAttempt.order_id == order_id)
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


def _to_paise(amount: Decimal) -> int:
    return int((amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _assert_provider_payment(
    attempt: PaymentAttempt, payment: gateway.ProviderPayment
) -> None:
    if (
        payment.order_id != attempt.provider_order_id
        or payment.amount_paise != _to_paise(attempt.amount)
        or payment.currency.upper() != attempt.currency.upper()
    ):
        raise BadRequestError("payment details do not match this order")


def _record_captured_payment(
    session: AsyncSession,
    *,
    order: Order,
    attempt: PaymentAttempt,
    payment_id: str,
    method: str | None,
    source: str,
) -> tuple[OrderEvent | None, bool]:
    if order.payment_status == "PAID":
        return None, False
    attempt.status = "CAPTURED"
    attempt.signature_verified = True
    attempt.provider_payment_id = payment_id
    attempt.captured_at = datetime.now(UTC)
    attempt.provider_payload = {"method": method, "verified_via": source}
    if order.status in {OrderStatus.CANCELLED, OrderStatus.FAILED}:
        order.payment_status = "REFUND_PENDING"
        event_type = "payment_refund_required"
    else:
        order.payment_status = "PAID"
        event_type = "payment_captured"
    event = OrderEvent(
        order_id=order.id,
        type=event_type,
        payload={
            "provider": attempt.provider,
            "payment_id": payment_id,
            "amount": str(attempt.amount),
            "currency": attempt.currency,
            "source": source,
        },
    )
    session.add(event)
    return event, order.payment_status == "PAID"
