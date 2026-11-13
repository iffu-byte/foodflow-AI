from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.models import OrderStatus
from app.domain.schemas import MenuItemOut, OrderItemOut


class PaymentCheckoutOut(BaseModel):
    provider: Literal["razorpay"]
    provider_order_id: str
    key_id: str
    amount_paise: int
    currency: str
    display_name: str
    description: str
    is_test_mode: bool


class PaymentProviderConfigOut(BaseModel):
    provider: Literal["demo", "razorpay"]
    online_payments_enabled: bool
    is_test_mode: bool


class MarketOrderOut(BaseModel):
    id: UUID
    order_number: str | None
    customer_id: UUID
    restaurant_id: UUID
    restaurant_name: str
    rider_id: UUID | None
    rider_name: str | None
    status: OrderStatus
    items: list[OrderItemOut]
    subtotal: Decimal
    delivery_fee: Decimal
    discount: Decimal
    tax: Decimal
    total_amount: Decimal
    payment_method: str
    payment_status: str
    payment_checkout: PaymentCheckoutOut | None = None
    placed_at: datetime
    promised_eta_at: datetime | None
    deadline_at: datetime | None
    actual_delivery_at: datetime | None
    drop_lat: float
    drop_lng: float
    delivery_address: str | None
    customer_phone: str | None
    delivery_instructions: str | None
    estimated_prep_min: int | None
    delay_flags: list[str]
    reassign_count: int
    can_review: bool = False


class AddressIn(BaseModel):
    label: str = Field(default="Home", max_length=40)
    line1: str = Field(min_length=3, max_length=200)
    line2: str | None = Field(default=None, max_length=200)
    city: str = Field(default="Hyderabad", max_length=80)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    phone: str | None = Field(default=None, max_length=24)
    is_default: bool = False


class AddressOut(BaseModel):
    id: UUID
    label: str
    line1: str
    line2: str | None
    city: str
    lat: float
    lng: float
    phone: str | None
    is_default: bool


class ProfileOut(BaseModel):
    id: UUID
    name: str
    email: str | None
    phone: str | None
    home_lat: float
    home_lng: float
    budget_pref: str | None
    diet_pref: str | None


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = Field(default=None, max_length=24)
    budget_pref: str | None = Field(default=None, max_length=40)
    diet_pref: str | None = Field(default=None, max_length=40)
    home_lat: float | None = Field(default=None, ge=-90, le=90)
    home_lng: float | None = Field(default=None, ge=-180, le=180)


class CartItemIn(BaseModel):
    menu_item_id: UUID
    qty: int = Field(default=1, ge=1, le=20)


class CartItemUpdate(BaseModel):
    qty: int = Field(ge=0, le=20)


class CartLineOut(BaseModel):
    id: UUID
    menu_item_id: UUID
    name: str
    price: Decimal
    qty: int
    veg: bool
    available: bool
    line_total: Decimal


class CartRestaurantOut(BaseModel):
    id: UUID
    name: str
    image_url: str | None
    delivery_fee: Decimal
    min_order_value: Decimal
    avg_prep_min: int


class CartOut(BaseModel):
    id: UUID
    restaurant: CartRestaurantOut | None
    items: list[CartLineOut]
    item_count: int
    subtotal: Decimal
    delivery_fee: Decimal
    discount: Decimal
    tax: Decimal
    total: Decimal
    coupon_code: str | None


class CouponIn(BaseModel):
    code: str = Field(min_length=2, max_length=30)


class CouponOut(BaseModel):
    code: str
    valid: bool
    description: str
    discount: Decimal = Decimal("0.00")


class CheckoutIn(BaseModel):
    address_id: UUID | None = None
    phone: str | None = Field(default=None, max_length=24)
    instructions: str | None = Field(default=None, max_length=500)
    payment_method: Literal["COD", "UPI_DEMO", "RAZORPAY"] = "COD"
    coupon_code: str | None = Field(default=None, max_length=30)


class RazorpayPaymentVerifyIn(BaseModel):
    razorpay_payment_id: str = Field(min_length=3, max_length=100)
    razorpay_order_id: str = Field(min_length=3, max_length=100)
    razorpay_signature: str = Field(min_length=32, max_length=256)


class ReviewIn(BaseModel):
    restaurant_rating: int = Field(ge=1, le=5)
    rider_rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


class ReviewOut(BaseModel):
    id: UUID
    order_id: UUID
    restaurant_rating: int
    rider_rating: int | None
    comment: str | None
    created_at: datetime


class RiderProfileOut(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    email: str | None
    phone: str | None
    lat: float
    lng: float
    location_source: str
    location_accuracy_m: float | None
    status: str
    vehicle: str
    vehicle_registration: str | None
    capacity: int
    verification_status: str
    average_rating: float
    active_order_ids: list[str]
    last_seen_at: datetime | None
    today_earnings: Decimal
    week_earnings: Decimal
    month_earnings: Decimal
    today_deliveries: int
    total_deliveries: int


class AvailabilityIn(BaseModel):
    online: bool


class OfferOut(BaseModel):
    assignment_id: UUID
    order_id: UUID
    order_number: str | None
    restaurant_name: str
    restaurant_address: str | None
    pickup_lat: float
    pickup_lng: float
    drop_lat: float
    drop_lng: float
    pickup_distance_km: float
    pickup_eta_min: float
    delivery_distance_km: float
    estimated_delivery_min: float
    estimated_earnings: Decimal
    expires_at: datetime
    offered_at: datetime


class AssignmentActionOut(BaseModel):
    assignment_id: UUID
    status: str
    order: MarketOrderOut


class OfferActionOut(BaseModel):
    status: str
    next_offer: OfferOut | None = None


class DeliveryActionIn(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class EarningsEntryOut(BaseModel):
    order_id: UUID
    order_number: str | None
    restaurant_name: str
    amount: Decimal
    distance_km: float
    created_at: datetime


class EarningsOut(BaseModel):
    today: Decimal
    week: Decimal
    month: Decimal
    completed_deliveries: int
    entries: list[EarningsEntryOut]


class TrackingRiderOut(BaseModel):
    id: UUID
    name: str
    lat: float
    lng: float
    vehicle: str
    phone: str | None
    location_source: str
    location_accuracy_m: float | None
    last_seen_at: datetime | None


class TrackingPointOut(BaseModel):
    lat: float
    lng: float
    created_at: datetime


class RoutePointOut(BaseModel):
    lat: float
    lng: float


class TrackingRouteOut(BaseModel):
    order_id: UUID
    phase: Literal["to_pickup", "to_drop", "restaurant_to_customer"]
    origin: RoutePointOut
    destination: RoutePointOut
    points: list[RoutePointOut]
    distance_m: float
    duration_s: float
    routing_provider: str
    is_estimated: bool


class TrackingOut(BaseModel):
    order_id: UUID
    order_number: str | None
    status: OrderStatus
    restaurant_name: str
    restaurant_address: str | None
    restaurant_lat: float
    restaurant_lng: float
    drop_lat: float
    drop_lng: float
    delivery_address: str | None
    rider: TrackingRiderOut | None
    points: list[TrackingPointOut]
    eta_minutes: float | None
    low_minutes: float | None
    high_minutes: float | None
    promised_eta_at: datetime | None
    simulated: bool = True


class MenuPatch(BaseModel):
    available: bool | None = None
    price: Decimal | None = Field(default=None, gt=0)
    description: str | None = Field(default=None, max_length=500)


class RestaurantMenuItemOut(MenuItemOut):
    available: bool
    description: str
    image_url: str | None


class RestaurantBrowseOut(BaseModel):
    id: UUID
    name: str
    cuisine: list[str]
    rating: Decimal
    rating_count: int
    avg_prep_min: int
    min_order_value: Decimal
    delivery_fee: Decimal
    address: str | None
    description: str
    image_url: str | None
    is_active: bool
    distance_km: float | None = None


class RestaurantAnalyticsOut(BaseModel):
    active_orders: int
    completed_today: int
    revenue_today: Decimal
    average_prep_min: float | None
    menu_items: int
    available_items: int
    rating: Decimal
    rating_count: int


class NotificationOut(BaseModel):
    id: UUID
    type: str
    title: str
    body: str
    order_id: UUID | None
    is_read: bool
    created_at: datetime
