"""Consent-based shared delivery: one rider, two same-route orders.

Only orders whose customers chose "shared" at checkout (and paid less for it)
are ever batched, and only with another shared order from the same kitchen
whose rider has not picked up yet. The second drop must sit on roughly the
same route: the extra riding for whoever is delivered second is capped, so a
shared order is a little slower, never a surprise detour.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.geo import haversine_km
from app.domain.models import DeliveryAssignment, Order, OrderStatus, Restaurant, Rider

MAX_DROP_GAP_KM = 2.5
MAX_EXTRA_MIN_FOR_SECOND = 12.0
RIDER_SPEED_KMH = 22.0
LOCATION_FRESH = timedelta(minutes=2)
PRE_PICKUP = ("ACCEPTED", "ARRIVED_AT_RESTAURANT")


@dataclass(frozen=True)
class BatchPlan:
    partner_order: Order
    partner_assignment: DeliveryAssignment
    rider: Rider
    first_order_id: uuid.UUID
    separate_km: float
    batched_km: float
    extra_min_for_second: float

    @property
    def saved_km(self) -> float:
        return round(self.separate_km - self.batched_km, 2)


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    return haversine_km(a[0], a[1], b[0], b[1])


def plan_route(
    restaurant: tuple[float, float], drop_a: tuple[float, float], drop_b: tuple[float, float]
) -> tuple[str, float, float, float]:
    """Return (first, batched_km, separate_km, extra_min_for_second)."""
    direct_a = _km(restaurant, drop_a)
    direct_b = _km(restaurant, drop_b)
    between = _km(drop_a, drop_b)
    a_first = direct_a + between
    b_first = direct_b + between
    first = "a" if a_first <= b_first else "b"
    batched = min(a_first, b_first)
    # Two separate trips also need the rider to come back for the second bag.
    separate = direct_a * 2 + direct_b if first == "a" else direct_b * 2 + direct_a
    second_direct = direct_b if first == "a" else direct_a
    extra_min = max(0.0, (batched - second_direct) / RIDER_SPEED_KMH * 60.0) + 3.0
    return first, round(batched, 2), round(separate, 2), round(extra_min, 1)


async def find_partner(
    session: AsyncSession,
    order: Order,
    restaurant: Restaurant,
    exclude_rider_ids: set[uuid.UUID],
) -> BatchPlan | None:
    if order.delivery_mode != "shared" or order.batch_id is not None:
        return None
    rows = (
        await session.execute(
            select(DeliveryAssignment, Order, Rider)
            .join(Order, Order.id == DeliveryAssignment.order_id)
            .join(Rider, Rider.id == DeliveryAssignment.rider_id)
            .where(
                DeliveryAssignment.status.in_(PRE_PICKUP),
                Order.restaurant_id == order.restaurant_id,
                Order.delivery_mode == "shared",
                Order.status == OrderStatus.READY,
                Order.id != order.id,
            )
        )
    ).all()
    now = datetime.now(UTC)
    best: BatchPlan | None = None
    for assignment, partner, rider in rows:
        if rider.id in exclude_rider_ids:
            continue
        if len(rider.active_order_ids or []) >= rider.capacity:
            continue
        seen = rider.last_seen_at
        if seen is not None and seen.tzinfo is None:
            seen = seen.replace(tzinfo=UTC)
        if seen is None or now - seen > LOCATION_FRESH:
            continue
        if partner.batch_id is not None:
            batch_size = len(
                list(
                    (
                        await session.execute(
                            select(Order.id).where(Order.batch_id == partner.batch_id)
                        )
                    ).scalars()
                )
            )
            if batch_size >= 2:
                continue
        drop_new = (order.drop_lat, order.drop_lng)
        drop_partner = (partner.drop_lat, partner.drop_lng)
        if _km(drop_new, drop_partner) > MAX_DROP_GAP_KM:
            continue
        first, batched, separate, extra = plan_route(
            (restaurant.lat, restaurant.lng), drop_partner, drop_new
        )
        if extra > MAX_EXTRA_MIN_FOR_SECOND:
            continue
        plan = BatchPlan(
            partner_order=partner,
            partner_assignment=assignment,
            rider=rider,
            first_order_id=partner.id if first == "a" else order.id,
            separate_km=separate,
            batched_km=batched,
            extra_min_for_second=extra,
        )
        if best is None or plan.saved_km > best.saved_km:
            best = plan
    return best


def apply_plan(order: Order, plan: BatchPlan) -> None:
    batch_id = plan.partner_order.batch_id or uuid.uuid4()
    for row in (order, plan.partner_order):
        row.batch_id = batch_id
        row.batch_sequence = 1 if row.id == plan.first_order_id else 2


async def rider_batch(session: AsyncSession, rider: Rider) -> list[dict]:
    """All of the rider's open drops in delivery order, for the rider screen."""
    rows = (
        await session.execute(
            select(DeliveryAssignment, Order)
            .join(Order, Order.id == DeliveryAssignment.order_id)
            .where(
                DeliveryAssignment.rider_id == rider.id,
                DeliveryAssignment.status.in_(
                    ("ACCEPTED", "ARRIVED_AT_RESTAURANT", "PICKED_UP", "ARRIVED_AT_CUSTOMER")
                ),
            )
        )
    ).all()
    drops = [
        {
            "assignment_id": str(assignment.id),
            "order_id": str(order.id),
            "order_number": order.order_number,
            "sequence": order.batch_sequence or 1,
            "status": assignment.status,
            "delivery_address": order.delivery_address,
            "drop_lat": order.drop_lat,
            "drop_lng": order.drop_lng,
            "shared": order.delivery_mode == "shared",
        }
        for assignment, order in rows
    ]
    drops.sort(key=lambda row: row["sequence"])
    return drops
