from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain import service as domain_service
from app.domain.exceptions import BadRequestError, ConflictError, NotFoundError
from app.domain.models import (
    Cart,
    CartItem,
    Customer,
    CustomerAddress,
    DeliveryAssignment,
    MenuItem,
    Order,
    OrderStatus,
    Restaurant,
    RestaurantStaff,
    Review,
    Rider,
    User,
)
from app.marketplace import access, notifications
from app.marketplace.cart import cart_out
from app.marketplace.schemas import (
    AddressIn,
    AddressOut,
    MarketOrderOut,
    ProfileOut,
    ProfileUpdate,
    ReviewIn,
    ReviewOut,
)
from app.marketplace.serializers import order_out
from app.realtime import service as realtime_service


async def _restaurant_name(session: AsyncSession, restaurant_id: UUID) -> str:
    restaurant = await session.get(Restaurant, restaurant_id)
    return restaurant.name if restaurant is not None else "Restaurant"


async def _order_view(
    session: AsyncSession, order: Order, reviewed_ids: set[UUID] | None = None
) -> MarketOrderOut:
    rider_name = None
    if order.rider_id is not None:
        rider = await session.get(Rider, order.rider_id)
        rider_name = rider.name if rider is not None else None
    restaurant_name = await _restaurant_name(session, order.restaurant_id)
    can_review = (
        reviewed_ids is not None
        and order.status is OrderStatus.DELIVERED
        and order.id not in reviewed_ids
    )
    return order_out(
        order,
        restaurant_name=restaurant_name,
        rider_name=rider_name,
        can_review=can_review,
    )


async def list_orders(session: AsyncSession, customer_id: UUID) -> list[MarketOrderOut]:
    orders = list(
        (
            await session.execute(
                select(Order)
                .options(selectinload(Order.items))
                .where(Order.customer_id == customer_id)
                .order_by(Order.placed_at.desc())
            )
        )
        .scalars()
        .all()
    )
    reviewed = set(
        (
            await session.execute(
                select(Review.order_id).where(Review.customer_id == customer_id)
            )
        ).scalars()
    )
    return [await _order_view(session, order, reviewed) for order in orders]


async def order_detail(
    session: AsyncSession, user: User, order_id: UUID
) -> MarketOrderOut:
    order = await domain_service.get_order(session, order_id)
    await access.assert_can_view_order(session, user, order)
    reviewed = set(
        (
            await session.execute(
                select(Review.order_id).where(Review.order_id == order_id)
            )
        ).scalars()
    )
    return await _order_view(session, order, reviewed)


async def cancel_order(
    session: AsyncSession, user: User, order_id: UUID, reason: str | None
) -> MarketOrderOut:
    order = await domain_service.get_order(session, order_id)
    if order.customer_id != user.id:
        raise NotFoundError("order not found")
    if order.status in (OrderStatus.PICKED_UP, OrderStatus.DELIVERED):
        raise ConflictError("an order cannot be cancelled after pickup")
    order, event = await domain_service.transition_order(
        session,
        order_id,
        OrderStatus.CANCELLED,
        actor="customer",
        reason=reason or "cancelled by customer",
    )
    manager_ids = (
        await session.execute(
            select(RestaurantStaff.user_id).where(
                RestaurantStaff.restaurant_id == order.restaurant_id
            )
        )
    ).scalars()
    rows = [
        await notifications.add(
            session,
            manager_id,
            "ORDER_CANCELLED",
            "Order cancelled",
            f"{order.order_number or order.id} was cancelled by the customer.",
            order.id,
        )
        for manager_id in manager_ids
    ]
    assignments = (
        await session.execute(
            select(DeliveryAssignment).where(
                DeliveryAssignment.order_id == order.id,
                DeliveryAssignment.status.in_(
                    ("OFFERED", "ACCEPTED", "ARRIVED_AT_RESTAURANT", "PICKED_UP")
                ),
            ).with_for_update()
        )
    ).scalars()
    for assignment in assignments:
        if assignment.status == "OFFERED":
            assignment.status = "EXPIRED"
        elif assignment.status != "PICKED_UP":
            assignment.status = "CANCELLED"
    if order.rider_id is not None:
        rider = await session.get(Rider, order.rider_id)
        if rider is not None:
            rows.append(
                await notifications.add(
                    session,
                    rider.user_id,
                    "ORDER_CANCELLED",
                    "Delivery cancelled",
                    f"{order.order_number or order.id} was cancelled.",
                    order.id,
                )
            )
    rows.extend(
        await notifications.notify_admins(
            session,
            "ORDER_CANCELLED",
            "Order cancelled",
            f"{order.order_number or order.id} was cancelled.",
            order.id,
        )
    )
    await session.commit()
    order = await domain_service.get_order(session, order.id)
    await realtime_service.publish_order_event(order, event)
    await notifications.publish(rows)
    return await _order_view(session, order)


async def reorder(session: AsyncSession, customer_id: UUID, order_id: UUID):
    order = await domain_service.get_order(session, order_id)
    if order.customer_id != customer_id:
        raise NotFoundError("order not found")
    menu_ids = [item.menu_item_id for item in order.items]
    menu_rows = (
        await session.execute(select(MenuItem).where(MenuItem.id.in_(menu_ids)))
    ).scalars().all()
    menu = {item.id: item for item in menu_rows}
    unavailable = [
        item.name
        for item in order.items
        if item.menu_item_id not in menu or not menu[item.menu_item_id].available
    ]
    if unavailable:
        raise BadRequestError(f"unavailable items: {', '.join(unavailable)}")

    cart = (
        await session.execute(select(Cart).where(Cart.customer_id == customer_id))
    ).scalar_one_or_none()
    if cart is None:
        cart = Cart(customer_id=customer_id)
        session.add(cart)
        await session.flush()
    cart.items.clear()
    cart.restaurant_id = order.restaurant_id
    cart.coupon_code = None
    for item in order.items:
        cart.items.append(
            CartItem(menu_item_id=item.menu_item_id, qty=item.qty)
        )
    await session.commit()
    await session.refresh(cart)
    return await cart_out(session, cart)


async def create_review(
    session: AsyncSession, user: User, order_id: UUID, payload: ReviewIn
) -> ReviewOut:
    order = await domain_service.get_order(session, order_id)
    if order.customer_id != user.id:
        raise NotFoundError("order not found")
    if order.status is not OrderStatus.DELIVERED:
        raise BadRequestError("only delivered orders can be reviewed")
    existing = await session.scalar(select(Review).where(Review.order_id == order.id))
    if existing is not None:
        raise ConflictError("this order already has a review")

    review = Review(
        order_id=order.id,
        customer_id=user.id,
        restaurant_id=order.restaurant_id,
        rider_id=order.rider_id,
        restaurant_rating=payload.restaurant_rating,
        rider_rating=payload.rider_rating,
        comment=payload.comment,
    )
    session.add(review)

    restaurant = await session.get(Restaurant, order.restaurant_id)
    if restaurant is not None:
        aggregate = (
            await session.execute(
                select(func.avg(Review.restaurant_rating), func.count())
                .where(Review.restaurant_id == restaurant.id)
            )
        ).one()
        restaurant.rating = Decimal(
            str(round(float(aggregate[0] or payload.restaurant_rating), 1))
        )
        restaurant.rating_count = int(aggregate[1] or 0)

    if order.rider_id is not None and payload.rider_rating is not None:
        rider = await session.get(Rider, order.rider_id)
        if rider is not None:
            average = await session.scalar(
                select(func.avg(Review.rider_rating)).where(
                    Review.rider_id == order.rider_id,
                    Review.rider_rating.is_not(None),
                )
            )
            rider.average_rating = round(float(average or payload.rider_rating), 2)

    await session.commit()
    await session.refresh(review)
    return ReviewOut(
        id=review.id,
        order_id=review.order_id,
        restaurant_rating=review.restaurant_rating,
        rider_rating=review.rider_rating,
        comment=review.comment,
        created_at=review.created_at,
    )


async def profile(session: AsyncSession, user: User, customer: Customer) -> ProfileOut:
    return ProfileOut(
        id=user.id,
        name=user.name,
        email=user.email,
        phone=user.phone,
        home_lat=customer.home_lat,
        home_lng=customer.home_lng,
        budget_pref=customer.budget_pref,
        diet_pref=customer.diet_pref,
    )


async def update_profile(
    session: AsyncSession, user: User, customer: Customer, payload: ProfileUpdate
) -> ProfileOut:
    updates = payload.model_dump(exclude_unset=True)
    if updates.get("name") is not None:
        user.name = updates["name"]
    if "phone" in updates:
        user.phone = updates["phone"]
    if "budget_pref" in updates:
        customer.budget_pref = updates["budget_pref"]
    if "diet_pref" in updates:
        customer.diet_pref = updates["diet_pref"]
    if updates.get("home_lat") is not None:
        customer.home_lat = updates["home_lat"]
    if updates.get("home_lng") is not None:
        customer.home_lng = updates["home_lng"]
    await session.commit()
    return await profile(session, user, customer)


def address_out(address: CustomerAddress) -> AddressOut:
    return AddressOut(
        id=address.id,
        label=address.label,
        line1=address.line1,
        line2=address.line2,
        city=address.city,
        lat=address.lat,
        lng=address.lng,
        phone=address.phone,
        is_default=address.is_default,
    )


async def list_addresses(session: AsyncSession, customer_id: UUID) -> list[AddressOut]:
    rows = (
        await session.execute(
            select(CustomerAddress)
            .where(CustomerAddress.customer_id == customer_id)
            .order_by(CustomerAddress.is_default.desc(), CustomerAddress.created_at)
        )
    ).scalars()
    return [address_out(row) for row in rows]


async def _clear_default(session: AsyncSession, customer_id: UUID) -> None:
    rows = (
        await session.execute(
            select(CustomerAddress).where(
                CustomerAddress.customer_id == customer_id,
                CustomerAddress.is_default.is_(True),
            )
        )
    ).scalars()
    for row in rows:
        row.is_default = False


async def add_address(
    session: AsyncSession, customer_id: UUID, payload: AddressIn
) -> AddressOut:
    if payload.is_default:
        await _clear_default(session, customer_id)
    address = CustomerAddress(
        customer_id=customer_id,
        label=payload.label,
        line1=payload.line1,
        line2=payload.line2,
        city=payload.city,
        lat=payload.lat,
        lng=payload.lng,
        phone=payload.phone,
        is_default=payload.is_default,
    )
    session.add(address)
    await session.commit()
    await session.refresh(address)
    return address_out(address)


async def update_address(
    session: AsyncSession,
    customer_id: UUID,
    address_id: UUID,
    payload: AddressIn,
) -> AddressOut:
    address = await session.get(CustomerAddress, address_id)
    if address is None or address.customer_id != customer_id:
        raise NotFoundError("address not found")
    if payload.is_default and not address.is_default:
        await _clear_default(session, customer_id)
    address.label = payload.label
    address.line1 = payload.line1
    address.line2 = payload.line2
    address.city = payload.city
    address.lat = payload.lat
    address.lng = payload.lng
    address.phone = payload.phone
    address.is_default = payload.is_default
    await session.commit()
    await session.refresh(address)
    return address_out(address)


async def delete_address(
    session: AsyncSession, customer_id: UUID, address_id: UUID
) -> None:
    address = await session.get(CustomerAddress, address_id)
    if address is None or address.customer_id != customer_id:
        raise NotFoundError("address not found")
    await session.delete(address)
    await session.commit()
