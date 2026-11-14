import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class Role(str, Enum):
    CUSTOMER = "customer"
    RESTAURANT = "restaurant"
    RIDER = "rider"
    ADMIN = "admin"


class OrderStatus(str, Enum):
    PLACED = "PLACED"
    ACCEPTED = "ACCEPTED"
    PREPARING = "PREPARING"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class RiderStatus(str, Enum):
    OFFLINE = "offline"
    IDLE = "idle"
    TO_PICKUP = "to_pickup"
    TO_DROP = "to_drop"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[Role] = mapped_column(SAEnum(Role, name="user_role"))
    email: Mapped[str | None] = mapped_column(String(160), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(24))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Customer(Base):
    __tablename__ = "customers"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    home_lat: Mapped[float] = mapped_column(Float)
    home_lng: Mapped[float] = mapped_column(Float)
    budget_pref: Mapped[str | None] = mapped_column(String(40))
    diet_pref: Mapped[str | None] = mapped_column(String(40))
    daily_kcal_goal: Mapped[int | None] = mapped_column(Integer)


class Restaurant(Base):
    __tablename__ = "restaurants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(120), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    cuisine: Mapped[list[str]] = mapped_column(JSONB, default=list)
    avg_prep_min: Mapped[int] = mapped_column(Integer, default=15)
    capacity_per_hr: Mapped[int] = mapped_column(Integer, default=40)
    open_from: Mapped[time] = mapped_column(Time, default=time(0, 0))
    open_to: Mapped[time] = mapped_column(Time, default=time(23, 59))
    rating: Mapped[Decimal] = mapped_column(Numeric(2, 1), default=Decimal("4.0"))
    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    address: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(String(500), default="")
    image_url: Mapped[str | None] = mapped_column(String(500))
    # Credit for the cover photo (author, licence, source) shown under the image.
    image_credit: Mapped[dict] = mapped_column(JSONB, default=dict)
    min_order_value: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    delivery_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("29.00"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Trust layer: what the customer can verify about the kitchen itself.
    fssai_license: Mapped[str | None] = mapped_column(String(20))
    fssai_valid_until: Mapped[date | None] = mapped_column(Date)
    kitchen_type: Mapped[str] = mapped_column(String(20), default="dine_in")
    price_parity: Mapped[bool] = mapped_column(Boolean, default=True)
    google_place_id: Mapped[str | None] = mapped_column(String(160))
    place_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    place_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MenuItem(Base):
    __tablename__ = "menu_items"
    __table_args__ = (Index("ix_menu_items_restaurant", "restaurant_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(120))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    category: Mapped[str] = mapped_column(String(60))
    veg: Mapped[bool] = mapped_column(Boolean, default=True)
    prep_complexity: Mapped[int] = mapped_column(Integer, default=1)
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    description: Mapped[str] = mapped_column(String(500), default="")
    image_url: Mapped[str | None] = mapped_column(String(500))
    image_credit: Mapped[dict] = mapped_column(JSONB, default=dict)
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    # Portion truth: declared or measured quantity shown before ordering.
    portion_grams: Mapped[int | None] = mapped_column(Integer)
    portion_serves: Mapped[int | None] = mapped_column(Integer)
    portion_pieces: Mapped[int | None] = mapped_column(Integer)
    portion_method: Mapped[str] = mapped_column(String(20), default="unknown")
    portion_confidence: Mapped[float | None] = mapped_column(Float)
    portion_photo_url: Mapped[str | None] = mapped_column(String(500))
    portion_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingredients: Mapped[list[str]] = mapped_column(JSONB, default=list)
    # Cached nutrition estimate (per 100 g plus provenance); computed once per dish.
    nutrition: Mapped[dict] = mapped_column(JSONB, default=dict)


class Rider(Base):
    __tablename__ = "riders"
    __table_args__ = (Index("ix_riders_status", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    name: Mapped[str] = mapped_column(String(120))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    location_source: Mapped[str] = mapped_column(String(16), default="simulated")
    location_accuracy_m: Mapped[float | None] = mapped_column(Float)
    status: Mapped[RiderStatus] = mapped_column(
        SAEnum(RiderStatus, name="rider_status"), default=RiderStatus.OFFLINE
    )
    active_order_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    capacity: Mapped[int] = mapped_column(Integer, default=2)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    vehicle: Mapped[str] = mapped_column(String(40), default="bike")
    vehicle_registration: Mapped[str | None] = mapped_column(String(40))
    verification_status: Mapped[str] = mapped_column(String(20), default="APPROVED")
    average_rating: Mapped[float] = mapped_column(Float, default=5.0)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_status", "status"),
        Index("ix_orders_customer", "customer_id"),
        Index("ix_orders_batch", "batch_id"),
        CheckConstraint("total_price >= 0", name="ck_orders_total_price_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.user_id", ondelete="RESTRICT")
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="RESTRICT")
    )
    rider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("riders.id", ondelete="SET NULL")
    )
    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(OrderStatus, name="order_status"), default=OrderStatus.PLACED
    )
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    promised_eta_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    drop_lat: Mapped[float] = mapped_column(Float)
    drop_lng: Mapped[float] = mapped_column(Float)
    total_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    reassign_count: Mapped[int] = mapped_column(Integer, default=0)
    delay_flags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    order_number: Mapped[str | None] = mapped_column(String(24), unique=True)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    delivery_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("29.00"))
    discount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    tax: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    payment_method: Mapped[str] = mapped_column(String(20), default="COD")
    payment_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    customer_phone: Mapped[str | None] = mapped_column(String(24))
    delivery_address: Mapped[str | None] = mapped_column(String(255))
    delivery_instructions: Mapped[str | None] = mapped_column(String(500))
    coupon_code: Mapped[str | None] = mapped_column(String(30))
    estimated_prep_min: Mapped[int | None] = mapped_column(Integer)
    actual_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_distance_km: Mapped[float | None] = mapped_column(Float)
    # Proof of delivery: a door OTP plus a GPS geofence check at handover.
    delivery_otp: Mapped[str | None] = mapped_column(String(6))
    otp_attempts: Mapped[int] = mapped_column(Integer, default=0)
    delivery_proof: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Consent-based batching: "shared" orders may ride with a same-route order.
    delivery_mode: Mapped[str] = mapped_column(String(10), default="solo")
    shared_saving: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    batch_sequence: Mapped[int | None] = mapped_column(Integer)
    # Fair-delay accounting: who caused lateness and what the customer got back.
    compensation: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    delay_attribution: Mapped[dict] = mapped_column(JSONB, default=dict)

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderItem.name",
    )


class OrderNumberCounter(Base):
    """Per-year checkout counter allocated atomically by PostgreSQL."""

    __tablename__ = "order_number_counters"

    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer, default=0)


class PaymentAttempt(Base):
    """The provider-facing payment record for a marketplace order.

    Card/UPI details never enter FoodFlow.  This table stores only provider
    references and the verified outcome needed to decide whether a restaurant
    may fulfil an online order.
    """

    __tablename__ = "payment_attempts"
    __table_args__ = (
        UniqueConstraint("order_id", "provider", name="uq_payment_attempt_order_provider"),
        UniqueConstraint("provider", "provider_order_id", name="uq_payment_provider_order"),
        UniqueConstraint("provider", "provider_payment_id", name="uq_payment_provider_payment"),
        Index("ix_payment_attempts_provider_order", "provider", "provider_order_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED")
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    provider_order_id: Mapped[str | None] = mapped_column(String(100))
    provider_payment_id: Mapped[str | None] = mapped_column(String(100))
    signature_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaymentWebhookReceipt(Base):
    """Durable webhook deduplication key; raw payment payloads are not retained."""

    __tablename__ = "payment_webhook_receipts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_payment_webhook_event"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (CheckConstraint("qty > 0", name="ck_order_items_qty_positive"),)

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), primary_key=True
    )
    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="RESTRICT"), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(120))
    qty: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    order: Mapped["Order"] = relationship(back_populates="items")


class OrderEvent(Base):
    __tablename__ = "order_events"
    __table_args__ = (Index("ix_order_events_order_created", "order_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE")
    )
    type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TrainingRow(Base):
    __tablename__ = "training_rows"
    __table_args__ = (
        Index("ix_training_rows_completed_at", "completed_at"),
        Index("ix_training_rows_source", "source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    features_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    actual_prep_min: Mapped[float] = mapped_column(Float)
    actual_drive_min: Mapped[float] = mapped_column(Float)
    actual_total_min: Mapped[float] = mapped_column(Float)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source: Mapped[str] = mapped_column(String(40), default="live")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (Index("ix_model_versions_created_at", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(40), default="eta")
    version: Mapped[str] = mapped_column(String(80), unique=True)
    artifact_path: Mapped[str | None] = mapped_column(String(255))
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RestaurantStaff(Base):
    __tablename__ = "restaurant_staff"
    __table_args__ = (UniqueConstraint("restaurant_id", "user_id", name="uq_restaurant_staff"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CustomerAddress(Base):
    __tablename__ = "customer_addresses"
    __table_args__ = (Index("ix_customer_addresses_customer", "customer_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.user_id", ondelete="CASCADE")
    )
    label: Mapped[str] = mapped_column(String(40), default="Home")
    line1: Mapped[str] = mapped_column(String(200))
    line2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(80), default="Hyderabad")
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    phone: Mapped[str | None] = mapped_column(String(24))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Cart(Base):
    __tablename__ = "carts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.user_id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    restaurant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="SET NULL")
    )
    coupon_code: Mapped[str | None] = mapped_column(String(30))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    items: Mapped[list["CartItem"]] = relationship(
        back_populates="cart", cascade="all, delete-orphan", order_by="CartItem.added_at"
    )


class CartItem(Base):
    __tablename__ = "cart_items"
    __table_args__ = (
        UniqueConstraint("cart_id", "menu_item_id", name="uq_cart_item"),
        CheckConstraint("qty > 0", name="ck_cart_items_qty_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    cart_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("carts.id", ondelete="CASCADE"), index=True
    )
    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="CASCADE")
    )
    qty: Mapped[int] = mapped_column(Integer)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    rescue_listing_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rescue_listings.id", ondelete="SET NULL")
    )

    cart: Mapped[Cart] = relationship(back_populates="items")


class DeliveryAssignment(Base):
    __tablename__ = "delivery_assignments"
    __table_args__ = (
        Index("ix_delivery_assignments_order", "order_id"),
        Index("ix_delivery_assignments_rider", "rider_id"),
        Index("ix_delivery_assignments_status", "status"),
        Index(
            "uq_delivery_assignments_open_offer",
            "order_id",
            unique=True,
            postgresql_where=text("status = 'OFFERED'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE")
    )
    rider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("riders.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(30), default="OFFERED")
    offered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    arrived_restaurant_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pickup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    arrived_customer_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimated_pickup_min: Mapped[float] = mapped_column(Float, default=0.0)
    estimated_delivery_min: Mapped[float] = mapped_column(Float, default=0.0)
    rejection_reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TrackingPoint(Base):
    __tablename__ = "tracking_points"
    __table_args__ = (Index("ix_tracking_points_order_created", "order_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE")
    )
    rider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("riders.id", ondelete="CASCADE")
    )
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EtaPrediction(Base):
    __tablename__ = "eta_predictions"
    __table_args__ = (Index("ix_eta_predictions_order_created", "order_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE")
    )
    predicted_minutes: Mapped[float] = mapped_column(Float)
    lower_bound_minutes: Mapped[float] = mapped_column(Float)
    upper_bound_minutes: Mapped[float] = mapped_column(Float)
    prediction_source: Mapped[str] = mapped_column(String(20), default="model")
    model_version: Mapped[str | None] = mapped_column(String(80))
    actual_minutes: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DeliveryEarning(Base):
    __tablename__ = "delivery_earnings"
    __table_args__ = (Index("ix_delivery_earnings_rider_created", "rider_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), unique=True
    )
    rider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("riders.id", ondelete="CASCADE")
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    distance_km: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("restaurant_rating BETWEEN 1 AND 5", name="ck_reviews_restaurant_rating"),
        CheckConstraint(
            "rider_rating IS NULL OR rider_rating BETWEEN 1 AND 5",
            name="ck_reviews_rider_rating",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), unique=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.user_id", ondelete="CASCADE"), index=True
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), index=True
    )
    rider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("riders.id", ondelete="SET NULL")
    )
    restaurant_rating: Mapped[int] = mapped_column(Integer)
    rider_rating: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
    quantity_feedback: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_created", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(String(500))
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE")
    )
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KitchenPhoto(Base):
    """A dated photo the restaurant takes of its own kitchen, shown to customers."""

    __tablename__ = "kitchen_photos"
    __table_args__ = (Index("ix_kitchen_photos_restaurant_taken", "restaurant_id", "taken_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE")
    )
    url: Mapped[str] = mapped_column(String(500))
    caption: Mapped[str] = mapped_column(String(160), default="")
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RescueListing(Base):
    """Surplus food offered before closing at a price that falls over time."""

    __tablename__ = "rescue_listings"
    __table_args__ = (
        Index("ix_rescue_listings_status_ends", "status", "ends_at"),
        CheckConstraint("qty_left >= 0", name="ck_rescue_listings_qty_left"),
        CheckConstraint("floor_price > 0", name="ck_rescue_listings_floor_price"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), index=True
    )
    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="CASCADE")
    )
    qty_total: Mapped[int] = mapped_column(Integer)
    qty_left: Mapped[int] = mapped_column(Integer)
    original_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    start_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    floor_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="LIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PrepLog(Base):
    """How many portions of a dish the kitchen prepared today (input to the forecast)."""

    __tablename__ = "prep_logs"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "menu_item_id", "day", name="uq_prep_log_item_day"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), index=True
    )
    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="CASCADE")
    )
    day: Mapped[date] = mapped_column(Date)
    prepared_qty: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AiUsage(Base):
    """One row per paid AI/maps call (or cache hit) so cost stays visible."""

    __tablename__ = "ai_usage"
    __table_args__ = (Index("ix_ai_usage_created", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    provider: Mapped[str] = mapped_column(String(30))
    purpose: Mapped[str] = mapped_column(String(40))
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    est_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    detail: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
