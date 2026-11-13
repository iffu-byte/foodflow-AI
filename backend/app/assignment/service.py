from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assignment.scoring import Candidate, rank_candidates
from app.domain import service as domain_service
from app.domain.exceptions import BadRequestError, ConflictError, NotFoundError
from app.domain.models import Order, OrderEvent, OrderStatus, Restaurant, Rider, RiderStatus
from app.realtime import service as realtime_service

DISPATCHABLE_STATUS = OrderStatus.READY


async def _prepare(session: AsyncSession, order_id: UUID) -> tuple[Order, Restaurant]:
    order = await domain_service.get_order(session, order_id)
    if order.status is not DISPATCHABLE_STATUS:
        raise BadRequestError("order is not ready for dispatch")
    if order.rider_id is not None:
        raise ConflictError("order is already assigned to a rider")
    restaurant = await session.get(Restaurant, order.restaurant_id)
    if restaurant is None:
        raise NotFoundError("restaurant not found")
    return order, restaurant


async def _rank(session: AsyncSession, order: Order, restaurant: Restaurant) -> list[Candidate]:
    riders = list((await session.execute(select(Rider))).scalars().all())
    return rank_candidates(order, riders, restaurant.lat, restaurant.lng)


async def _lock_eligible_candidate(
    session: AsyncSession,
    order: Order,
    restaurant: Restaurant,
    candidates: list[Candidate],
) -> Candidate | None:
    """Lock and re-score a candidate before mutating its active assignment list."""
    for candidate in candidates:
        rider = (
            await session.execute(
                select(Rider).where(Rider.id == candidate.rider.id).with_for_update()
            )
        ).scalar_one_or_none()
        if rider is None:
            continue
        current = rank_candidates(order, [rider], restaurant.lat, restaurant.lng)
        if current:
            return current[0]
    return None


async def list_candidates(session: AsyncSession, order_id: UUID) -> list[Candidate]:
    order, restaurant = await _prepare(session, order_id)
    return await _rank(session, order, restaurant)


async def assign_order(
    session: AsyncSession,
    order_id: UUID,
    rider_id: UUID | None = None,
) -> tuple[Order, Candidate]:
    order = await domain_service.get_order(session, order_id, for_update=True)
    if order.status is not DISPATCHABLE_STATUS:
        raise BadRequestError("order is not ready for dispatch")
    if order.rider_id is not None:
        raise ConflictError("order is already assigned to a rider")

    restaurant = await session.get(Restaurant, order.restaurant_id)
    if restaurant is None:
        raise NotFoundError("restaurant not found")

    candidates = await _rank(session, order, restaurant)
    if rider_id is None:
        if not candidates:
            raise ConflictError("no riders available for dispatch")
        candidate = candidates[0]
    else:
        rider = await session.get(Rider, rider_id)
        if rider is None:
            raise NotFoundError("rider not found")
        candidate = next((item for item in candidates if item.rider.id == rider_id), None)
        if candidate is None:
            raise BadRequestError("rider is not eligible for dispatch")

    candidate = await _lock_eligible_candidate(session, order, restaurant, candidates)
    if candidate is None:
        if rider_id is not None:
            raise ConflictError("rider is no longer eligible for dispatch")
        raise ConflictError("no riders available for dispatch")

    rider = candidate.rider
    rider.active_order_ids = [
        *(existing for existing in rider.active_order_ids if existing != str(order.id)),
        str(order.id),
    ]
    rider.status = RiderStatus.TO_PICKUP
    order.rider_id = rider.id

    event = OrderEvent(
        order_id=order.id,
        type="rider_assigned",
        payload={
            "rider_id": str(rider.id),
            "auto": rider_id is None,
            "score": candidate.score,
            "pickup_distance_km": candidate.pickup_distance_km,
            "pickup_eta_min": candidate.pickup_eta_min,
            "reasons": candidate.reasons,
        },
    )
    session.add(event)
    await session.commit()

    order = await domain_service.get_order(session, order_id)
    await realtime_service.publish_order_event(order, event)
    return order, candidate
