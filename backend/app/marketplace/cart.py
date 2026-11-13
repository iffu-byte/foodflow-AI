from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import BadRequestError, ConflictError, NotFoundError
from app.domain.models import Cart, CartItem, MenuItem, Restaurant
from app.marketplace import pricing
from app.marketplace.schemas import (
    CartItemIn,
    CartItemUpdate,
    CartLineOut,
    CartOut,
    CartRestaurantOut,
)

MAX_QTY = 20


async def _get_or_create(session: AsyncSession, customer_id: UUID) -> Cart:
    cart = (
        await session.execute(select(Cart).where(Cart.customer_id == customer_id))
    ).scalar_one_or_none()
    if cart is None:
        cart = Cart(customer_id=customer_id)
        session.add(cart)
        await session.commit()
        await session.refresh(cart)
    return cart


async def _load_lines(session: AsyncSession, cart: Cart) -> list[tuple[CartItem, MenuItem]]:
    rows = (
        await session.execute(
            select(CartItem, MenuItem)
            .join(MenuItem, MenuItem.id == CartItem.menu_item_id)
            .where(CartItem.cart_id == cart.id)
            .order_by(CartItem.added_at)
        )
    ).all()
    return [(item, menu_item) for item, menu_item in rows]


async def cart_out(session: AsyncSession, cart: Cart) -> CartOut:
    lines = await _load_lines(session, cart)
    restaurant = (
        await session.get(Restaurant, cart.restaurant_id)
        if cart.restaurant_id is not None
        else None
    )
    subtotal = sum(
        (menu_item.price * item.qty for item, menu_item in lines),
        start=Decimal("0.00"),
    )
    fee = restaurant.delivery_fee if restaurant is not None else Decimal("29.00")
    try:
        quoted = pricing.quote(subtotal, fee, cart.coupon_code)
        coupon_code = quoted.coupon_code
    except BadRequestError:
        quoted = pricing.quote(subtotal, fee, None)
        coupon_code = None
        cart.coupon_code = None
        await session.commit()
    return CartOut(
        id=cart.id,
        restaurant=(
            CartRestaurantOut(
                id=restaurant.id,
                name=restaurant.name,
                image_url=restaurant.image_url,
                delivery_fee=restaurant.delivery_fee,
                min_order_value=restaurant.min_order_value,
                avg_prep_min=restaurant.avg_prep_min,
            )
            if restaurant is not None
            else None
        ),
        items=[
            CartLineOut(
                id=item.id,
                menu_item_id=menu_item.id,
                name=menu_item.name,
                price=menu_item.price,
                qty=item.qty,
                veg=menu_item.veg,
                available=menu_item.available,
                line_total=menu_item.price * item.qty,
            )
            for item, menu_item in lines
        ],
        item_count=sum(item.qty for item, _ in lines),
        subtotal=quoted.subtotal,
        delivery_fee=quoted.delivery_fee,
        discount=quoted.discount,
        tax=quoted.tax,
        total=quoted.total,
        coupon_code=coupon_code,
    )


async def get_cart(session: AsyncSession, customer_id: UUID) -> CartOut:
    cart = await _get_or_create(session, customer_id)
    return await cart_out(session, cart)


async def add_item(session: AsyncSession, customer_id: UUID, payload: CartItemIn) -> CartOut:
    menu_item = await session.get(MenuItem, payload.menu_item_id)
    if menu_item is None:
        raise NotFoundError("menu item not found")
    if not menu_item.available:
        raise BadRequestError("this item is currently unavailable")
    restaurant = await session.get(Restaurant, menu_item.restaurant_id)
    if restaurant is None or not restaurant.is_active:
        raise BadRequestError("restaurant is not accepting orders")

    cart = await _get_or_create(session, customer_id)
    existing_lines = await _load_lines(session, cart)
    if existing_lines and cart.restaurant_id != menu_item.restaurant_id:
        raise ConflictError("a cart can contain items from only one restaurant")

    cart.restaurant_id = menu_item.restaurant_id
    line = (
        await session.execute(
            select(CartItem).where(
                CartItem.cart_id == cart.id,
                CartItem.menu_item_id == menu_item.id,
            )
        )
    ).scalar_one_or_none()
    if line is None:
        session.add(CartItem(cart_id=cart.id, menu_item_id=menu_item.id, qty=payload.qty))
    else:
        line.qty = min(MAX_QTY, line.qty + payload.qty)
    await session.commit()
    await session.refresh(cart)
    return await cart_out(session, cart)


async def update_item(
    session: AsyncSession,
    customer_id: UUID,
    line_id: UUID,
    payload: CartItemUpdate,
) -> CartOut:
    cart = await _get_or_create(session, customer_id)
    line = await session.get(CartItem, line_id)
    if line is None or line.cart_id != cart.id:
        raise NotFoundError("cart item not found")
    if payload.qty == 0:
        await session.delete(line)
    else:
        line.qty = payload.qty
    await session.commit()
    remaining = await _load_lines(session, cart)
    if not remaining:
        cart.restaurant_id = None
        cart.coupon_code = None
        await session.commit()
    await session.refresh(cart)
    return await cart_out(session, cart)


async def remove_item(session: AsyncSession, customer_id: UUID, line_id: UUID) -> CartOut:
    return await update_item(session, customer_id, line_id, CartItemUpdate(qty=0))


async def apply_coupon(session: AsyncSession, customer_id: UUID, code: str | None) -> CartOut:
    cart = await _get_or_create(session, customer_id)
    lines = await _load_lines(session, cart)
    subtotal = sum(
        (menu_item.price * item.qty for item, menu_item in lines),
        start=Decimal("0.00"),
    )
    restaurant = (
        await session.get(Restaurant, cart.restaurant_id)
        if cart.restaurant_id is not None
        else None
    )
    fee = restaurant.delivery_fee if restaurant is not None else Decimal("29.00")
    quoted = pricing.quote(subtotal, fee, code)
    cart.coupon_code = quoted.coupon_code
    await session.commit()
    return await cart_out(session, cart)


async def clear_cart(session: AsyncSession, cart: Cart) -> None:
    await session.execute(delete(CartItem).where(CartItem.cart_id == cart.id))
    cart.restaurant_id = None
    cart.coupon_code = None
    await session.flush()
