from pydantic import BaseModel

from app.domain.schemas import MenuItemOut, RestaurantOut


class RestaurantRecommendationOut(BaseModel):
    restaurant: RestaurantOut
    score: float
    distance_km: float
    reasons: list[str]


class MenuRecommendationOut(BaseModel):
    item: MenuItemOut
    score: float
    reasons: list[str]
