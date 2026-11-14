from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import String, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain import service as domain_service
from app.domain.exceptions import BadRequestError, ConflictError, NotFoundError
from app.domain.geo import haversine_km
from app.domain.models import (
    CartItem,
    MenuItem,
    Order,
    OrderStatus,
    Restaurant,
    RestaurantStaff,
    Rider,
    User,
)
from app.marketplace import notifications
from app.marketplace.dispatch import create_offer
from app.marketplace.schemas import (
    MarketOrderOut,
    MenuPatch,
    RestaurantAnalyticsOut,
    RestaurantMenuItemOut,
)
from app.marketplace.serializers import order_out
from app.nutrition import service as nutrition_service
from app.rescue import service as rescue_service

ACTIVE_RESTAURANT_STATUSES = (
    OrderStatus.PLACED,
    OrderStatus.ACCEPTED,
    OrderStatus.PREPARING,
    OrderStatus.READY,
)


def _now() -> datetime:
    return datetime.now(UTC)


def menu_item_out(item: MenuItem, rescue: dict | None = None) -> RestaurantMenuItemOut:
    return RestaurantMenuItemOut(
        id=item.id,
        name=item.name,
        price=item.price,
        category=item.category,
        veg=item.veg,
        prep_complexity=item.prep_complexity,
        tags=item.tags or [],
        available=item.available,
        description=item.description,
        image_url=item.image_url,
        image_credit=item.image_credit or None,
        portion_grams=item.portion_grams,
        portion_serves=item.portion_serves,
        portion_pieces=item.portion_pieces,
        portion_method=item.portion_method,
        portion_confidence=item.portion_confidence,
        portion_photo_url=item.portion_photo_url,
        portion_verified_at=item.portion_verified_at,
        nutrition=nutrition_service.portion_view(item),
        rescue=rescue,
    )


async def menu(session: AsyncSession, restaurant: Restaurant) -> list[RestaurantMenuItemOut]:
    items = list(
        (
            await session.execute(
                select(MenuItem)
                .where(MenuItem.restaurant_id == restaurant.id)
                .order_by(MenuItem.category, MenuItem.name)
            )
        ).scalars()
    )
    await nutrition_service.ensure_for_items(session, items)
    live = await rescue_service.live_for_items(session, [item.id for item in items])
    return [
        menu_item_out(
            item,
            rescue_service.listing_out(live[item.id], item) if item.id in live else None,
        )
        for item in items
    ]


async def update_menu_item(
    session: AsyncSession,
    restaurant: Restaurant,
    item_id: UUID,
    payload: MenuPatch,
) -> RestaurantMenuItemOut:
    item = await session.get(MenuItem, item_id)
    if item is None or item.restaurant_id != restaurant.id:
        raise NotFoundError("menu item not found")
    if payload.available is False and item.available:
        in_carts = await session.scalar(
            select(func.count()).select_from(CartItem).where(CartItem.menu_item_id == item.id)
        )
        if in_carts:
            raise ConflictError(
                "this item is in an active cart; keep it available until carts are cleared"
            )
        item.available = False
    elif payload.available is not None:
        item.available = payload.available
    if payload.price is not None:
        item.price = payload.price
    if payload.description is not None:
        item.description = payload.description
    await session.commit()
    await session.refresh(item)
    return menu_item_out(item)


async def _order_view(
    session: AsyncSession, order: Order, restaurant: Restaurant
) -> MarketOrderOut:
    rider_name = None
    if order.rider_id is not None:
        rider = await session.get(Rider, order.rider_id)
        rider_name = rider.name if rider is not None else None
    return order_out(order, restaurant_name=restaurant.name, rider_name=rider_name)


async def orders(
    session: AsyncSession,
    restaurant: Restaurant,
    status: OrderStatus | None = None,
    limit: int = 50,
) -> list[MarketOrderOut]:
    stmt = (
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.restaurant_id == restaurant.id)
        .order_by(Order.placed_at.desc())
        .limit(limit)
    )
    if status is not None:
        stmt = stmt.where(Order.status == status)
    rows = list((await session.execute(stmt)).scalars().all())
    return [await _order_view(session, order, restaurant) for order in rows]


async def _owned_order(
    session: AsyncSession, restaurant: Restaurant, order_id: UUID
) -> Order:
    order = await domain_service.get_order(session, order_id)
    if order.restaurant_id != restaurant.id:
        raise NotFoundError("order not found")
    return order


async def _notify_customer(
    session: AsyncSession,
    order: Order,
    type_: str,
    title: str,
    body: str,
) -> None:
    row = await notifications.add(session, order.customer_id, type_, title, body, order.id)
    await session.commit()
    await notifications.publish([row])


async def accept_order(
    session: AsyncSession, restaurant: Restaurant, order_id: UUID
) -> MarketOrderOut:
    order = await _owned_order(session, restaurant, order_id)
    if order.status is not OrderStatus.PLACED:
        raise ConflictError("only new orders can be accepted")
    order = await domain_service.advance_order(
        session,
        order.id,
        OrderStatus.ACCEPTED,
        actor=f"restaurant:{restaurant.id}",
    )
    await _notify_customer(
        session,
        order,
        "ORDER_ACCEPTED",
        "Restaurant accepted your order",
        f"{restaurant.name} is preparing {order.order_number or order.id}.",
    )
    return await _order_view(session, order, restaurant)


async def reject_order(
    session: AsyncSession, restaurant: Restaurant, order_id: UUID, reason: str | None
) -> MarketOrderOut:
    order = await _owned_order(session, restaurant, order_id)
    if order.status is not OrderStatus.PLACED:
        raise ConflictError("only new orders can be rejected")
    order = await domain_service.advance_order(
        session,
        order.id,
        OrderStatus.CANCELLED,
        actor=f"restaurant:{restaurant.id}",
        reason=reason or "restaurant is unable to accept the order",
    )
    await _notify_customer(
        session,
        order,
        "ORDER_REJECTED",
        "Order could not be accepted",
        (
            f"{restaurant.name} cancelled {order.order_number or order.id}. "
            "Any online payment is refunded in the demo."
        ),
    )
    rows = await notifications.notify_admins(
        session,
        "ORDER_REJECTED",
        "Restaurant rejected an order",
        f"{order.order_number or order.id} at {restaurant.name}.",
        order.id,
    )
    await session.commit()
    await notifications.publish(rows)
    return await _order_view(session, order, restaurant)


async def start_preparing(
    session: AsyncSession, restaurant: Restaurant, order_id: UUID
) -> MarketOrderOut:
    order = await _owned_order(session, restaurant, order_id)
    if order.status is not OrderStatus.ACCEPTED:
        raise ConflictError("accept the order before starting preparation")
    order = await domain_service.advance_order(
        session,
        order.id,
        OrderStatus.PREPARING,
        actor=f"restaurant:{restaurant.id}",
    )
    await _notify_customer(
        session,
        order,
        "ORDER_PREPARING",
        "Your food is being prepared",
        f"{restaurant.name} is cooking {order.order_number or order.id}.",
    )
    return await _order_view(session, order, restaurant)


async def mark_ready(
    session: AsyncSession, restaurant: Restaurant, order_id: UUID
) -> MarketOrderOut:
    order = await _owned_order(session, restaurant, order_id)
    if order.status is not OrderStatus.PREPARING:
        raise ConflictError("start preparing the order before marking it ready")
    order = await domain_service.advance_order(
        session,
        order.id,
        OrderStatus.READY,
        actor=f"restaurant:{restaurant.id}",
    )
    await _notify_customer(
        session,
        order,
        "ORDER_READY",
        "Order ready for pickup",
        f"{restaurant.name} has packed {order.order_number or order.id}. Finding a rider.",
    )
    await create_offer(session, order)
    order = await domain_service.get_order(session, order.id)
    return await _order_view(session, order, restaurant)


async def analytics(
    session: AsyncSession, restaurant: Restaurant
) -> RestaurantAnalyticsOut:
    start_today = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    active = await session.scalar(
        select(func.count())
        .select_from(Order)
        .where(
            Order.restaurant_id == restaurant.id,
            Order.status.in_(ACTIVE_RESTAURANT_STATUSES),
        )
    )
    completed_rows = (
        await session.execute(
            select(Order)
            .where(
                Order.restaurant_id == restaurant.id,
                Order.status == OrderStatus.DELIVERED,
                Order.actual_delivery_at >= start_today,
            )
        )
    ).scalars().all()
    revenue = sum(
        (order.total_price for order in completed_rows), start=Decimal("0.00")
    )
    prep_minutes = [
        (order.actual_delivery_at - order.placed_at).total_seconds() / 60.0
        for order in completed_rows
        if order.actual_delivery_at is not None
    ]
    item_count = await session.scalar(
        select(func.count()).select_from(MenuItem).where(MenuItem.restaurant_id == restaurant.id)
    )
    available_count = await session.scalar(
        select(func.count())
        .select_from(MenuItem)
        .where(MenuItem.restaurant_id == restaurant.id, MenuItem.available.is_(True))
    )
    return RestaurantAnalyticsOut(
        active_orders=int(active or 0),
        completed_today=len(completed_rows),
        revenue_today=revenue,
        average_prep_min=(
            round(sum(prep_minutes) / len(prep_minutes), 1) if prep_minutes else None
        ),
        menu_items=int(item_count or 0),
        available_items=int(available_count or 0),
        rating=restaurant.rating,
        rating_count=restaurant.rating_count,
    )


async def browse(
    session: AsyncSession,
    lat: float | None = None,
    lng: float | None = None,
    q: str | None = None,
    cuisine: str | None = None,
    veg: bool | None = None,
    max_delivery_fee: Decimal | None = None,
    min_rating: float | None = None,
) -> list[tuple[Restaurant, float | None]]:
    stmt = select(Restaurant).where(Restaurant.is_active.is_(True))
    if q:
        # Dish-first search: a kitchen matches on its name, cuisine or any dish.
        dish_ids = select(MenuItem.restaurant_id).where(
            MenuItem.name.ilike(f"%{q}%"), MenuItem.available.is_(True)
        )
        stmt = stmt.where(
            Restaurant.name.ilike(f"%{q}%")
            | Restaurant.id.in_(dish_ids)
            | func.cast(Restaurant.cuisine, String).ilike(f"%{q}%")
        )
    if cuisine:
        stmt = stmt.where(Restaurant.cuisine.contains([cuisine]))
    if min_rating is not None:
        stmt = stmt.where(Restaurant.rating >= min_rating)
    if max_delivery_fee is not None:
        stmt = stmt.where(Restaurant.delivery_fee <= max_delivery_fee)
    rows = list((await session.execute(stmt.order_by(Restaurant.name))).scalars().all())
    if veg:
        veg_ids = set(
            (
                await session.execute(
                    select(MenuItem.restaurant_id)
                    .where(MenuItem.veg.is_(True), MenuItem.available.is_(True))
                    .distinct()
                )
            ).scalars()
        )
        rows = [restaurant for restaurant in rows if restaurant.id in veg_ids]
    results: list[tuple[Restaurant, float | None]] = []
    for restaurant in rows:
        distance = (
            haversine_km(lat, lng, restaurant.lat, restaurant.lng)
            if lat is not None and lng is not None
            else None
        )
        results.append((restaurant, distance))
    results.sort(
        key=lambda pair: pair[1] if pair[1] is not None else 0.0,
    )
    return results


async def staff_ids(session: AsyncSession, restaurant_id: UUID) -> list[UUID]:
    return list(
        (
            await session.execute(
                select(RestaurantStaff.user_id).where(
                    RestaurantStaff.restaurant_id == restaurant_id
                )
            )
        ).scalars()
    )


async def manager_contact(session: AsyncSession, restaurant_id: UUID) -> User | None:
    manager = (
        await session.execute(
            select(User)
            .join(RestaurantStaff, RestaurantStaff.user_id == User.id)
            .where(RestaurantStaff.restaurant_id == restaurant_id)
        )
    ).scalars().first()
    return manager


async def check_accepting(restaurant: Restaurant) -> None:
    if not restaurant.is_active:
        raise BadRequestError("restaurant is not accepting orders")
