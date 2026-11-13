from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import NotFoundError
from app.domain.models import (
    Customer,
    Order,
    Restaurant,
    RestaurantStaff,
    Rider,
    Role,
    User,
)


async def customer_for(session: AsyncSession, user: User) -> Customer:
    customer = await session.get(Customer, user.id)
    if customer is None:
        raise NotFoundError("customer profile not found")
    return customer


async def rider_for(session: AsyncSession, user: User) -> Rider:
    rider = (
        await session.execute(select(Rider).where(Rider.user_id == user.id))
    ).scalar_one_or_none()
    if rider is None:
        raise NotFoundError("rider profile not found")
    return rider


async def restaurant_for(session: AsyncSession, user: User) -> Restaurant:
    restaurant = (
        await session.execute(
            select(Restaurant)
            .join(RestaurantStaff, RestaurantStaff.restaurant_id == Restaurant.id)
            .where(RestaurantStaff.user_id == user.id)
        )
    ).scalar_one_or_none()
    if restaurant is None:
        raise NotFoundError("no restaurant is assigned to this account")
    return restaurant


async def can_view_order(session: AsyncSession, user: User, order: Order) -> bool:
    if user.role is Role.ADMIN:
        return True
    if user.role is Role.CUSTOMER:
        return order.customer_id == user.id
    if user.role is Role.RIDER:
        rider = (
            await session.execute(select(Rider).where(Rider.user_id == user.id))
        ).scalar_one_or_none()
        return rider is not None and order.rider_id == rider.id
    if user.role is Role.RESTAURANT:
        staff = (
            await session.execute(
                select(RestaurantStaff).where(RestaurantStaff.user_id == user.id)
            )
        ).scalar_one_or_none()
        return staff is not None and staff.restaurant_id == order.restaurant_id
    return False


async def assert_can_view_order(session: AsyncSession, user: User, order: Order) -> None:
    if not await can_view_order(session, user, order):
        raise NotFoundError("order not found")


async def restaurant_ids_for(session: AsyncSession, user: User) -> list[UUID]:
    rows = (
        await session.execute(
            select(RestaurantStaff.restaurant_id).where(RestaurantStaff.user_id == user.id)
        )
    ).scalars()
    return list(rows)
