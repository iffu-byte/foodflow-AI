from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import BadRequestError, ConflictError, NotFoundError
from app.domain.models import Cart, CartItem, MenuItem, RescueListing, Restaurant
from app.marketplace import pricing
from app.marketplace.schemas import (
    CartItemIn,
    CartItemUpdate,
    CartLineOut,
    CartOut,
    CartRestaurantOut,
)
from app.nutrition import service as nutrition_service
from app.rescue import service as rescue_service

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


async def effective_prices(
    session: AsyncSession, lines: list[tuple[CartItem, MenuItem]]
) -> dict[UUID, tuple[Decimal, RescueListing | None]]:
    """Price each line now: the live rescue price when it applies, else the menu price.

    A rescue deal that has ended or sold out silently returns the line to menu
    price, and the stale link is cleared so the customer sees the real bill.
    """
    prices: dict[UUID, tuple[Decimal, RescueListing | None]] = {}
    for item, menu_item in lines:
        listing = None
        if item.rescue_listing_id is not None:
            listing = await session.get(RescueListing, item.rescue_listing_id)
            if listing is None or not rescue_service.is_live(listing):
                item.rescue_listing_id = None
                listing = None
        price = rescue_service.price_at(listing) if listing is not None else menu_item.price
        prices[item.id] = (price, listing)
    return prices


async def cart_out(session: AsyncSession, cart: Cart) -> CartOut:
    lines = await _load_lines(session, cart)
    restaurant = (
        await session.get(Restaurant, cart.restaurant_id)
        if cart.restaurant_id is not None
        else None
    )
    prices = await effective_prices(session, lines)
    subtotal = sum(
        (prices[item.id][0] * item.qty for item, _ in lines),
        start=Decimal("0.00"),
    )
    rescue_saving = sum(
        ((menu_item.price - prices[item.id][0]) * item.qty for item, menu_item in lines),
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

    await nutrition_service.ensure_for_items(session, [menu_item for _, menu_item in lines])
    totals = {"kcal": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
    allergens: set[str] = set()
    out_lines = []
    for item, menu_item in lines:
        view = nutrition_service.portion_view(menu_item)
        for key in totals:
            totals[key] += view[key] * item.qty
        allergens.update(view["allergens"])
        price, listing = prices[item.id]
        out_lines.append(
            CartLineOut(
                id=item.id,
                menu_item_id=menu_item.id,
                name=menu_item.name,
                price=price,
                qty=item.qty,
                veg=menu_item.veg,
                available=menu_item.available,
                line_total=price * item.qty,
                original_price=menu_item.price if listing is not None else None,
                rescue_listing_id=listing.id if listing is not None else None,
                rescue_ends_at=listing.ends_at if listing is not None else None,
                kcal=view["kcal"],
                protein_g=view["protein_g"],
            )
        )
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
        items=out_lines,
        item_count=sum(item.qty for item, _ in lines),
        subtotal=quoted.subtotal,
        delivery_fee=quoted.delivery_fee,
        discount=quoted.discount,
        tax=quoted.tax,
        total=quoted.total,
        coupon_code=coupon_code,
        nutrition=(
            {
                **{key: round(value, 1) for key, value in totals.items()},
                "allergens": sorted(allergens),
                "estimate": True,
            }
            if lines
            else None
        ),
        rescue_saving=pricing.money(rescue_saving),
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

    listing = None
    if payload.rescue_listing_id is not None:
        listing = await session.get(RescueListing, payload.rescue_listing_id)
        if (
            listing is None
            or listing.menu_item_id != menu_item.id
            or not rescue_service.is_live(listing)
        ):
            raise BadRequestError("this rescue deal is no longer available")

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
    limit = min(MAX_QTY, listing.qty_left) if listing is not None else MAX_QTY
    if line is None:
        session.add(
            CartItem(
                cart_id=cart.id,
                menu_item_id=menu_item.id,
                qty=min(limit, payload.qty),
                rescue_listing_id=listing.id if listing is not None else None,
            )
        )
    else:
        if listing is not None:
            line.rescue_listing_id = listing.id
        elif line.rescue_listing_id is not None:
            rescue = await session.get(RescueListing, line.rescue_listing_id)
            if rescue is not None and rescue_service.is_live(rescue):
                limit = min(MAX_QTY, rescue.qty_left)
        line.qty = min(limit, line.qty + payload.qty)
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
        if line.rescue_listing_id is not None:
            listing = await session.get(RescueListing, line.rescue_listing_id)
            if listing is not None and rescue_service.is_live(listing):
                if payload.qty > listing.qty_left:
                    raise BadRequestError(
                        f"only {listing.qty_left} left in this rescue deal"
                    )
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
    prices = await effective_prices(session, lines)
    subtotal = sum(
        (prices[item.id][0] * item.qty for item, _ in lines),
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
