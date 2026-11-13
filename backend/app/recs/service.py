import math
from collections import Counter
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import NotFoundError
from app.domain.geo import haversine_km
from app.domain.models import Customer, MenuItem, Order, OrderItem, Restaurant

BUDGET_BANDS = {
    "low": (0.0, 180.0),
    "medium": (150.0, 350.0),
    "high": (300.0, 10_000.0),
}


@dataclass
class RestaurantPick:
    restaurant: Restaurant
    score: float
    distance_km: float
    reasons: list[str]


@dataclass
class MenuPick:
    item: MenuItem
    score: float
    reasons: list[str]


def _budget_fit(price: float, preference: str | None) -> float:
    band = BUDGET_BANDS.get(preference or "")
    if band is None:
        return 0.5
    low, high = band
    if low <= price <= high:
        return 1.0
    gap = min(abs(price - low), abs(price - high))
    return max(0.0, 1.0 - gap / 250.0)


def _diet_fit(veg_share: float, preference: str | None) -> float:
    if preference == "veg":
        return veg_share
    if preference == "eggetarian":
        return max(veg_share, 0.5)
    if preference == "non_veg":
        return 1.0 - veg_share
    return 0.5


async def _customer(session: AsyncSession, customer_id: UUID) -> Customer:
    customer = await session.get(Customer, customer_id)
    if customer is None:
        raise NotFoundError("customer not found")
    return customer


async def _restaurant(session: AsyncSession, restaurant_id: UUID) -> Restaurant:
    restaurant = await session.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise NotFoundError("restaurant not found")
    return restaurant


async def recommend_restaurants(
    session: AsyncSession,
    customer_id: UUID,
    *,
    lat: float | None = None,
    lng: float | None = None,
    limit: int = 8,
) -> list[RestaurantPick]:
    customer = await _customer(session, customer_id)
    origin_lat = lat if lat is not None else customer.home_lat
    origin_lng = lng if lng is not None else customer.home_lng

    restaurants = list((await session.execute(select(Restaurant))).scalars().all())
    items = list((await session.execute(select(MenuItem))).scalars().all())
    items_by_restaurant: dict[UUID, list[MenuItem]] = {}
    for item in items:
        items_by_restaurant.setdefault(item.restaurant_id, []).append(item)

    order_counts = dict(
        (
            await session.execute(
                select(Order.restaurant_id, func.count()).group_by(Order.restaurant_id)
            )
        ).all()
    )
    max_orders = max(order_counts.values(), default=0)

    history = (
        await session.execute(
            select(Restaurant.cuisine)
            .join(Order, Order.restaurant_id == Restaurant.id)
            .where(Order.customer_id == customer_id)
        )
    ).scalars()
    cuisine_counts: Counter[str] = Counter(
        cuisine for cuisines in history for cuisine in cuisines
    )
    max_affinity = max(cuisine_counts.values(), default=0)

    picks: list[RestaurantPick] = []
    for restaurant in restaurants:
        menu = items_by_restaurant.get(restaurant.id, [])
        avg_price = (
            sum(float(item.price) for item in menu) / len(menu) if menu else 250.0
        )
        veg_share = (
            sum(1 for item in menu if item.veg) / len(menu) if menu else 0.5
        )
        distance = haversine_km(origin_lat, origin_lng, restaurant.lat, restaurant.lng)
        distance_fit = math.exp(-distance / 4.0)
        rating_fit = min(1.0, max(0.0, (float(restaurant.rating) - 3.0) / 2.0))
        budget_fit = _budget_fit(avg_price, customer.budget_pref)
        diet_fit = _diet_fit(veg_share, customer.diet_pref)
        popularity = (
            math.log1p(order_counts.get(restaurant.id, 0)) / math.log1p(max_orders)
            if max_orders
            else 0.0
        )
        affinity = (
            sum(cuisine_counts.get(cuisine, 0) for cuisine in restaurant.cuisine)
            / max_affinity
            if max_affinity
            else 0.0
        )

        score = (
            0.30 * distance_fit
            + 0.15 * rating_fit
            + 0.20 * budget_fit
            + 0.15 * diet_fit
            + 0.10 * popularity
            + 0.10 * affinity
        )

        reasons = [f"{distance:.1f} km away"]
        if float(restaurant.rating) >= 4.3:
            reasons.append(f"{float(restaurant.rating):.1f} star rating")
        if budget_fit >= 0.9 and customer.budget_pref:
            reasons.append(f"fits your {customer.budget_pref} budget")
        if customer.diet_pref == "veg" and veg_share >= 0.6:
            reasons.append(f"vegetarian-friendly menu ({veg_share:.0%})")
        if order_counts.get(restaurant.id, 0) > 0:
            reasons.append(f"{order_counts[restaurant.id]} orders so far")
        if affinity > 0:
            reasons.append("matches your usual cuisines")

        picks.append(
            RestaurantPick(
                restaurant=restaurant,
                score=round(min(1.0, max(0.0, score)), 3),
                distance_km=round(distance, 2),
                reasons=reasons,
            )
        )

    picks.sort(key=lambda pick: (-pick.score, pick.restaurant.name))
    return picks[:limit]


async def recommend_menu(
    session: AsyncSession,
    customer_id: UUID,
    restaurant_id: UUID,
    *,
    limit: int = 10,
) -> list[MenuPick]:
    customer = await _customer(session, customer_id)
    await _restaurant(session, restaurant_id)

    items = list(
        (
            await session.execute(
                select(MenuItem)
                .where(MenuItem.restaurant_id == restaurant_id)
                .order_by(MenuItem.name)
            )
        )
        .scalars()
        .all()
    )
    item_counts = dict(
        (
            await session.execute(
                select(OrderItem.menu_item_id, func.count())
                .join(Order, Order.id == OrderItem.order_id)
                .where(Order.restaurant_id == restaurant_id)
                .group_by(OrderItem.menu_item_id)
            )
        ).all()
    )
    max_orders = max(item_counts.values(), default=0)

    picks: list[MenuPick] = []
    for item in items:
        if customer.diet_pref == "veg" and not item.veg:
            continue

        price = float(item.price)
        budget_fit = _budget_fit(price, customer.budget_pref)
        diet_fit = _diet_fit(1.0 if item.veg else 0.0, customer.diet_pref)
        popularity = (
            math.log1p(item_counts.get(item.id, 0)) / math.log1p(max_orders)
            if max_orders
            else 0.0
        )
        quickness = max(0.0, 1.0 - (item.prep_complexity - 1) / 4.0)
        score = 0.35 * diet_fit + 0.25 * budget_fit + 0.20 * popularity + 0.20 * quickness

        reasons = [f"{item.category} at {price:.0f}"]
        if item.veg and customer.diet_pref == "veg":
            reasons.append("vegetarian")
        if budget_fit >= 0.9 and customer.budget_pref:
            reasons.append(f"fits your {customer.budget_pref} budget")
        if item_counts.get(item.id, 0) > 0:
            reasons.append(f"ordered {item_counts[item.id]} times")
        if item.prep_complexity <= 1:
            reasons.append("quick to prepare")

        picks.append(
            MenuPick(
                item=item,
                score=round(min(1.0, max(0.0, score)), 3),
                reasons=reasons,
            )
        )

    picks.sort(key=lambda pick: (-pick.score, pick.item.name))
    return picks[:limit]
