from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import OrderStatus, RiderStatus


class MenuItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    price: Decimal
    category: str
    veg: bool
    prep_complexity: int
    tags: list[str]


class RestaurantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    lat: float
    lng: float
    cuisine: list[str]
    avg_prep_min: int
    capacity_per_hr: int
    rating: Decimal
    distance_km: float | None = None


class OrderItemIn(BaseModel):
    menu_item_id: UUID
    qty: int = Field(ge=1, le=20)


class OrderCreate(BaseModel):
    customer_id: UUID
    restaurant_id: UUID
    items: list[OrderItemIn] = Field(min_length=1, max_length=30)
    drop_lat: float | None = Field(default=None, ge=-90, le=90)
    drop_lng: float | None = Field(default=None, ge=-180, le=180)
    deadline_at: datetime | None = None

    @model_validator(mode="after")
    def drop_coordinates_paired(self) -> "OrderCreate":
        if (self.drop_lat is None) != (self.drop_lng is None):
            raise ValueError("drop_lat and drop_lng must be provided together")
        return self


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    menu_item_id: UUID
    name: str
    qty: int
    unit_price: Decimal


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    customer_id: UUID
    restaurant_id: UUID
    rider_id: UUID | None
    status: OrderStatus
    placed_at: datetime
    promised_eta_at: datetime | None
    deadline_at: datetime | None
    drop_lat: float
    drop_lng: float
    total_price: Decimal
    reassign_count: int
    delay_flags: list[str]
    items: list[OrderItemOut]


class OrderEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: str
    payload: dict
    created_at: datetime


class ActionRequest(BaseModel):
    reason: str | None = None


class RiderStatusUpdate(BaseModel):
    status: Literal["PICKED_UP", "DELIVERED"]
    rider_id: UUID
    reason: str | None = None


class CustomerOut(BaseModel):
    id: UUID
    name: str
    home_lat: float
    home_lng: float
    budget_pref: str | None = None
    diet_pref: str | None = None


class RiderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    lat: float
    lng: float
    location_source: str
    location_accuracy_m: float | None
    status: RiderStatus
    active_order_ids: list[str]
    capacity: int
    vehicle: str
    last_seen_at: datetime | None = None


class RiderLocationUpdate(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    source: Literal["gps", "simulated"] = "simulated"
    accuracy_m: float | None = Field(default=None, ge=0, le=5000)
