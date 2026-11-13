from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import SessionDep
from app.domain import service
from app.domain.schemas import MenuItemOut, RestaurantOut

router = APIRouter(prefix="/restaurants", tags=["restaurants"])


@router.get("", response_model=list[RestaurantOut])
async def list_restaurants(
    session: SessionDep,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lng: Annotated[float | None, Query(ge=-180, le=180)] = None,
) -> list[RestaurantOut]:
    if (lat is None) != (lng is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="lat and lng must be provided together",
        )

    rows = await service.list_restaurants(session, lat, lng)
    results: list[RestaurantOut] = []
    for restaurant, distance in rows:
        result = RestaurantOut.model_validate(restaurant)
        result.distance_km = round(distance, 2) if distance is not None else None
        results.append(result)
    return results


@router.get("/{restaurant_id}/menu", response_model=list[MenuItemOut])
async def get_menu(restaurant_id: UUID, session: SessionDep) -> list[MenuItemOut]:
    items = await service.get_menu(session, restaurant_id)
    return [MenuItemOut.model_validate(item) for item in items]
