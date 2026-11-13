from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import SessionDep
from app.auth.deps import RestaurantUser
from app.domain.models import OrderStatus
from app.marketplace import access
from app.marketplace import restaurant as restaurant_service
from app.marketplace.schemas import (
    DeliveryActionIn,
    MarketOrderOut,
    MenuPatch,
    RestaurantAnalyticsOut,
    RestaurantBrowseOut,
    RestaurantMenuItemOut,
)
from app.marketplace.serializers import browse_out

router = APIRouter(prefix="/api/v1/restaurant", tags=["restaurant"])


@router.get("/me", response_model=RestaurantBrowseOut)
async def me(user: RestaurantUser, session: SessionDep) -> RestaurantBrowseOut:
    restaurant = await access.restaurant_for(session, user)
    return browse_out(restaurant)


@router.get("/menu", response_model=list[RestaurantMenuItemOut])
async def menu(
    user: RestaurantUser, session: SessionDep
) -> list[RestaurantMenuItemOut]:
    restaurant = await access.restaurant_for(session, user)
    return await restaurant_service.menu(session, restaurant)


@router.patch("/menu/{item_id}", response_model=RestaurantMenuItemOut)
async def patch_menu_item(
    item_id: UUID,
    payload: MenuPatch,
    user: RestaurantUser,
    session: SessionDep,
) -> RestaurantMenuItemOut:
    restaurant = await access.restaurant_for(session, user)
    return await restaurant_service.update_menu_item(
        session, restaurant, item_id, payload
    )


@router.get("/orders", response_model=list[MarketOrderOut])
async def orders(
    user: RestaurantUser,
    session: SessionDep,
    status_filter: Annotated[OrderStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[MarketOrderOut]:
    restaurant = await access.restaurant_for(session, user)
    return await restaurant_service.orders(
        session, restaurant, status=status_filter, limit=limit
    )


@router.post("/orders/{order_id}/accept", response_model=MarketOrderOut)
async def accept_order(
    order_id: UUID, user: RestaurantUser, session: SessionDep
) -> MarketOrderOut:
    restaurant = await access.restaurant_for(session, user)
    return await restaurant_service.accept_order(session, restaurant, order_id)


@router.post("/orders/{order_id}/reject", response_model=MarketOrderOut)
async def reject_order(
    order_id: UUID,
    user: RestaurantUser,
    session: SessionDep,
    payload: DeliveryActionIn | None = None,
) -> MarketOrderOut:
    restaurant = await access.restaurant_for(session, user)
    return await restaurant_service.reject_order(
        session, restaurant, order_id, payload.reason if payload else None
    )


@router.post("/orders/{order_id}/prepare", response_model=MarketOrderOut)
async def prepare_order(
    order_id: UUID, user: RestaurantUser, session: SessionDep
) -> MarketOrderOut:
    restaurant = await access.restaurant_for(session, user)
    return await restaurant_service.start_preparing(session, restaurant, order_id)


@router.post("/orders/{order_id}/ready", response_model=MarketOrderOut)
async def ready_order(
    order_id: UUID, user: RestaurantUser, session: SessionDep
) -> MarketOrderOut:
    restaurant = await access.restaurant_for(session, user)
    return await restaurant_service.mark_ready(session, restaurant, order_id)


@router.get("/analytics", response_model=RestaurantAnalyticsOut)
async def analytics(
    user: RestaurantUser, session: SessionDep
) -> RestaurantAnalyticsOut:
    restaurant = await access.restaurant_for(session, user)
    return await restaurant_service.analytics(session, restaurant)
