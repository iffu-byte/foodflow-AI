from app.domain.models import Order
from app.domain.schemas import OrderItemOut
from app.marketplace.schemas import MarketOrderOut, NotificationOut


def order_out(
    order: Order,
    *,
    restaurant_name: str,
    rider_name: str | None = None,
    can_review: bool = False,
) -> MarketOrderOut:
    return MarketOrderOut(
        id=order.id,
        order_number=order.order_number,
        customer_id=order.customer_id,
        restaurant_id=order.restaurant_id,
        restaurant_name=restaurant_name,
        rider_id=order.rider_id,
        rider_name=rider_name,
        status=order.status,
        items=[OrderItemOut.model_validate(item) for item in order.items],
        subtotal=order.subtotal,
        delivery_fee=order.delivery_fee,
        discount=order.discount,
        tax=order.tax,
        total_amount=order.total_price,
        payment_method=order.payment_method,
        payment_status=order.payment_status,
        placed_at=order.placed_at,
        promised_eta_at=order.promised_eta_at,
        deadline_at=order.deadline_at,
        actual_delivery_at=order.actual_delivery_at,
        drop_lat=order.drop_lat,
        drop_lng=order.drop_lng,
        delivery_address=order.delivery_address,
        customer_phone=order.customer_phone,
        delivery_instructions=order.delivery_instructions,
        estimated_prep_min=order.estimated_prep_min,
        delay_flags=order.delay_flags or [],
        reassign_count=order.reassign_count,
        can_review=can_review,
    )


def notification_out(notification) -> NotificationOut:
    return NotificationOut(
        id=notification.id,
        type=notification.type,
        title=notification.title,
        body=notification.body,
        order_id=notification.order_id,
        is_read=notification.is_read,
        created_at=notification.created_at,
    )


def browse_out(restaurant, distance_km: float | None = None):
    from app.marketplace.schemas import RestaurantBrowseOut

    return RestaurantBrowseOut(
        id=restaurant.id,
        name=restaurant.name,
        cuisine=restaurant.cuisine or [],
        rating=restaurant.rating,
        rating_count=restaurant.rating_count,
        avg_prep_min=restaurant.avg_prep_min,
        min_order_value=restaurant.min_order_value,
        delivery_fee=restaurant.delivery_fee,
        address=restaurant.address,
        description=restaurant.description,
        image_url=restaurant.image_url,
        is_active=restaurant.is_active,
        distance_km=round(distance_km, 2) if distance_km is not None else None,
    )
