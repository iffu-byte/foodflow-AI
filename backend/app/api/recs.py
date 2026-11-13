from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import SessionDep
from app.auth.deps import CurrentUser
from app.domain.models import Role
from app.domain.schemas import MenuItemOut, RestaurantOut
from app.recs import service
from app.recs.schemas import MenuRecommendationOut, RestaurantRecommendationOut

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


def _validate_coordinates(lat: float | None, lng: float | None) -> None:
    if (lat is None) != (lng is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="lat and lng must be provided together",
        )


def _assert_can_view_recommendations(user: CurrentUser, customer_id: UUID) -> None:
    if user.role is Role.ADMIN:
        return
    if user.role is Role.CUSTOMER and user.id == customer_id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="you are not allowed to view these recommendations",
    )


@router.get(
    "/restaurants/{customer_id}", response_model=list[RestaurantRecommendationOut]
)
async def recommend_restaurants(
    customer_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lng: Annotated[float | None, Query(ge=-180, le=180)] = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 8,
) -> list[RestaurantRecommendationOut]:
    _assert_can_view_recommendations(user, customer_id)
    _validate_coordinates(lat, lng)
    picks = await service.recommend_restaurants(
        session, customer_id, lat=lat, lng=lng, limit=limit
    )
    results: list[RestaurantRecommendationOut] = []
    for pick in picks:
        restaurant = RestaurantOut.model_validate(pick.restaurant)
        restaurant.distance_km = pick.distance_km
        results.append(
            RestaurantRecommendationOut(
                restaurant=restaurant,
                score=pick.score,
                distance_km=pick.distance_km,
                reasons=pick.reasons,
            )
        )
    return results


@router.get(
    "/menu/{customer_id}/{restaurant_id}", response_model=list[MenuRecommendationOut]
)
async def recommend_menu(
    customer_id: UUID,
    restaurant_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=30)] = 10,
) -> list[MenuRecommendationOut]:
    _assert_can_view_recommendations(user, customer_id)
    picks = await service.recommend_menu(
        session, customer_id, restaurant_id, limit=limit
    )
    return [
        MenuRecommendationOut(
            item=MenuItemOut.model_validate(pick.item),
            score=pick.score,
            reasons=pick.reasons,
        )
        for pick in picks
    ]
