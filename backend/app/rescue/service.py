"""Rescue a Meal: surplus food sold before closing at a falling price.

The kitchen logs how many portions it prepared. The forecast compares that
with real orders so far and the recent sales pace to project what will be
left at closing, and suggests a rescue listing. A live listing's price falls
linearly from its start price to a floor as the end time approaches, so
customers see exactly what they pay now and what it will drop to.
"""

from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import BadRequestError, ConflictError, NotFoundError
from app.domain.geo import haversine_km
from app.domain.models import (
    MenuItem,
    Order,
    OrderItem,
    OrderStatus,
    PrepLog,
    RescueListing,
    Restaurant,
)

PACE_WINDOW = timedelta(hours=2)
# Cooked food has to sell within a few hours, so never forecast further ahead.
SHELF_LIFE_H = 3.0
MAX_LISTING_HOURS = 6
# Suggested listings open at 25-50% off (more when more is left) and fall to 70% off.
START_DISCOUNT_MIN = Decimal("0.25")
START_DISCOUNT_MAX = Decimal("0.50")
MAX_DISCOUNT = Decimal("0.70")
NEARBY_KM = 6.0
IST = timedelta(hours=5, minutes=30)


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _rupees(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def price_at(listing: RescueListing, moment: datetime | None = None) -> Decimal:
    moment = moment or _now()
    start, end = _aware(listing.starts_at), _aware(listing.ends_at)
    if moment <= start:
        return _rupees(listing.start_price)
    if moment >= end:
        return _rupees(listing.floor_price)
    progress = Decimal(str((moment - start).total_seconds() / (end - start).total_seconds()))
    price = listing.start_price - (listing.start_price - listing.floor_price) * progress
    return max(_rupees(listing.floor_price), _rupees(price))


def is_live(listing: RescueListing, moment: datetime | None = None) -> bool:
    moment = moment or _now()
    return (
        listing.status == "LIVE"
        and listing.qty_left > 0
        and _aware(listing.starts_at) <= moment < _aware(listing.ends_at)
    )


def listing_out(listing: RescueListing, item: MenuItem, restaurant: Restaurant | None = None,
                distance_km: float | None = None) -> dict:
    now = _now()
    current = price_at(listing, now)
    in_10 = price_at(listing, now + timedelta(minutes=10))
    return {
        "id": listing.id,
        "restaurant_id": listing.restaurant_id,
        "restaurant_name": restaurant.name if restaurant else None,
        "menu_item_id": item.id,
        "name": item.name,
        "veg": item.veg,
        "portion_grams": item.portion_grams,
        "original_price": str(listing.original_price),
        "current_price": str(current),
        "price_in_10_min": str(in_10),
        "floor_price": str(listing.floor_price),
        "discount_pct": round(
            float((listing.original_price - current) / listing.original_price * 100)
        ),
        "qty_left": listing.qty_left,
        "qty_total": listing.qty_total,
        "starts_at": listing.starts_at,
        "ends_at": listing.ends_at,
        "status": listing.status if is_live(listing, now) or listing.status != "LIVE" else "ENDED",
        "distance_km": round(distance_km, 2) if distance_km is not None else None,
    }


def _local_day(moment: datetime) -> date:
    return (moment + IST).date()


def _closing_utc(restaurant: Restaurant, moment: datetime) -> datetime:
    """Restaurant closing time today (open_to is local IST wall time)."""
    local = moment + IST
    close_local = datetime.combine(local.date(), restaurant.open_to or time(23, 0))
    if restaurant.open_to and restaurant.open_to <= time(4, 0):
        close_local += timedelta(days=1)
    return (close_local - IST).replace(tzinfo=UTC)


async def _sold_today(
    session: AsyncSession, restaurant_id: UUID, since: datetime
) -> dict[UUID, int]:
    rows = (
        await session.execute(
            select(OrderItem.menu_item_id, func.sum(OrderItem.qty))
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                Order.restaurant_id == restaurant_id,
                Order.placed_at >= since,
                Order.status.not_in((OrderStatus.CANCELLED, OrderStatus.FAILED)),
            )
            .group_by(OrderItem.menu_item_id)
        )
    ).all()
    return {row[0]: int(row[1] or 0) for row in rows}


async def forecast(session: AsyncSession, restaurant: Restaurant) -> dict:
    now = _now()
    day = _local_day(now)
    day_start = (datetime.combine(day, time(0, 0)) - IST).replace(tzinfo=UTC)
    closing = _closing_utc(restaurant, now)
    hours_left = max(0.0, (closing - now).total_seconds() / 3600.0)
    horizon = min(hours_left, SHELF_LIFE_H)

    items = list(
        (
            await session.execute(
                select(MenuItem)
                .where(MenuItem.restaurant_id == restaurant.id)
                .order_by(MenuItem.category, MenuItem.name)
            )
        ).scalars()
    )
    logs = {
        log.menu_item_id: log
        for log in (
            await session.execute(
                select(PrepLog).where(
                    PrepLog.restaurant_id == restaurant.id, PrepLog.day == day
                )
            )
        ).scalars()
    }
    sold = await _sold_today(session, restaurant.id, day_start)
    recent = await _sold_today(session, restaurant.id, now - PACE_WINDOW)
    live = {
        listing.menu_item_id: listing
        for listing in (
            await session.execute(
                select(RescueListing).where(
                    RescueListing.restaurant_id == restaurant.id,
                    RescueListing.status == "LIVE",
                    RescueListing.ends_at > now,
                )
            )
        ).scalars()
    }

    rows = []
    for item in items:
        log = logs.get(item.id)
        sold_qty = sold.get(item.id, 0)
        pace = recent.get(item.id, 0) / (PACE_WINDOW.total_seconds() / 3600.0)
        expected_more = pace * horizon
        prepared = log.prepared_qty if log else None
        projected = None
        suggestion = None
        if prepared is not None:
            remaining = max(0, prepared - sold_qty)
            projected = max(0, round(remaining - expected_more))
            if projected >= 1 and item.id not in live:
                share = Decimal(str(projected / max(1, prepared)))
                discount = min(
                    START_DISCOUNT_MAX, START_DISCOUNT_MIN + share * Decimal("0.25")
                )
                start = _rupees(item.price * (1 - discount))
                floor = max(Decimal("10"), _rupees(item.price * (1 - MAX_DISCOUNT)))
                window = min(max(horizon, 1.0), 3.0)
                suggestion = {
                    "qty": projected,
                    "start_price": str(max(start, floor)),
                    "floor_price": str(floor),
                    "duration_min": int(window * 60),
                    "reason": (
                        f"{prepared} prepared, {sold_qty} sold so far, selling about "
                        f"{pace:.1f}/h over the next {horizon:.1f} h -> about {projected} "
                        "likely left over."
                    ),
                }
        listing = live.get(item.id)
        rows.append(
            {
                "menu_item_id": item.id,
                "name": item.name,
                "price": str(item.price),
                "prepared": prepared,
                "sold_today": sold_qty,
                "pace_per_hour": round(pace, 2),
                "projected_leftover": projected,
                "suggestion": suggestion,
                "live_listing": listing_out(listing, item) if listing else None,
            }
        )
    return {
        "day": day.isoformat(),
        "closing_at": closing,
        "hours_to_close": round(hours_left, 2),
        "horizon_hours": round(horizon, 2),
        "items": rows,
        "method": (
            "Leftover = prepared - sold so far - (orders per hour over the last 2 h x the "
            "next 3 h, or until closing if sooner). Uses this kitchen's real orders; no AI call."
        ),
    }


async def log_prep(
    session: AsyncSession, restaurant: Restaurant, menu_item_id: UUID, prepared_qty: int
) -> None:
    item = await session.get(MenuItem, menu_item_id)
    if item is None or item.restaurant_id != restaurant.id:
        raise NotFoundError("menu item not found")
    if not 0 <= prepared_qty <= 2000:
        raise BadRequestError("prepared quantity must be between 0 and 2000")
    day = _local_day(_now())
    log = (
        await session.execute(
            select(PrepLog).where(
                PrepLog.restaurant_id == restaurant.id,
                PrepLog.menu_item_id == menu_item_id,
                PrepLog.day == day,
            )
        )
    ).scalar_one_or_none()
    if log is None:
        session.add(
            PrepLog(
                restaurant_id=restaurant.id,
                menu_item_id=menu_item_id,
                day=day,
                prepared_qty=prepared_qty,
            )
        )
    else:
        log.prepared_qty = prepared_qty
    await session.commit()


async def create_listing(
    session: AsyncSession,
    restaurant: Restaurant,
    *,
    menu_item_id: UUID,
    qty: int,
    start_price: Decimal,
    floor_price: Decimal,
    duration_min: int,
) -> dict:
    item = await session.get(MenuItem, menu_item_id)
    if item is None or item.restaurant_id != restaurant.id:
        raise NotFoundError("menu item not found")
    if not 1 <= qty <= 200:
        raise BadRequestError("quantity must be between 1 and 200")
    if not 15 <= duration_min <= MAX_LISTING_HOURS * 60:
        raise BadRequestError("a rescue window must be 15 minutes to 6 hours")
    if not Decimal("1") <= floor_price <= start_price <= item.price:
        raise BadRequestError("prices must satisfy floor <= start <= menu price")
    existing = await session.scalar(
        select(func.count())
        .select_from(RescueListing)
        .where(
            RescueListing.menu_item_id == item.id,
            RescueListing.status == "LIVE",
            RescueListing.ends_at > _now(),
        )
    )
    if existing:
        raise ConflictError("this dish already has a live rescue listing")
    now = _now()
    listing = RescueListing(
        restaurant_id=restaurant.id,
        menu_item_id=item.id,
        qty_total=qty,
        qty_left=qty,
        original_price=item.price,
        start_price=start_price,
        floor_price=floor_price,
        starts_at=now,
        ends_at=now + timedelta(minutes=duration_min),
        status="LIVE",
    )
    session.add(listing)
    await session.commit()
    await session.refresh(listing)
    return listing_out(listing, item, restaurant)


async def end_listing(session: AsyncSession, restaurant: Restaurant, listing_id: UUID) -> None:
    listing = await session.get(RescueListing, listing_id)
    if listing is None or listing.restaurant_id != restaurant.id:
        raise NotFoundError("rescue listing not found")
    listing.status = "ENDED"
    await session.commit()


async def live_near(
    session: AsyncSession, lat: float | None, lng: float | None, limit: int = 20
) -> list[dict]:
    now = _now()
    rows = (
        await session.execute(
            select(RescueListing, MenuItem, Restaurant)
            .join(MenuItem, MenuItem.id == RescueListing.menu_item_id)
            .join(Restaurant, Restaurant.id == RescueListing.restaurant_id)
            .where(
                RescueListing.status == "LIVE",
                RescueListing.qty_left > 0,
                RescueListing.starts_at <= now,
                RescueListing.ends_at > now,
                Restaurant.is_active.is_(True),
            )
            .order_by(RescueListing.ends_at)
        )
    ).all()
    result = []
    for listing, item, restaurant in rows:
        distance = (
            haversine_km(lat, lng, restaurant.lat, restaurant.lng)
            if lat is not None and lng is not None
            else None
        )
        if distance is not None and distance > NEARBY_KM:
            continue
        result.append(listing_out(listing, item, restaurant, distance))
    return result[:limit]


async def live_counts(session: AsyncSession) -> dict[UUID, int]:
    now = _now()
    rows = (
        await session.execute(
            select(RescueListing.restaurant_id, func.count())
            .where(
                RescueListing.status == "LIVE",
                RescueListing.qty_left > 0,
                RescueListing.ends_at > now,
            )
            .group_by(RescueListing.restaurant_id)
        )
    ).all()
    return {row[0]: int(row[1]) for row in rows}


async def live_for_items(
    session: AsyncSession, item_ids: list[UUID]
) -> dict[UUID, RescueListing]:
    if not item_ids:
        return {}
    now = _now()
    rows = (
        await session.execute(
            select(RescueListing).where(
                RescueListing.menu_item_id.in_(item_ids),
                RescueListing.status == "LIVE",
                RescueListing.qty_left > 0,
                RescueListing.ends_at > now,
            )
        )
    ).scalars()
    return {listing.menu_item_id: listing for listing in rows}


async def claim(
    session: AsyncSession, listing_id: UUID, qty: int
) -> tuple[RescueListing, Decimal]:
    """Lock a listing at checkout, take the quantity and return the price paid."""
    listing = (
        await session.execute(
            select(RescueListing).where(RescueListing.id == listing_id).with_for_update()
        )
    ).scalar_one_or_none()
    if listing is None or not is_live(listing):
        raise BadRequestError("this rescue deal has ended; remove it from your cart")
    if listing.qty_left < qty:
        raise BadRequestError(
            f"only {listing.qty_left} left in this rescue deal; reduce the quantity"
        )
    listing.qty_left -= qty
    if listing.qty_left == 0:
        listing.status = "SOLD_OUT"
    return listing, price_at(listing)
