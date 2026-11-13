from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import isfinite
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assignment.scoring import Candidate, rank_candidates
from app.domain import service as domain_service
from app.domain.exceptions import ConflictError, NotFoundError
from app.domain.geo import haversine_km
from app.domain.models import (
    DeliveryAssignment,
    DeliveryEarning,
    EtaPrediction,
    Order,
    OrderEvent,
    OrderStatus,
    Restaurant,
    RestaurantStaff,
    Rider,
    RiderStatus,
    TrackingPoint,
    User,
)
from app.marketplace import notifications, pricing
from app.marketplace.schemas import (
    AssignmentActionOut,
    DeliveryActionIn,
    EarningsEntryOut,
    EarningsOut,
    MarketOrderOut,
    OfferOut,
    RiderProfileOut,
)
from app.marketplace.serializers import order_out
from app.realtime import service as realtime_service
from app.routing.base import LatLng
from app.routing.service import get_router

OFFER_TTL_SECONDS = 20
LOCATION_FRESH_MINUTES = 2
MAX_PICKUP_DISTANCE_KM = 5.0
ROUTED_CANDIDATE_LIMIT = 12
PICKUP_SPEED_KMH = 24.0
DELIVERY_SPEED_KMH = 22.0
BASE_EARNING = Decimal("25.00")
PER_KM_EARNING = Decimal("8.00")
ACTIVE_STATUSES = (
    "ACCEPTED",
    "ARRIVED_AT_RESTAURANT",
    "PICKED_UP",
    "ARRIVED_AT_CUSTOMER",
)


def _now() -> datetime:
    return datetime.now(UTC)


def _money(value: Decimal) -> Decimal:
    return pricing.money(value)


def _is_fresh(rider: Rider) -> bool:
    if rider.last_seen_at is None:
        return False
    return _now() - rider.last_seen_at <= timedelta(minutes=LOCATION_FRESH_MINUTES)


async def _rank_nearby_riders(
    order: Order, riders: list[Rider], restaurant: Restaurant
) -> list[Candidate]:
    """Rank nearby fresh riders using road travel time when available.

    A fast haversine pass limits routing to a small candidate set.  The routing
    interface always has a fallback, and a defensive catch preserves dispatch
    if even that dependency fails.
    """
    candidates = [
        candidate
        for candidate in rank_candidates(order, riders, restaurant.lat, restaurant.lng)
        if candidate.pickup_distance_km <= MAX_PICKUP_DISTANCE_KM
    ][:ROUTED_CANDIDATE_LIMIT]
    if not candidates:
        return []

    try:
        durations = await get_router().matrix(
            [LatLng(candidate.rider.lat, candidate.rider.lng) for candidate in candidates],
            [LatLng(restaurant.lat, restaurant.lng)],
        )
    except Exception:
        return candidates

    routed: list[Candidate] = []
    for candidate, row in zip(candidates, durations, strict=False):
        duration_s = row[0] if row else float("inf")
        if not isfinite(duration_s) or duration_s < 0:
            routed.append(candidate)
            continue
        pickup_eta_min = round(duration_s / 60.0, 1)
        routed.append(
            replace(
                candidate,
                pickup_eta_min=pickup_eta_min,
                score=round(candidate.score - candidate.pickup_eta_min + pickup_eta_min, 2),
                reasons=[*candidate.reasons, f"{pickup_eta_min:.1f} min route ETA"],
            )
        )
    return sorted(routed, key=lambda candidate: (candidate.score, candidate.rider.name))


async def _order_view(session: AsyncSession, order: Order) -> MarketOrderOut:
    restaurant = await session.get(Restaurant, order.restaurant_id)
    rider = await session.get(Rider, order.rider_id) if order.rider_id else None
    return order_out(
        order,
        restaurant_name=restaurant.name if restaurant else "Restaurant",
        rider_name=rider.name if rider else None,
    )


def _offer_out(
    assignment: DeliveryAssignment,
    order: Order,
    restaurant: Restaurant,
    candidate: Candidate,
) -> OfferOut:
    delivery_km = haversine_km(
        restaurant.lat, restaurant.lng, order.drop_lat, order.drop_lng
    )
    delivery_min = delivery_km / DELIVERY_SPEED_KMH * 60.0
    earning = _money(
        BASE_EARNING
        + PER_KM_EARNING * Decimal(str(round(delivery_km, 2)))
        + Decimal(str(round(candidate.pickup_distance_km * 4, 2)))
    )
    assignment.estimated_pickup_min = candidate.pickup_eta_min
    assignment.estimated_delivery_min = round(delivery_min, 1)
    return OfferOut(
        assignment_id=assignment.id,
        order_id=order.id,
        order_number=order.order_number,
        restaurant_name=restaurant.name,
        restaurant_address=restaurant.address,
        pickup_lat=restaurant.lat,
        pickup_lng=restaurant.lng,
        drop_lat=order.drop_lat,
        drop_lng=order.drop_lng,
        pickup_distance_km=candidate.pickup_distance_km,
        pickup_eta_min=candidate.pickup_eta_min,
        delivery_distance_km=round(delivery_km, 2),
        estimated_delivery_min=round(candidate.pickup_eta_min + delivery_min, 1),
        estimated_earnings=earning,
        expires_at=assignment.expires_at,
        offered_at=assignment.offered_at,
    )


async def _open_offer(
    session: AsyncSession, order_id: UUID
) -> DeliveryAssignment | None:
    return (
        await session.execute(
            select(DeliveryAssignment)
            .where(
                DeliveryAssignment.order_id == order_id,
                DeliveryAssignment.status == "OFFERED",
            )
            .order_by(DeliveryAssignment.offered_at.desc())
        )
    ).scalars().first()


async def create_offer(
    session: AsyncSession, order: Order, *, rider_id: UUID | None = None
) -> OfferOut | None:
    if order.status is not OrderStatus.READY or order.rider_id is not None:
        return None

    existing = await _open_offer(session, order.id)
    if existing is not None:
        if existing.expires_at > _now():
            restaurant = await session.get(Restaurant, order.restaurant_id)
            rider = await session.get(Rider, existing.rider_id)
            if restaurant is None or rider is None:
                return None
            candidate = Candidate(
                rider=rider,
                score=0.0,
                pickup_distance_km=haversine_km(
                    rider.lat, rider.lng, restaurant.lat, restaurant.lng
                ),
                pickup_eta_min=existing.estimated_pickup_min,
                active_load=len(rider.active_order_ids or []),
                reasons=[],
            )
            return _offer_out(existing, order, restaurant, candidate)
        existing.status = "EXPIRED"
        await session.flush()

    restaurant = await session.get(Restaurant, order.restaurant_id)
    if restaurant is None:
        raise NotFoundError("restaurant not found")

    rejected = set(
        (
            await session.execute(
                select(DeliveryAssignment.rider_id).where(
                    DeliveryAssignment.order_id == order.id,
                    DeliveryAssignment.status.in_(("REJECTED", "EXPIRED")),
                )
            )
        ).scalars()
    )
    riders = list(
        (
            await session.execute(
                select(Rider).where(
                    Rider.verification_status == "APPROVED",
                    Rider.status != RiderStatus.OFFLINE,
                )
            )
        )
        .scalars()
        .all()
    )
    fresh = [rider for rider in riders if _is_fresh(rider) and rider.id not in rejected]
    candidates = await _rank_nearby_riders(order, fresh, restaurant)
    if rider_id is not None:
        candidates = [item for item in candidates if item.rider.id == rider_id]
    if not candidates:
        rows = await notifications.notify_admins(
            session,
            "NO_RIDERS_AVAILABLE",
            "No riders available",
            f"{order.order_number or order.id} is ready but no rider could be offered it.",
            order.id,
        )
        await session.commit()
        await notifications.publish(rows)
        return None

    candidate = candidates[0]
    assignment = DeliveryAssignment(
        order_id=order.id,
        rider_id=candidate.rider.id,
        status="OFFERED",
        offered_at=_now(),
        expires_at=_now() + timedelta(seconds=OFFER_TTL_SECONDS),
    )
    session.add(assignment)
    await session.flush()
    offer = _offer_out(assignment, order, restaurant, candidate)
    notification = await notifications.add(
        session,
        candidate.rider.user_id,
        "DELIVERY_OFFER",
        "New delivery request",
        f"{restaurant.name} · earn {offer.estimated_earnings} · {offer.delivery_distance_km} km",
        order.id,
    )
    await session.commit()
    await notifications.publish([notification])
    return offer


async def sweep_expired_offers(session: AsyncSession) -> int:
    """Expire timed-out offers and continue dispatch without a rider request.

    ``SKIP LOCKED`` lets multiple API replicas run this sweep safely: only one
    worker can expire and advance a particular offer.
    """
    assignments = list(
        (
            await session.execute(
                select(DeliveryAssignment)
                .where(
                    DeliveryAssignment.status == "OFFERED",
                    DeliveryAssignment.expires_at <= _now(),
                )
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    if not assignments:
        return 0

    order_ids = list({assignment.order_id for assignment in assignments})
    for assignment in assignments:
        assignment.status = "EXPIRED"
    await session.commit()

    advanced = 0
    for order_id in order_ids:
        order = await domain_service.get_order(session, order_id, for_update=True)
        if await create_offer(session, order) is not None:
            advanced += 1
    return advanced


async def offers_for_rider(session: AsyncSession, rider: Rider) -> list[OfferOut]:
    rows = list(
        (
            await session.execute(
                select(DeliveryAssignment)
                .where(
                    DeliveryAssignment.rider_id == rider.id,
                    DeliveryAssignment.status == "OFFERED",
                )
                .order_by(DeliveryAssignment.offered_at)
            )
        )
        .scalars()
        .all()
    )
    results: list[OfferOut] = []
    expired_order_ids: list[UUID] = []
    for assignment in rows:
        if assignment.expires_at <= _now():
            assignment.status = "EXPIRED"
            expired_order_ids.append(assignment.order_id)
            continue
        order = await domain_service.get_order(session, assignment.order_id)
        restaurant = await session.get(Restaurant, order.restaurant_id)
        if restaurant is None:
            continue
        results.append(
            _offer_out(
                assignment,
                order,
                restaurant,
                Candidate(
                    rider=rider,
                    score=0.0,
                    pickup_distance_km=haversine_km(
                        rider.lat, rider.lng, restaurant.lat, restaurant.lng
                    ),
                    pickup_eta_min=assignment.estimated_pickup_min,
                    active_load=len(rider.active_order_ids or []),
                    reasons=[],
                ),
            )
        )
    await session.commit()
    # This is a fallback for an online rider client.  The API's background
    # sweeper performs the same handoff even when no rider screen is open.
    for order_id in expired_order_ids:
        order = await domain_service.get_order(session, order_id)
        await create_offer(session, order)
    return results


async def accept_offer(
    session: AsyncSession, rider: Rider, assignment_id: UUID
) -> AssignmentActionOut:
    assignment = (
        await session.execute(
            select(DeliveryAssignment)
            .where(DeliveryAssignment.id == assignment_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if assignment is None or assignment.rider_id != rider.id:
        raise NotFoundError("delivery offer not found")
    if assignment.status != "OFFERED":
        raise ConflictError("this offer is no longer open")
    if assignment.expires_at <= _now():
        assignment.status = "EXPIRED"
        await session.commit()
        raise ConflictError("this offer has expired")

    order = await domain_service.get_order(session, assignment.order_id, for_update=True)
    if order.status is not OrderStatus.READY or order.rider_id is not None:
        assignment.status = "EXPIRED"
        await session.commit()
        raise ConflictError("this order is no longer available for assignment")

    locked_rider = (
        await session.execute(select(Rider).where(Rider.id == rider.id).with_for_update())
    ).scalar_one_or_none()
    if locked_rider is None:
        raise NotFoundError("rider not found")
    if (
        locked_rider.verification_status != "APPROVED"
        or locked_rider.status is RiderStatus.OFFLINE
        or len(locked_rider.active_order_ids or []) >= locked_rider.capacity
    ):
        assignment.status = "EXPIRED"
        await session.commit()
        raise ConflictError("you are no longer eligible for this delivery")
    rider = locked_rider

    assignment.status = "ACCEPTED"
    assignment.accepted_at = _now()
    order.rider_id = rider.id
    rider.active_order_ids = [
        *(item for item in rider.active_order_ids or [] if item != str(order.id)),
        str(order.id),
    ]
    rider.status = RiderStatus.TO_PICKUP
    event = OrderEvent(
        order_id=order.id,
        type="rider_assigned",
        payload={
            "rider_id": str(rider.id),
            "assignment_id": str(assignment.id),
            "rider_name": rider.name,
        },
    )
    session.add(event)
    manager_id = await session.scalar(
        select(RestaurantStaff.user_id).where(
            RestaurantStaff.restaurant_id == order.restaurant_id
        )
    )
    rows = [
        await notifications.add(
            session,
            order.customer_id,
            "RIDER_ASSIGNED",
            "Rider assigned",
            f"{rider.name} is heading to the restaurant for {order.order_number or order.id}.",
            order.id,
        )
    ]
    if manager_id is not None:
        rows.append(
            await notifications.add(
                session,
                manager_id,
                "RIDER_ASSIGNED",
                "Rider on the way",
                f"{rider.name} accepted the pickup for {order.order_number or order.id}.",
                order.id,
            )
        )
    await session.commit()
    order = await domain_service.get_order(session, order.id)
    await realtime_service.publish_order_event(order, event)
    await notifications.publish(rows)
    return AssignmentActionOut(
        assignment_id=assignment.id,
        status=assignment.status,
        order=await _order_view(session, order),
    )


async def reject_offer(
    session: AsyncSession,
    rider: Rider,
    assignment_id: UUID,
    reason: str | None,
) -> dict:
    assignment = (
        await session.execute(
            select(DeliveryAssignment)
            .where(DeliveryAssignment.id == assignment_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if assignment is None or assignment.rider_id != rider.id:
        raise NotFoundError("delivery offer not found")
    if assignment.status != "OFFERED":
        raise ConflictError("this offer is no longer open")
    assignment.status = "REJECTED"
    assignment.rejection_reason = reason or "rejected by rider"
    order = await domain_service.get_order(session, assignment.order_id)
    rows = await notifications.notify_admins(
        session,
        "OFFER_REJECTED",
        "Rider rejected an offer",
        f"{rider.name} rejected {order.order_number or order.id}.",
        order.id,
    )
    await session.commit()
    await notifications.publish(rows)
    next_offer = await create_offer(session, await domain_service.get_order(session, order.id))
    return {"status": assignment.status, "next_offer": next_offer}


async def _assignment_for(
    session: AsyncSession, rider: Rider, assignment_id: UUID
) -> DeliveryAssignment:
    assignment = (
        await session.execute(
            select(DeliveryAssignment).where(
                DeliveryAssignment.id == assignment_id,
                DeliveryAssignment.rider_id == rider.id,
            )
        )
    ).scalar_one_or_none()
    if assignment is None:
        raise NotFoundError("delivery assignment not found")
    return assignment


async def arrived_at_restaurant(
    session: AsyncSession, rider: Rider, assignment_id: UUID
) -> AssignmentActionOut:
    assignment = await _assignment_for(session, rider, assignment_id)
    if assignment.status != "ACCEPTED":
        raise ConflictError("assignment is not awaiting restaurant arrival")
    assignment.status = "ARRIVED_AT_RESTAURANT"
    assignment.arrived_restaurant_at = _now()
    order = await domain_service.get_order(session, assignment.order_id)
    event = OrderEvent(
        order_id=order.id,
        type="rider_arrived_restaurant",
        payload={"rider_id": str(rider.id), "assignment_id": str(assignment.id)},
    )
    session.add(event)
    rows = [
        await notifications.add(
            session,
            order.customer_id,
            "RIDER_AT_RESTAURANT",
            "Rider at the restaurant",
            f"{rider.name} is collecting your order.",
            order.id,
        )
    ]
    await session.commit()
    await realtime_service.publish_order_event(order, event)
    await notifications.publish(rows)
    return AssignmentActionOut(
        assignment_id=assignment.id,
        status=assignment.status,
        order=await _order_view(session, order),
    )


async def pickup(
    session: AsyncSession, rider: Rider, assignment_id: UUID
) -> AssignmentActionOut:
    assignment = await _assignment_for(session, rider, assignment_id)
    if assignment.status != "ARRIVED_AT_RESTAURANT":
        raise ConflictError("mark arrival at the restaurant before pickup")
    assignment.status = "PICKED_UP"
    assignment.pickup_at = _now()
    order = await domain_service.advance_order(
        session,
        assignment.order_id,
        OrderStatus.PICKED_UP,
        actor=f"rider:{rider.id}",
        rider_id=rider.id,
    )
    event = OrderEvent(
        order_id=order.id,
        type="order_picked_up",
        payload={"rider_id": str(rider.id), "assignment_id": str(assignment.id)},
    )
    session.add(event)
    rows = [
        await notifications.add(
            session,
            order.customer_id,
            "ORDER_PICKED_UP",
            "Your order is on the way",
            f"{rider.name} picked up {order.order_number or order.id}.",
            order.id,
        )
    ]
    await session.commit()
    await realtime_service.publish_order_event(order, event)
    await notifications.publish(rows)
    return AssignmentActionOut(
        assignment_id=assignment.id,
        status=assignment.status,
        order=await _order_view(session, order),
    )


async def arrived_at_customer(
    session: AsyncSession, rider: Rider, assignment_id: UUID
) -> AssignmentActionOut:
    assignment = await _assignment_for(session, rider, assignment_id)
    if assignment.status != "PICKED_UP":
        raise ConflictError("pickup the order before marking customer arrival")
    assignment.status = "ARRIVED_AT_CUSTOMER"
    assignment.arrived_customer_at = _now()
    order = await domain_service.get_order(session, assignment.order_id)
    event = OrderEvent(
        order_id=order.id,
        type="rider_arrived_customer",
        payload={"rider_id": str(rider.id), "assignment_id": str(assignment.id)},
    )
    session.add(event)
    rows = [
        await notifications.add(
            session,
            order.customer_id,
            "RIDER_ARRIVED",
            "Your rider has arrived",
            f"{rider.name} is at your delivery address.",
            order.id,
        )
    ]
    await session.commit()
    await realtime_service.publish_order_event(order, event)
    await notifications.publish(rows)
    return AssignmentActionOut(
        assignment_id=assignment.id,
        status=assignment.status,
        order=await _order_view(session, order),
    )


async def complete(
    session: AsyncSession,
    rider: Rider,
    assignment_id: UUID,
    payload: DeliveryActionIn | None = None,
) -> AssignmentActionOut:
    assignment = await _assignment_for(session, rider, assignment_id)
    if assignment.status != "ARRIVED_AT_CUSTOMER":
        raise ConflictError("mark customer arrival before completing delivery")

    order = await domain_service.get_order(session, assignment.order_id)
    if order.status is not OrderStatus.PICKED_UP:
        raise ConflictError("order has not been picked up")
    distance = order.delivery_distance_km or haversine_km(
        rider.lat, rider.lng, order.drop_lat, order.drop_lng
    )
    earning_amount = _money(
        BASE_EARNING + PER_KM_EARNING * Decimal(str(round(distance, 2)))
    )
    assignment.status = "COMPLETED"
    assignment.completed_at = _now()
    order.actual_delivery_at = _now()
    if order.payment_method == "COD":
        order.payment_status = "PAID"
    session.add(
        DeliveryEarning(
            order_id=order.id,
            rider_id=rider.id,
            amount=earning_amount,
            distance_km=round(distance, 2),
        )
    )
    prediction = (
        await session.execute(
            select(EtaPrediction)
            .where(EtaPrediction.order_id == order.id)
            .order_by(EtaPrediction.created_at.desc())
        )
    ).scalars().first()
    if prediction is not None:
        prediction.actual_minutes = round(
            (order.actual_delivery_at - order.placed_at).total_seconds() / 60.0, 1
        )

    order = await domain_service.advance_order(
        session,
        order.id,
        OrderStatus.DELIVERED,
        actor=f"rider:{rider.id}",
        reason=payload.reason if payload else None,
        rider_id=rider.id,
    )
    event = OrderEvent(
        order_id=order.id,
        type="order_delivered",
        payload={
            "rider_id": str(rider.id),
            "assignment_id": str(assignment.id),
            "earning": str(earning_amount),
            "distance_km": round(distance, 2),
        },
    )
    session.add(event)
    rows = [
        await notifications.add(
            session,
            order.customer_id,
            "ORDER_DELIVERED",
            "Enjoy your meal",
            f"{order.order_number or order.id} has been delivered.",
            order.id,
        )
    ]
    rows.extend(
        await notifications.notify_admins(
            session,
            "ORDER_DELIVERED",
            "Delivery completed",
            f"{order.order_number or order.id} completed by {rider.name}.",
            order.id,
        )
    )
    await session.commit()
    await realtime_service.publish_order_event(order, event)
    await notifications.publish(rows)
    return AssignmentActionOut(
        assignment_id=assignment.id,
        status=assignment.status,
        order=await _order_view(session, order),
    )


async def _assignment_stats(
    session: AsyncSession, rider: Rider
) -> tuple[Decimal, Decimal, Decimal, int, int]:
    now = _now()
    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_week = start_today - timedelta(days=start_today.weekday())
    start_month = start_today.replace(day=1)

    async def total_since(moment: datetime) -> Decimal:
        value = await session.scalar(
            select(func.sum(DeliveryEarning.amount)).where(
                DeliveryEarning.rider_id == rider.id,
                DeliveryEarning.created_at >= moment,
            )
        )
        return _money(Decimal(str(value or 0)))

    today = await total_since(start_today)
    week = await total_since(start_week)
    month = await total_since(start_month)
    today_count = await session.scalar(
        select(func.count(DeliveryEarning.id)).where(
            DeliveryEarning.rider_id == rider.id,
            DeliveryEarning.created_at >= start_today,
        )
    )
    total_count = await session.scalar(
        select(func.count(DeliveryEarning.id)).where(DeliveryEarning.rider_id == rider.id)
    )
    return today, week, month, int(today_count or 0), int(total_count or 0)


async def rider_profile(session: AsyncSession, rider: Rider) -> RiderProfileOut:
    user = await session.get(User, rider.user_id)
    today, week, month, today_count, total_count = await _assignment_stats(
        session, rider
    )
    return RiderProfileOut(
        id=rider.id,
        user_id=rider.user_id,
        name=rider.name,
        email=user.email if user else None,
        phone=user.phone if user else None,
        lat=rider.lat,
        lng=rider.lng,
        location_source=rider.location_source,
        location_accuracy_m=rider.location_accuracy_m,
        status=rider.status.value,
        vehicle=rider.vehicle,
        vehicle_registration=rider.vehicle_registration,
        capacity=rider.capacity,
        verification_status=rider.verification_status,
        average_rating=rider.average_rating,
        active_order_ids=rider.active_order_ids or [],
        last_seen_at=rider.last_seen_at,
        today_earnings=today,
        week_earnings=week,
        month_earnings=month,
        today_deliveries=today_count,
        total_deliveries=total_count,
    )


async def set_availability(
    session: AsyncSession, rider: Rider, online: bool
) -> RiderProfileOut:
    if online:
        if rider.status is RiderStatus.OFFLINE:
            rider.status = RiderStatus.IDLE
        rider.last_seen_at = _now()
    else:
        rider.status = RiderStatus.OFFLINE
    await session.commit()
    await session.refresh(rider)
    return await rider_profile(session, rider)


async def update_location(
    session: AsyncSession,
    rider: Rider,
    lat: float,
    lng: float,
    *,
    source: str = "simulated",
    accuracy_m: float | None = None,
) -> RiderProfileOut:
    rider.lat = lat
    rider.lng = lng
    rider.location_source = source
    rider.location_accuracy_m = accuracy_m
    rider.last_seen_at = _now()
    active = list(
        (
            await session.execute(
                select(DeliveryAssignment.order_id, Order.restaurant_id)
                .join(Order, Order.id == DeliveryAssignment.order_id)
                .where(
                    DeliveryAssignment.rider_id == rider.id,
                    DeliveryAssignment.status.in_(ACTIVE_STATUSES),
                )
            )
        ).all()
    )
    for order_id, _ in active:
        session.add(
            TrackingPoint(order_id=order_id, rider_id=rider.id, lat=lat, lng=lng)
        )
    await session.commit()
    await session.refresh(rider)
    if active:
        await realtime_service.publish_rider_location(rider, active)
    return await rider_profile(session, rider)


async def active_delivery(
    session: AsyncSession, rider: Rider
) -> AssignmentActionOut | None:
    assignment = (
        await session.execute(
            select(DeliveryAssignment)
            .where(
                DeliveryAssignment.rider_id == rider.id,
                DeliveryAssignment.status.in_(ACTIVE_STATUSES),
            )
            .order_by(DeliveryAssignment.offered_at.desc())
        )
    ).scalars().first()
    if assignment is None:
        return None
    order = await domain_service.get_order(session, assignment.order_id)
    return AssignmentActionOut(
        assignment_id=assignment.id,
        status=assignment.status,
        order=await _order_view(session, order),
    )


async def delivery_history(
    session: AsyncSession, rider: Rider, limit: int = 50
) -> list[MarketOrderOut]:
    assignments = list(
        (
            await session.execute(
                select(DeliveryAssignment)
                .where(
                    DeliveryAssignment.rider_id == rider.id,
                    DeliveryAssignment.status == "COMPLETED",
                )
                .order_by(DeliveryAssignment.completed_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    results = []
    for assignment in assignments:
        order = await domain_service.get_order(session, assignment.order_id)
        results.append(await _order_view(session, order))
    return results


async def earnings(session: AsyncSession, rider: Rider) -> EarningsOut:
    today, week, month, today_count, _ = await _assignment_stats(session, rider)
    rows = (
        await session.execute(
            select(DeliveryEarning, Order.order_number, Restaurant.name)
            .join(Order, Order.id == DeliveryEarning.order_id)
            .join(Restaurant, Restaurant.id == Order.restaurant_id)
            .where(DeliveryEarning.rider_id == rider.id)
            .order_by(DeliveryEarning.created_at.desc())
            .limit(50)
        )
    ).all()
    entries = [
        EarningsEntryOut(
            order_id=row.DeliveryEarning.order_id,
            order_number=row.order_number,
            restaurant_name=row.name,
            amount=row.DeliveryEarning.amount,
            distance_km=row.DeliveryEarning.distance_km,
            created_at=row.DeliveryEarning.created_at,
        )
        for row in rows
    ]
    return EarningsOut(
        today=today,
        week=week,
        month=month,
        completed_deliveries=len(entries),
        entries=entries,
    )
