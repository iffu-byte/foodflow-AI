from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import SessionDep
from app.auth.deps import CustomerUser, OrderViewUser
from app.domain.exceptions import NotFoundError
from app.domain.models import Restaurant
from app.marketplace import access, cart, checkout, customer
from app.marketplace import restaurant as restaurant_service
from app.marketplace.pricing import COUPONS
from app.marketplace.schemas import (
    AddressIn,
    AddressOut,
    CartItemIn,
    CartItemUpdate,
    CartOut,
    CheckoutIn,
    CouponIn,
    CouponOut,
    DeliveryActionIn,
    MarketOrderOut,
    ProfileOut,
    ProfileUpdate,
    ReviewIn,
    ReviewOut,
    TrackingOut,
    TrackingRouteOut,
)
from app.marketplace.tracking import route_for_order, tracking

router = APIRouter(prefix="/api/v1", tags=["customer"])


@router.get("/restaurants")
async def browse_restaurants(
    session: SessionDep,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lng: Annotated[float | None, Query(ge=-180, le=180)] = None,
    q: str | None = None,
    cuisine: str | None = None,
    veg: bool | None = None,
    max_delivery_fee: float | None = None,
    min_rating: float | None = None,
    sort: str | None = None,
):
    from decimal import Decimal

    from sqlalchemy import select

    from app.domain.models import MenuItem
    from app.marketplace.serializers import browse_out
    from app.rescue import service as rescue_service
    from app.trust import service as trust_service

    rows = await restaurant_service.browse(
        session,
        lat=lat,
        lng=lng,
        q=q,
        cuisine=cuisine,
        veg=veg,
        max_delivery_fee=(
            Decimal(str(max_delivery_fee)) if max_delivery_fee is not None else None
        ),
        min_rating=min_rating,
    )
    scores = await trust_service.scores_for(session, [restaurant for restaurant, _ in rows])
    rescue_counts = await rescue_service.live_counts(session)
    dishes: dict = {}
    if q:
        matches = (
            await session.execute(
                select(MenuItem).where(
                    MenuItem.restaurant_id.in_([restaurant.id for restaurant, _ in rows]),
                    MenuItem.name.ilike(f"%{q}%"),
                    MenuItem.available.is_(True),
                )
            )
        ).scalars()
        for item in matches:
            dishes.setdefault(item.restaurant_id, []).append(
                {
                    "id": str(item.id),
                    "name": item.name,
                    "price": str(item.price),
                    "veg": item.veg,
                    "portion_grams": item.portion_grams,
                }
            )
    results = []
    for restaurant, distance in rows:
        out = browse_out(restaurant, distance)
        trust = scores.get(restaurant.id)
        if trust:
            out.trust_score = trust["score"]
            out.trust_grade = trust["grade"]
            out.trust_badges = trust["badges"]
            out.trust_warnings = trust["warnings"]
        out.rescue_live = rescue_counts.get(restaurant.id, 0)
        out.matching_dishes = dishes.get(restaurant.id, [])[:3]
        results.append(out)
    # Ranking is never paid: distance by default, or the customer's own choice.
    if sort == "trust":
        results.sort(key=lambda row: -(row.trust_score or 0))
    elif sort == "rating":
        results.sort(key=lambda row: -float(row.rating))
    return results


@router.get("/restaurants/{restaurant_id}")
async def restaurant_detail(restaurant_id: UUID, session: SessionDep):
    from app.marketplace.serializers import browse_out

    restaurant = await session.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise NotFoundError("restaurant not found")
    return browse_out(restaurant)


@router.get("/restaurants/{restaurant_id}/menu")
async def restaurant_menu(restaurant_id: UUID, session: SessionDep):
    restaurant = await session.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise NotFoundError("restaurant not found")
    return await restaurant_service.menu(session, restaurant)


@router.get("/me/profile", response_model=ProfileOut)
async def get_profile(user: CustomerUser, session: SessionDep) -> ProfileOut:
    customer_profile = await access.customer_for(session, user)
    return await customer.profile(session, user, customer_profile)


@router.patch("/me/profile", response_model=ProfileOut)
async def patch_profile(
    payload: ProfileUpdate, user: CustomerUser, session: SessionDep
) -> ProfileOut:
    customer_profile = await access.customer_for(session, user)
    return await customer.update_profile(session, user, customer_profile, payload)


@router.get("/me/addresses", response_model=list[AddressOut])
async def get_addresses(user: CustomerUser, session: SessionDep) -> list[AddressOut]:
    return await customer.list_addresses(session, user.id)


@router.post(
    "/me/addresses", response_model=AddressOut, status_code=status.HTTP_201_CREATED
)
async def add_address(
    payload: AddressIn, user: CustomerUser, session: SessionDep
) -> AddressOut:
    return await customer.add_address(session, user.id, payload)


@router.put("/me/addresses/{address_id}", response_model=AddressOut)
async def update_address(
    address_id: UUID, payload: AddressIn, user: CustomerUser, session: SessionDep
) -> AddressOut:
    return await customer.update_address(session, user.id, address_id, payload)


@router.delete("/me/addresses/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_address(
    address_id: UUID, user: CustomerUser, session: SessionDep
) -> None:
    await customer.delete_address(session, user.id, address_id)


@router.get("/cart", response_model=CartOut)
async def get_cart(user: CustomerUser, session: SessionDep) -> CartOut:
    return await cart.get_cart(session, user.id)


@router.post("/cart/items", response_model=CartOut)
async def add_cart_item(
    payload: CartItemIn, user: CustomerUser, session: SessionDep
) -> CartOut:
    return await cart.add_item(session, user.id, payload)


@router.patch("/cart/items/{line_id}", response_model=CartOut)
async def update_cart_item(
    line_id: UUID, payload: CartItemUpdate, user: CustomerUser, session: SessionDep
) -> CartOut:
    return await cart.update_item(session, user.id, line_id, payload)


@router.delete("/cart/items/{line_id}", response_model=CartOut)
async def delete_cart_item(
    line_id: UUID, user: CustomerUser, session: SessionDep
) -> CartOut:
    return await cart.remove_item(session, user.id, line_id)


@router.get("/coupons", response_model=list[CouponOut])
async def list_coupons() -> list[CouponOut]:
    from decimal import Decimal

    return [
        CouponOut(
            code=code,
            valid=True,
            description=value["description"],
            discount=Decimal(str(value.get("discount", "0.00"))),
        )
        for code, value in COUPONS.items()
    ]


@router.post("/cart/coupon", response_model=CartOut)
async def apply_coupon(
    payload: CouponIn, user: CustomerUser, session: SessionDep
) -> CartOut:
    return await cart.apply_coupon(session, user.id, payload.code)


@router.delete("/cart/coupon", response_model=CartOut)
async def clear_coupon(user: CustomerUser, session: SessionDep) -> CartOut:
    return await cart.apply_coupon(session, user.id, None)


@router.post(
    "/checkout",
    response_model=MarketOrderOut,
    status_code=status.HTTP_201_CREATED,
)
async def place_order(
    payload: CheckoutIn, user: CustomerUser, session: SessionDep
) -> MarketOrderOut:
    customer_profile = await access.customer_for(session, user)
    return await checkout.checkout(session, user, customer_profile, payload)


@router.get("/orders", response_model=list[MarketOrderOut])
async def my_orders(user: CustomerUser, session: SessionDep) -> list[MarketOrderOut]:
    return await customer.list_orders(session, user.id)


@router.get("/orders/{order_id}", response_model=MarketOrderOut)
async def my_order(
    order_id: UUID, user: CustomerUser, session: SessionDep
) -> MarketOrderOut:
    return await customer.order_detail(session, user, order_id)


@router.post("/orders/{order_id}/cancel", response_model=MarketOrderOut)
async def cancel_order(
    order_id: UUID,
    user: CustomerUser,
    session: SessionDep,
    payload: DeliveryActionIn | None = None,
) -> MarketOrderOut:
    return await customer.cancel_order(
        session, user, order_id, payload.reason if payload else None
    )


@router.post("/orders/{order_id}/reorder", response_model=CartOut)
async def reorder(
    order_id: UUID, user: CustomerUser, session: SessionDep
) -> CartOut:
    return await customer.reorder(session, user.id, order_id)


@router.post(
    "/orders/{order_id}/review",
    response_model=ReviewOut,
    status_code=status.HTTP_201_CREATED,
)
async def review_order(
    order_id: UUID, payload: ReviewIn, user: CustomerUser, session: SessionDep
) -> ReviewOut:
    return await customer.create_review(session, user, order_id, payload)


@router.get("/orders/{order_id}/tracking", response_model=TrackingOut)
async def track_order(
    order_id: UUID, user: OrderViewUser, session: SessionDep
) -> TrackingOut:
    return await tracking(session, user, order_id)


@router.get("/orders/{order_id}/route", response_model=TrackingRouteOut)
async def track_order_route(
    order_id: UUID, user: OrderViewUser, session: SessionDep
) -> TrackingRouteOut:
    return await route_for_order(session, user, order_id)
