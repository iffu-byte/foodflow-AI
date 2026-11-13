from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import MenuItem, Order, Restaurant
from app.eta.engine import predict_eta
from app.eta.features import ItemFeature, build_feature_dict
from app.eta.types import EtaPrediction


async def _menu_items(session: AsyncSession, order: Order) -> dict[UUID, MenuItem]:
    ids = {item.menu_item_id for item in order.items}
    if not ids:
        return {}
    stmt = select(MenuItem).where(MenuItem.id.in_(ids))
    rows = (await session.execute(stmt)).scalars().all()
    return {row.id: row for row in rows}


async def estimate_for_order(
    session: AsyncSession,
    order: Order,
    restaurant: Restaurant,
    *,
    now: datetime | None = None,
) -> EtaPrediction:
    menu_items = await _menu_items(session, order)
    items = [
        ItemFeature(
            qty=item.qty,
            veg=menu_items[item.menu_item_id].veg
            if item.menu_item_id in menu_items
            else True,
            prep_complexity=menu_items[item.menu_item_id].prep_complexity
            if item.menu_item_id in menu_items
            else 1,
        )
        for item in order.items
    ]
    features = build_feature_dict(
        restaurant_avg_prep_min=restaurant.avg_prep_min,
        restaurant_capacity_per_hr=restaurant.capacity_per_hr,
        restaurant_lat=restaurant.lat,
        restaurant_lng=restaurant.lng,
        drop_lat=order.drop_lat,
        drop_lng=order.drop_lng,
        placed_at=order.placed_at or now or datetime.now(UTC),
        total_price=float(order.total_price),
        items=items,
    )
    return predict_eta(features)
