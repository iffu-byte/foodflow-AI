from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.exceptions import BadRequestError, ConflictError, NotFoundError
from app.domain.geo import haversine_km
from app.domain.models import (
    Customer,
    MenuItem,
    Order,
    OrderEvent,
    OrderItem,
    OrderStatus,
    Restaurant,
    Rider,
    RiderStatus,
    User,
)
from app.domain.schemas import OrderCreate
from app.domain.state_machine import transition
from app.eta.service import estimate_for_order
from app.realtime import service as realtime_service


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def list_restaurants(
    session: AsyncSession,
    lat: float | None = None,
    lng: float | None = None,
) -> list[tuple[Restaurant, float | None]]:
    restaurants = (await session.execute(select(Restaurant))).scalars().all()
    if lat is None or lng is None:
        return [(restaurant, None) for restaurant in sorted(restaurants, key=lambda r: r.name)]

    ranked = [
        (restaurant, haversine_km(lat, lng, restaurant.lat, restaurant.lng))
        for restaurant in restaurants
    ]
    return sorted(ranked, key=lambda pair: pair[1])


async def get_menu(session: AsyncSession, restaurant_id: UUID) -> list[MenuItem]:
    restaurant = await session.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise NotFoundError("restaurant not found")

    stmt = (
        select(MenuItem)
        .where(MenuItem.restaurant_id == restaurant_id)
        .order_by(MenuItem.category, MenuItem.name)
    )
    return list((await session.execute(stmt)).scalars().all())


async def create_order(session: AsyncSession, payload: OrderCreate) -> Order:
    customer = await session.get(Customer, payload.customer_id)
    if customer is None:
        raise NotFoundError("customer not found")

    restaurant = await session.get(Restaurant, payload.restaurant_id)
    if restaurant is None:
        raise NotFoundError("restaurant not found")

    quantities: dict[UUID, int] = {}
    for entry in payload.items:
        if entry.menu_item_id in quantities:
            raise BadRequestError(f"duplicate menu item in cart: {entry.menu_item_id}")
        quantities[entry.menu_item_id] = entry.qty

    menu_items = (
        (
            await session.execute(
                select(MenuItem).where(MenuItem.id.in_(quantities.keys()))
            )
        )
        .scalars()
        .all()
    )
    found = {item.id: item for item in menu_items}
    missing = set(quantities) - set(found)
    if missing:
        raise BadRequestError(f"unknown menu items: {', '.join(str(item) for item in missing)}")

    for item in found.values():
        if item.restaurant_id != payload.restaurant_id:
            raise BadRequestError(f"menu item {item.id} does not belong to this restaurant")

    total = sum(
        (found[item_id].price * qty for item_id, qty in quantities.items()),
        start=Decimal("0.00"),
    )

    order = Order(
        customer_id=payload.customer_id,
        restaurant_id=payload.restaurant_id,
        status=OrderStatus.PLACED,
        drop_lat=payload.drop_lat if payload.drop_lat is not None else customer.home_lat,
        drop_lng=payload.drop_lng if payload.drop_lng is not None else customer.home_lng,
        deadline_at=_ensure_utc(payload.deadline_at),
        total_price=total,
    )
    for item_id, qty in quantities.items():
        menu_item = found[item_id]
        order.items.append(
            OrderItem(
                menu_item_id=menu_item.id,
                name=menu_item.name,
                qty=qty,
                unit_price=menu_item.price,
            )
        )

    session.add(order)
    await session.flush()

    placed_event = OrderEvent(
        order_id=order.id,
        type="order_placed",
        payload={
            "total_price": str(total),
            "item_count": sum(quantities.values()),
            "restaurant_id": str(payload.restaurant_id),
        },
    )
    session.add(placed_event)

    prediction = await estimate_for_order(session, order, restaurant)
    order.promised_eta_at = order.placed_at + timedelta(minutes=prediction.eta_minutes)
    meets_deadline = (
        order.promised_eta_at <= order.deadline_at
        if order.deadline_at is not None
        else None
    )
    eta_event = OrderEvent(
        order_id=order.id,
        type="eta_predicted",
        payload={
            **prediction.event_payload(),
            "promised_eta_at": order.promised_eta_at.isoformat(),
            "deadline_at": (
                order.deadline_at.isoformat() if order.deadline_at is not None else None
            ),
            "meets_deadline": meets_deadline,
        },
    )
    session.add(eta_event)
    await session.commit()
    order = await get_order(session, order.id)
    await realtime_service.publish_order_event(order, placed_event)
    await realtime_service.publish_order_event(order, eta_event)
    return order


async def get_order(
    session: AsyncSession,
    order_id: UUID,
    *,
    for_update: bool = False,
) -> Order:
    stmt = (
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items))
        .execution_options(populate_existing=True)
    )
    if for_update:
        stmt = stmt.with_for_update()
    order = (await session.execute(stmt)).scalar_one_or_none()
    if order is None:
        raise NotFoundError("order not found")
    return order


async def list_order_events(session: AsyncSession, order_id: UUID) -> list[OrderEvent]:
    await get_order(session, order_id)
    stmt = (
        select(OrderEvent)
        .where(OrderEvent.order_id == order_id)
        .order_by(OrderEvent.created_at, OrderEvent.id)
    )
    return list((await session.execute(stmt)).scalars().all())


async def _sync_rider_status(
    session: AsyncSession,
    order: Order,
    new_status: OrderStatus,
) -> None:
    if order.rider_id is None:
        return
    rider = await session.get(Rider, order.rider_id)
    if rider is None:
        return

    order_key = str(order.id)
    if new_status is OrderStatus.PICKED_UP:
        rider.status = RiderStatus.TO_DROP
        if order_key not in rider.active_order_ids:
            rider.active_order_ids = [*(rider.active_order_ids or []), order_key]
    elif new_status in (OrderStatus.DELIVERED, OrderStatus.FAILED, OrderStatus.CANCELLED):
        remaining = [
            active_id for active_id in rider.active_order_ids or [] if active_id != order_key
        ]
        rider.active_order_ids = remaining
        if not remaining:
            rider.status = RiderStatus.IDLE


async def transition_order(
    session: AsyncSession,
    order_id: UUID,
    new_status: OrderStatus,
    actor: str,
    reason: str | None = None,
    rider_id: UUID | None = None,
) -> tuple[Order, OrderEvent]:
    """Apply an order transition without committing its surrounding workflow.

    Composite flows, such as customer cancellation, can add assignment cleanup
    and notifications before committing every durable change together.
    """
    order = await get_order(session, order_id, for_update=True)

    if new_status is OrderStatus.PICKED_UP:
        if rider_id is None:
            raise BadRequestError("rider_id is required when picking up an order")
        rider = await session.get(Rider, rider_id)
        if rider is None:
            raise NotFoundError("rider not found")
        if order.rider_id is not None and order.rider_id != rider_id:
            raise ConflictError("order is already assigned to a different rider")
        if order.rider_id is None:
            order.rider_id = rider_id

    event = transition(order, new_status, actor=actor, reason=reason)
    await _sync_rider_status(session, order, new_status)
    session.add(event)
    return order, event


async def advance_order(
    session: AsyncSession,
    order_id: UUID,
    new_status: OrderStatus,
    actor: str,
    reason: str | None = None,
    rider_id: UUID | None = None,
) -> Order:
    order, event = await transition_order(
        session,
        order_id,
        new_status,
        actor,
        reason,
        rider_id,
    )
    await session.commit()
    order = await get_order(session, order_id)
    await realtime_service.publish_order_event(order, event)
    return order


async def list_orders(
    session: AsyncSession,
    *,
    status: OrderStatus | None = None,
    limit: int = 50,
) -> list[Order]:
    stmt = (
        select(Order)
        .options(selectinload(Order.items))
        .order_by(Order.placed_at.desc(), Order.id)
        .limit(limit)
    )
    if status is not None:
        stmt = stmt.where(Order.status == status)
    return list((await session.execute(stmt)).scalars().all())


async def list_customers(session: AsyncSession) -> list[tuple[Customer, User]]:
    stmt = (
        select(Customer, User)
        .join(User, User.id == Customer.user_id)
        .order_by(User.name, User.id)
    )
    rows = (await session.execute(stmt)).all()
    return [(customer, user) for customer, user in rows]


async def list_riders(session: AsyncSession) -> list[Rider]:
    stmt = select(Rider).order_by(Rider.name, Rider.id)
    return list((await session.execute(stmt)).scalars().all())


async def update_rider_location(
    session: AsyncSession,
    rider_id: UUID,
    lat: float,
    lng: float,
    *,
    source: str = "simulated",
    accuracy_m: float | None = None,
) -> Rider:
    rider = await session.get(Rider, rider_id)
    if rider is None:
        raise NotFoundError("rider not found")

    rider.lat = lat
    rider.lng = lng
    rider.location_source = source
    rider.location_accuracy_m = accuracy_m
    rider.last_seen_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(rider)

    active_orders = list(
        (
            await session.execute(
                select(Order.id, Order.restaurant_id).where(
                    Order.rider_id == rider.id,
                    Order.status == OrderStatus.PICKED_UP,
                )
            )
        )
        .all()
    )
    await realtime_service.publish_rider_location(rider, active_orders)
    return rider
