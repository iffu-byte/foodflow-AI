from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.domain import service as domain_service
from app.domain.exceptions import BadRequestError, NotFoundError
from app.domain.geo import haversine_km
from app.domain.models import (
    Cart,
    Customer,
    CustomerAddress,
    EtaPrediction,
    MenuItem,
    Order,
    OrderEvent,
    OrderItem,
    OrderNumberCounter,
    OrderStatus,
    Restaurant,
    RestaurantStaff,
    Rider,
    User,
)
from app.eta.service import estimate_for_order
from app.marketplace import delivery_proof, notifications, pricing
from app.marketplace.schemas import CheckoutIn, MarketOrderOut, PaymentCheckoutOut
from app.marketplace.serializers import order_out
from app.payments import service as payment_service
from app.realtime import service as realtime_service
from app.rescue import service as rescue_service


async def _next_order_number(session: AsyncSession) -> str:
    year = datetime.now(UTC).year
    value = await session.scalar(
        insert(OrderNumberCounter)
        .values(year=year, next_value=1)
        .on_conflict_do_update(
            index_elements=[OrderNumberCounter.year],
            set_={"next_value": OrderNumberCounter.next_value + 1},
        )
        .returning(OrderNumberCounter.next_value)
    )
    if value is None:
        raise BadRequestError("could not allocate an order number")
    return f"FF-{year}-{int(value):06d}"


async def _address(
    session: AsyncSession, customer: Customer, user: User, address_id: UUID | None
) -> tuple[float, float, str, str | None]:
    if address_id is not None:
        address = await session.get(CustomerAddress, address_id)
        if address is None or address.customer_id != customer.user_id:
            raise NotFoundError("delivery address not found")
        label = f"{address.line1}, {address.city}"
        return address.lat, address.lng, label, address.phone or user.phone
    default = (
        await session.execute(
            select(CustomerAddress)
            .where(CustomerAddress.customer_id == customer.user_id)
            .order_by(CustomerAddress.is_default.desc(), CustomerAddress.created_at)
        )
    ).scalars().first()
    if default is not None:
        return (
            default.lat,
            default.lng,
            f"{default.line1}, {default.city}",
            default.phone or user.phone,
        )
    return customer.home_lat, customer.home_lng, "Home", user.phone


async def notify_paid_order(
    session: AsyncSession, order: Order, restaurant: Restaurant | None = None
) -> list:
    """Queue restaurant visibility only after online payment confirmation."""
    if restaurant is None:
        restaurant = await session.get(Restaurant, order.restaurant_id)
    restaurant_name = restaurant.name if restaurant is not None else "the restaurant"
    item_count = sum(item.qty for item in order.items)
    rows = [
        await notifications.add(
            session,
            order.customer_id,
            "PAYMENT_CONFIRMED",
            "Payment confirmed",
            f"{order.order_number} is now with {restaurant_name}.",
            order.id,
        )
    ]
    managers = (
        await session.execute(
            select(RestaurantStaff.user_id).where(
                RestaurantStaff.restaurant_id == order.restaurant_id
            )
        )
    ).scalars()
    for manager_id in managers:
        rows.append(
            await notifications.add(
                session,
                manager_id,
                "ORDER_RECEIVED",
                "New paid order",
                f"{order.order_number} - {item_count} items.",
                order.id,
            )
        )
    rows.extend(
        await notifications.notify_admins(
            session,
            "ORDER_RECEIVED",
            "New paid order",
            f"{order.order_number} at {restaurant_name}.",
            order.id,
        )
    )
    return rows


def payment_checkout_out(session: payment_service.CheckoutSession) -> PaymentCheckoutOut:
    return PaymentCheckoutOut(
        provider="razorpay",
        provider_order_id=session.provider_order_id,
        key_id=session.key_id,
        amount_paise=session.amount_paise,
        currency=session.currency,
        display_name=session.display_name,
        description=session.description,
        is_test_mode=session.is_test_mode,
    )


async def checkout(
    session: AsyncSession, user: User, customer: Customer, payload: CheckoutIn
) -> MarketOrderOut:
    cart = (
        await session.execute(
            select(Cart)
            .options(selectinload(Cart.items))
            .where(Cart.customer_id == customer.user_id)
        )
    ).scalar_one_or_none()
    if cart is None or cart.restaurant_id is None:
        raise BadRequestError("your cart is empty")

    restaurant = await session.get(Restaurant, cart.restaurant_id)
    if restaurant is None or not restaurant.is_active:
        raise BadRequestError("restaurant is not accepting orders")

    cart_items = list(cart.items)
    if not cart_items:
        raise BadRequestError("your cart is empty")

    menu_ids = [item.menu_item_id for item in cart_items]
    menu_rows = (
        await session.execute(select(MenuItem).where(MenuItem.id.in_(menu_ids)))
    ).scalars().all()
    menu = {item.id: item for item in menu_rows}
    if len(menu) != len(menu_ids):
        raise BadRequestError("some items in your cart are no longer on the menu")
    for item in cart_items:
        if not menu[item.menu_item_id].available:
            raise BadRequestError(f"{menu[item.menu_item_id].name} is unavailable")
        if item.qty < 1:
            raise BadRequestError("invalid item quantity")

    # Rescue lines are claimed under a row lock at today's falling price.
    unit_prices: dict = {}
    rescued: list[dict] = []
    for item in cart_items:
        unit_prices[item.menu_item_id] = menu[item.menu_item_id].price
        if item.rescue_listing_id is not None:
            listing, price = await rescue_service.claim(
                session, item.rescue_listing_id, item.qty
            )
            unit_prices[item.menu_item_id] = price
            rescued.append(
                {
                    "listing_id": str(listing.id),
                    "menu_item_id": str(item.menu_item_id),
                    "qty": item.qty,
                    "price": str(price),
                }
            )
    subtotal = sum(
        (unit_prices[item.menu_item_id] * item.qty for item in cart_items),
        start=Decimal("0.00"),
    )
    if subtotal < restaurant.min_order_value:
        raise BadRequestError(
            f"minimum order value for {restaurant.name} is {restaurant.min_order_value}"
        )

    coupon = payload.coupon_code or cart.coupon_code
    quoted = pricing.quote(
        subtotal,
        restaurant.delivery_fee,
        coupon,
        shared=payload.delivery_mode == "shared",
        shared_saving=Decimal(str(settings.shared_ride_saving)),
    )
    drop_lat, drop_lng, address_text, phone = await _address(
        session, customer, user, payload.address_id
    )
    if not phone:
        phone = user.phone
    if not phone:
        raise BadRequestError("a contact phone number is required")

    payment_status = "PAID" if payload.payment_method == "UPI_DEMO" else "PENDING"
    order = Order(
        order_number=await _next_order_number(session),
        customer_id=customer.user_id,
        restaurant_id=restaurant.id,
        status=OrderStatus.PLACED,
        drop_lat=drop_lat,
        drop_lng=drop_lng,
        subtotal=quoted.subtotal,
        delivery_fee=quoted.delivery_fee,
        discount=quoted.discount,
        tax=quoted.tax,
        total_price=quoted.total,
        coupon_code=quoted.coupon_code,
        payment_method=payload.payment_method,
        payment_status=payment_status,
        customer_phone=phone,
        delivery_address=address_text,
        delivery_instructions=payload.instructions,
        estimated_prep_min=restaurant.avg_prep_min,
        delivery_distance_km=round(
            haversine_km(restaurant.lat, restaurant.lng, drop_lat, drop_lng), 2
        ),
        delivery_otp=delivery_proof.generate_otp(),
        delivery_mode=payload.delivery_mode,
        shared_saving=quoted.shared_saving,
    )
    for cart_item in cart_items:
        menu_item = menu[cart_item.menu_item_id]
        order.items.append(
            OrderItem(
                menu_item_id=menu_item.id,
                name=menu_item.name,
                qty=cart_item.qty,
                unit_price=unit_prices[menu_item.id],
            )
        )
    session.add(order)
    await session.flush()

    placed_event = OrderEvent(
        order_id=order.id,
        type="order_placed",
        payload={
            "order_number": order.order_number,
            "total_price": str(order.total_price),
            "item_count": sum(item.qty for item in cart_items),
            "restaurant_id": str(restaurant.id),
            "payment_method": payload.payment_method,
            "delivery_mode": payload.delivery_mode,
            "rescued": rescued,
        },
    )
    session.add(placed_event)

    prediction = await estimate_for_order(session, order, restaurant)
    order.promised_eta_at = order.placed_at + timedelta(minutes=prediction.eta_minutes)
    eta_event = OrderEvent(
        order_id=order.id,
        type="eta_predicted",
        payload={
            **prediction.event_payload(),
            "promised_eta_at": order.promised_eta_at.isoformat(),
        },
    )
    session.add(eta_event)
    session.add(
        EtaPrediction(
            order_id=order.id,
            predicted_minutes=prediction.eta_minutes,
            lower_bound_minutes=prediction.low_minutes,
            upper_bound_minutes=prediction.high_minutes,
            prediction_source=prediction.source,
            model_version=prediction.model_version,
        )
    )
    payment_event = OrderEvent(
        order_id=order.id,
        type="payment_recorded",
        payload={
            "method": payload.payment_method,
            "status": payment_status,
            "amount": str(order.total_price),
        },
    )
    session.add(payment_event)

    payment_checkout = None
    payment_initiated_event = None
    if payload.payment_method == "RAZORPAY":
        payment_session, payment_initiated_event = await payment_service.start_checkout(
            session, order
        )
        payment_checkout = payment_checkout_out(payment_session)
        notification_rows = [
            await notifications.add(
                session,
                customer.user_id,
                "PAYMENT_PENDING",
                "Complete your secure payment",
                f"{order.order_number} will be sent to {restaurant.name} after payment is confirmed.",
                order.id,
            )
        ]
    else:
        notification_rows = await notify_paid_order(session, order, restaurant)

    cart.items.clear()
    cart.restaurant_id = None
    cart.coupon_code = None
    await session.commit()

    order = await domain_service.get_order(session, order.id)
    await realtime_service.publish_order_event(order, placed_event)
    await realtime_service.publish_order_event(order, eta_event)
    await realtime_service.publish_order_event(order, payment_event)
    if payment_initiated_event is not None:
        await realtime_service.publish_order_event(order, payment_initiated_event)
    await notifications.publish(notification_rows)

    rider_name = None
    if order.rider_id is not None:
        rider = await session.get(Rider, order.rider_id)
        rider_name = rider.name if rider is not None else None
    result = order_out(
        order, restaurant_name=restaurant.name, rider_name=rider_name, include_otp=True
    )
    result.payment_checkout = payment_checkout
    return result
