"""Honest order status, delay attribution and automatic compensation.

The tracking screen says what is really happening ("no rider has accepted
yet, 3 riders asked") instead of a frozen countdown. When an order is late,
each stage's overrun is assigned to the party that owned that stage, and a
platform- or rider-caused delay credits the customer without a support chat.
"""

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import service as domain_service
from app.domain.geo import haversine_km
from app.domain.models import (
    DeliveryAssignment,
    Order,
    OrderEvent,
    OrderStatus,
    Restaurant,
    Rider,
    User,
)
from app.marketplace import access, notifications

ACCEPT_EXPECTED_MIN = 3.0
DISPATCH_EXPECTED_MIN = 5.0
HANDOVER_MIN = 3.0
RIDER_SPEED_KMH = 22.0
FREE_CANCEL_ACCEPT_MIN = 8.0
FREE_CANCEL_NO_RIDER_MIN = 10.0
COMPENSATION_LATE_MIN = 10.0
COMPENSATION_MIN = Decimal("20.00")
COMPENSATION_MAX = Decimal("75.00")


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _minutes(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return round((_aware(end) - _aware(start)).total_seconds() / 60.0, 1)


def _drive_min(km: float) -> float:
    return km / RIDER_SPEED_KMH * 60.0


async def timeline(session: AsyncSession, order: Order) -> dict[str, datetime]:
    events = (
        await session.execute(
            select(OrderEvent)
            .where(OrderEvent.order_id == order.id)
            .order_by(OrderEvent.created_at)
        )
    ).scalars()
    marks: dict[str, datetime] = {"placed": _aware(order.placed_at)}
    for event in events:
        stamp = _aware(event.created_at)
        if event.type == "status_changed":
            target = (event.payload or {}).get("to", "").lower()
            if target and target not in marks:
                marks[target] = stamp
        elif event.type == "rider_assigned":
            marks.setdefault("rider_assigned", stamp)
        elif event.type == "rider_arrived_restaurant":
            marks.setdefault("rider_at_restaurant", stamp)
        elif event.type == "rider_arrived_customer":
            marks.setdefault("rider_at_customer", stamp)
    return marks


def attribute(order: Order, marks: dict[str, datetime], est_pickup_min: float) -> dict:
    """Split lateness into restaurant, platform and rider shares (minutes)."""
    prep_expected = float(order.estimated_prep_min or 15)
    drive_expected = _drive_min(order.delivery_distance_km or 2.0) + HANDOVER_MIN
    segments = [
        ("restaurant", "Accepting the order", "placed", "accepted", ACCEPT_EXPECTED_MIN),
        ("restaurant", "Cooking and packing", "accepted", "ready", prep_expected),
        ("platform", "Finding a rider", "ready", "rider_assigned", DISPATCH_EXPECTED_MIN),
        ("rider", "Reaching the restaurant", "rider_assigned", "picked_up", est_pickup_min + 4),
        ("rider", "Riding to you", "picked_up", "delivered", drive_expected),
    ]
    rows = []
    totals = {"restaurant": 0.0, "platform": 0.0, "rider": 0.0}
    for owner, label, start, end, expected in segments:
        start_at = marks.get(start)
        end_at = marks.get(end)
        if start == "rider_assigned" and marks.get("ready") and start_at:
            # A rider who arrived before the food was ready waited on the kitchen.
            start_at = max(start_at, marks["ready"])
        actual = _minutes(start_at, end_at)
        if actual is None:
            continue
        over = max(0.0, actual - expected)
        totals[owner] += over
        rows.append(
            {
                "owner": owner,
                "stage": label,
                "expected_min": round(expected, 1),
                "actual_min": round(actual, 1),
                "over_min": round(over, 1),
            }
        )
    late = None
    if order.promised_eta_at and marks.get("delivered"):
        late = _minutes(order.promised_eta_at, marks["delivered"])
    return {
        "segments": rows,
        "over_by_owner": {key: round(value, 1) for key, value in totals.items()},
        "late_min": late,
    }


def compensation_for(order: Order, attribution: dict) -> tuple[Decimal, str | None]:
    late = attribution.get("late_min") or 0.0
    if late < COMPENSATION_LATE_MIN:
        return Decimal("0.00"), None
    totals = attribution["over_by_owner"]
    ours = totals["platform"] + totals["rider"]
    overall = ours + totals["restaurant"]
    if overall <= 0 or ours / overall < 0.5:
        return Decimal("0.00"), (
            f"Your order was {late:.0f} min late, mostly in the kitchen. "
            "The restaurant has been flagged; no platform credit applies."
        )
    amount = (Decimal(str(order.total_price)) * Decimal("0.10")).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    amount = max(COMPENSATION_MIN, min(COMPENSATION_MAX, amount))
    return amount, (
        f"Your order was {late:.0f} min late and {ours:.0f} min of that was on us "
        f"(finding or moving the rider). ₹{amount:.0f} has been credited automatically."
    )


async def _estimated_pickup_min(session: AsyncSession, order_id: UUID) -> float:
    value = await session.scalar(
        select(DeliveryAssignment.estimated_pickup_min)
        .where(
            DeliveryAssignment.order_id == order_id,
            DeliveryAssignment.status.in_(
                ("ACCEPTED", "ARRIVED_AT_RESTAURANT", "PICKED_UP", "ARRIVED_AT_CUSTOMER",
                 "COMPLETED")
            ),
        )
        .order_by(DeliveryAssignment.accepted_at.desc())
    )
    return float(value or 6.0)


async def settle_delivery(session: AsyncSession, order: Order) -> list:
    """Store the attribution on a delivered order and credit platform delays."""
    marks = await timeline(session, order)
    marks.setdefault("delivered", _now())
    attribution = attribute(order, marks, await _estimated_pickup_min(session, order.id))
    amount, message = compensation_for(order, attribution)
    attribution["message"] = message
    order.delay_attribution = attribution
    rows = []
    if amount > 0:
        order.compensation = amount
        session.add(
            OrderEvent(
                order_id=order.id,
                type="compensation_credited",
                payload={"amount": str(amount), "reason": message},
            )
        )
        rows.append(
            await notifications.add(
                session,
                order.customer_id,
                "COMPENSATION",
                f"₹{amount:.0f} credited for the delay",
                message or "",
                order.id,
            )
        )
    return rows


async def _batch(session: AsyncSession, order: Order) -> dict | None:
    if order.batch_id is None:
        return None
    rows = list(
        (
            await session.execute(
                select(Order)
                .where(Order.batch_id == order.batch_id)
                .order_by(Order.batch_sequence)
            )
        ).scalars()
    )
    drops = [
        {
            "sequence": row.batch_sequence,
            "is_you": row.id == order.id,
            "status": row.status.value,
        }
        for row in rows
    ]
    return {
        "size": len(rows),
        "your_drop": order.batch_sequence,
        "drops": drops,
        "saving": str(order.shared_saving),
    }


async def honest_status(session: AsyncSession, user: User, order_id: UUID) -> dict:
    order = await domain_service.get_order(session, order_id)
    await access.assert_can_view_order(session, user, order)
    restaurant = await session.get(Restaurant, order.restaurant_id)
    rider = await session.get(Rider, order.rider_id) if order.rider_id else None
    marks = await timeline(session, order)
    now = _now()
    since_placed = _minutes(order.placed_at, now) or 0.0
    riders_asked = int(
        await session.scalar(
            select(func.count(func.distinct(DeliveryAssignment.rider_id))).where(
                DeliveryAssignment.order_id == order.id
            )
        )
        or 0
    )
    prep = float(order.estimated_prep_min or 15)
    drive_km = order.delivery_distance_km or 2.0
    status = order.status
    waiting_on = "none"
    free_cancel = None
    remaining = None
    rider_km = None
    batch = await _batch(session, order)

    if status is OrderStatus.PLACED:
        waiting_on = "restaurant"
        headline = f"Waiting for {restaurant.name if restaurant else 'the kitchen'} to accept"
        detail = f"Sent {since_placed:.0f} min ago. Restaurants usually respond within 3 min."
        remaining = max(0.0, ACCEPT_EXPECTED_MIN - since_placed) + prep + 6 + _drive_min(drive_km)
        if since_placed >= FREE_CANCEL_ACCEPT_MIN:
            free_cancel = (
                f"The restaurant hasn't responded in {since_placed:.0f} min. "
                "You can cancel now with a full refund."
            )
    elif status in (OrderStatus.ACCEPTED, OrderStatus.PREPARING):
        waiting_on = "restaurant"
        cooking = _minutes(marks.get("accepted"), now) or 0.0
        headline = "The kitchen is cooking your order"
        detail = f"They said about {prep:.0f} min; {cooking:.0f} min in."
        if cooking > prep + 10:
            detail += f" Running {cooking - prep:.0f} min over the kitchen's own estimate."
        remaining = max(2.0, prep - cooking) + 6 + _drive_min(drive_km)
    elif status is OrderStatus.READY and rider is None:
        waiting_on = "platform"
        waited = _minutes(marks.get("ready"), now) or 0.0
        headline = "Food is packed. No rider has accepted yet"
        detail = (
            f"Waiting {waited:.0f} min; asked {riders_asked} "
            f"rider{'s' if riders_asked != 1 else ''} so far. This wait is on us, not the kitchen."
        )
        remaining = 6 + _drive_min(drive_km)
        if waited >= FREE_CANCEL_NO_RIDER_MIN:
            free_cancel = (
                f"No rider for {waited:.0f} min. Cancel free with a full refund, or keep "
                "waiting and any delay credit applies automatically."
            )
    elif status is OrderStatus.READY and rider is not None and restaurant is not None:
        waiting_on = "rider"
        rider_km = haversine_km(rider.lat, rider.lng, restaurant.lat, restaurant.lng)
        headline = f"{rider.name} is heading to the restaurant"
        detail = f"{rider_km:.1f} km from the kitchen."
        remaining = _drive_min(rider_km) + HANDOVER_MIN + _drive_min(drive_km)
    elif status is OrderStatus.PICKED_UP and rider is not None:
        waiting_on = "rider"
        rider_km = haversine_km(rider.lat, rider.lng, order.drop_lat, order.drop_lng)
        headline = f"{rider.name} is on the way"
        detail = f"{rider_km:.1f} km from your pin."
        remaining = _drive_min(rider_km) + 2
        if batch and batch["your_drop"] and batch["your_drop"] > 1:
            earlier = [d for d in batch["drops"] if d["sequence"] < batch["your_drop"]]
            pending = [d for d in earlier if d["status"] != "DELIVERED"]
            detail += (
                f" You are drop {batch['your_drop']} of {batch['size']}"
                + (f"; {len(pending)} drop before yours." if pending else "; you're next.")
            )
            remaining += 4 * len(pending)
    elif status is OrderStatus.DELIVERED:
        headline = "Delivered"
        proof = order.delivery_proof or {}
        detail = (
            f"Handed over with your code {proof['distance_m']:.0f} m from your pin."
            if proof.get("distance_m") is not None
            else "Delivered."
        )
    else:
        headline = "Order cancelled" if status is OrderStatus.CANCELLED else "Delivery failed"
        detail = ""

    promised_left = None
    if order.promised_eta_at and status not in (
        OrderStatus.DELIVERED,
        OrderStatus.CANCELLED,
        OrderStatus.FAILED,
    ):
        promised_left = _minutes(now, order.promised_eta_at)

    attribution = order.delay_attribution or None
    if attribution is None and status not in (OrderStatus.CANCELLED,):
        attribution = attribute(order, marks, await _estimated_pickup_min(session, order.id))

    await session.commit()
    return {
        "order_id": order.id,
        "status": status.value,
        "headline": headline,
        "detail": detail,
        "waiting_on": waiting_on,
        "minutes_since_placed": round(since_placed, 1),
        "riders_asked": riders_asked,
        "live_eta_min": round(remaining, 0) if remaining is not None else None,
        "promised_min_left": promised_left,
        # Only call an order late once it is under way and clearly behind.
        "running_late": (
            remaining is not None
            and promised_left is not None
            and since_placed >= 5
            and remaining > promised_left + 8
        ),
        "free_cancel": free_cancel,
        "can_cancel": status
        in (OrderStatus.PLACED, OrderStatus.ACCEPTED, OrderStatus.PREPARING, OrderStatus.READY),
        "batch": batch,
        "delivery_mode": order.delivery_mode,
        "attribution": attribution,
        "compensation": str(order.compensation or Decimal("0.00")),
        "proof": order.delivery_proof or None,
        "timeline": {key: value.isoformat() for key, value in marks.items()},
        "estimate_basis": "Live estimate from current positions at 22 km/h; not a promise.",
    }
