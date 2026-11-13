"""HTTP surface for the trust layer.

Customer: kitchen reality check, live rescue deals, today's nutrition, honest
order status and "not received" disputes. Restaurant: trust profile, map
listing, kitchen photos, Portion Studio and rescue forecasting. Admin: the AI
cost meter.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.ai import service as ai_service
from app.api.deps import SessionDep
from app.auth.deps import AdminUser, CustomerUser, OrderViewUser, RestaurantUser
from app.domain import service as domain_service
from app.domain.exceptions import BadRequestError, NotFoundError
from app.domain.models import OrderEvent, OrderStatus, Restaurant
from app.honesty import service as honesty_service
from app.marketplace import access, notifications
from app.marketplace.restaurant import menu_item_out
from app.marketplace.schemas import RestaurantMenuItemOut
from app.nutrition import service as nutrition_service
from app.portion import estimator
from app.portion import service as portion_service
from app.realtime import service as realtime_service
from app.rescue import service as rescue_service
from app.trust import service as trust_service

router = APIRouter(prefix="/api/v1", tags=["trust-layer"])


class TrustPatch(BaseModel):
    fssai_license: str | None = Field(default=None, max_length=20)
    fssai_valid_until: date | None = None
    kitchen_type: Literal["dine_in", "cloud_kitchen", "shared_kitchen"] | None = None
    price_parity: bool | None = None


class PlaceLinkIn(BaseModel):
    place_id: str = Field(min_length=3, max_length=160)


class PhotoIn(BaseModel):
    image: str = Field(min_length=32, max_length=6_000_000)
    caption: str = Field(default="", max_length=160)


class PortionEstimateIn(BaseModel):
    method: Literal["photo_reference", "container", "scale", "pieces"]
    profile: str | None = None
    reference: str | None = None
    custom_reference_cm: float | None = Field(default=None, gt=0, le=60)
    reference_px: float | None = Field(default=None, ge=0)
    food_rx_px: float | None = Field(default=None, ge=0)
    food_ry_px: float | None = Field(default=None, ge=0)
    depth_cm: float | None = Field(default=None, gt=0, le=20)
    capacity_ml: float | None = Field(default=None, gt=0, le=5000)
    fill_fraction: float | None = Field(default=None, gt=0, le=1)
    grams: float | None = Field(default=None, gt=0, le=10000)
    pieces: int | None = Field(default=None, ge=1, le=100)
    piece_grams: float | None = Field(default=None, gt=0, le=1000)
    image: str | None = Field(default=None, max_length=6_000_000)


class PortionPublishIn(BaseModel):
    method: Literal["declared", "photo_reference", "container", "scale", "pieces"] = "declared"
    grams: int | None = Field(default=None, ge=10, le=5000)
    serves: int | None = Field(default=None, ge=1, le=12)
    pieces: int | None = Field(default=None, ge=1, le=100)
    confidence: float | None = Field(default=None, ge=0, le=1)
    image: str | None = Field(default=None, max_length=6_000_000)


class PrepIn(BaseModel):
    menu_item_id: UUID
    prepared_qty: int = Field(ge=0, le=2000)


class RescueIn(BaseModel):
    menu_item_id: UUID
    qty: int = Field(ge=1, le=200)
    start_price: Decimal = Field(gt=0)
    floor_price: Decimal = Field(gt=0)
    duration_min: int = Field(ge=15, le=360)


class DisputeIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)


# --- Customer and public -----------------------------------------------------


@router.get("/restaurants/{restaurant_id}/trust")
async def restaurant_trust(
    restaurant_id: UUID, session: SessionDep, refresh: bool = False
) -> dict:
    restaurant = await session.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise NotFoundError("restaurant not found")
    return await trust_service.trust_profile(session, restaurant, refresh=refresh)


@router.get("/restaurants/{restaurant_id}/trust/photo/{index}")
async def restaurant_trust_photo(restaurant_id: UUID, index: int, session: SessionDep):
    restaurant = await session.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise NotFoundError("restaurant not found")
    uri = await trust_service.photo_redirect(session, restaurant, index)
    if uri is None:
        raise NotFoundError("photo not available")
    return RedirectResponse(uri, status_code=307)


@router.get("/rescue/live")
async def rescue_live(
    session: SessionDep,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lng: Annotated[float | None, Query(ge=-180, le=180)] = None,
) -> list[dict]:
    return await rescue_service.live_near(session, lat, lng)


@router.get("/me/nutrition/today")
async def nutrition_today(user: CustomerUser, session: SessionDep) -> dict:
    return await nutrition_service.today_intake(session, user.id)


@router.get("/orders/{order_id}/honest-status")
async def honest_status(order_id: UUID, user: OrderViewUser, session: SessionDep) -> dict:
    return await honesty_service.honest_status(session, user, order_id)


@router.post("/orders/{order_id}/not-received")
async def not_received(
    order_id: UUID, user: CustomerUser, session: SessionDep, payload: DisputeIn | None = None
) -> dict:
    """Customer says a 'delivered' order never arrived; answer with the stored proof."""
    order = await domain_service.get_order(session, order_id)
    if order.customer_id != user.id:
        raise NotFoundError("order not found")
    if order.status is not OrderStatus.DELIVERED:
        raise BadRequestError("only delivered orders can be reported as not received")
    proof = order.delivery_proof or {}
    event = OrderEvent(
        order_id=order.id,
        type="delivery_disputed",
        payload={"note": payload.note if payload else None, "proof": proof},
    )
    session.add(event)
    if proof.get("method") == "otp_geofence":
        verdict = "proof_on_file"
        message = (
            f"Your delivery code was entered {proof['distance_m']:.0f} m from your pin at "
            f"{proof['verified_at'][11:16]} UTC. Support will review this with the rider's "
            "GPS trail before deciding."
        )
    else:
        verdict = "no_proof"
        message = (
            "This order has no delivery-code proof on file, so it is refunded in full "
            "automatically."
        )
        order.compensation = order.total_price
    rows = await notifications.notify_admins(
        session,
        "DELIVERY_DISPUTED",
        "Customer reports order not received",
        f"{order.order_number or order.id}: {verdict.replace('_', ' ')}.",
        order.id,
    )
    await session.commit()
    order = await domain_service.get_order(session, order.id)
    await realtime_service.publish_order_event(order, event)
    await notifications.publish(rows)
    return {"verdict": verdict, "message": message, "proof": proof or None}


# --- Restaurant: trust profile ---------------------------------------------


@router.get("/restaurant/trust")
async def my_trust(user: RestaurantUser, session: SessionDep, refresh: bool = False) -> dict:
    restaurant = await access.restaurant_for(session, user)
    return await trust_service.trust_profile(session, restaurant, refresh=refresh)


@router.patch("/restaurant/trust")
async def patch_trust(payload: TrustPatch, user: RestaurantUser, session: SessionDep) -> dict:
    restaurant = await access.restaurant_for(session, user)
    await trust_service.update_profile(
        session,
        restaurant,
        fssai_license=payload.fssai_license,
        fssai_valid_until=payload.fssai_valid_until,
        kitchen_type=payload.kitchen_type,
        price_parity=payload.price_parity,
    )
    return await trust_service.trust_profile(session, restaurant)


@router.get("/restaurant/places/search")
async def search_places(
    user: RestaurantUser, session: SessionDep, q: str | None = None
) -> dict:
    restaurant = await access.restaurant_for(session, user)
    return await trust_service.search_listings(session, restaurant, q)


@router.post("/restaurant/places/link")
async def link_place(payload: PlaceLinkIn, user: RestaurantUser, session: SessionDep) -> dict:
    restaurant = await access.restaurant_for(session, user)
    return await trust_service.link_place(session, restaurant, payload.place_id)


@router.post("/restaurant/kitchen-photos", status_code=201)
async def kitchen_photo(payload: PhotoIn, user: RestaurantUser, session: SessionDep) -> dict:
    restaurant = await access.restaurant_for(session, user)
    photo = await trust_service.add_kitchen_photo(
        session, restaurant, payload.image, payload.caption
    )
    return {"id": photo.id, "url": photo.url, "caption": photo.caption, "taken_at": photo.taken_at}


# --- Restaurant: Portion Studio ---------------------------------------------


@router.get("/restaurant/portion/config")
async def portion_config(user: RestaurantUser) -> dict:
    return {
        "references": [
            {"key": key, "cm": cm, "label": portion_service.REFERENCE_TEXT[key]}
            for key, cm in estimator.REFERENCES_CM.items()
        ],
        "profiles": [
            {"key": key, **value} for key, value in estimator.DISH_PROFILES.items()
        ],
        "ai_available": ai_service.gemini_enabled(),
    }


@router.post("/restaurant/menu/{item_id}/portion/estimate")
async def portion_estimate(
    item_id: UUID, payload: PortionEstimateIn, user: RestaurantUser, session: SessionDep
) -> dict:
    restaurant = await access.restaurant_for(session, user)
    return await portion_service.estimate(session, restaurant, item_id, payload)


@router.post("/restaurant/menu/{item_id}/portion", response_model=RestaurantMenuItemOut)
async def portion_publish(
    item_id: UUID, payload: PortionPublishIn, user: RestaurantUser, session: SessionDep
) -> RestaurantMenuItemOut:
    restaurant = await access.restaurant_for(session, user)
    item = await portion_service.publish(session, restaurant, item_id, payload)
    return menu_item_out(item)


# --- Restaurant: Rescue a Meal ---------------------------------------------


@router.get("/restaurant/rescue/forecast")
async def rescue_forecast(user: RestaurantUser, session: SessionDep) -> dict:
    restaurant = await access.restaurant_for(session, user)
    return await rescue_service.forecast(session, restaurant)


@router.post("/restaurant/rescue/prep")
async def rescue_prep(payload: PrepIn, user: RestaurantUser, session: SessionDep) -> dict:
    restaurant = await access.restaurant_for(session, user)
    await rescue_service.log_prep(session, restaurant, payload.menu_item_id, payload.prepared_qty)
    return await rescue_service.forecast(session, restaurant)


@router.post("/restaurant/rescue/listings", status_code=201)
async def rescue_create(payload: RescueIn, user: RestaurantUser, session: SessionDep) -> dict:
    restaurant = await access.restaurant_for(session, user)
    return await rescue_service.create_listing(
        session,
        restaurant,
        menu_item_id=payload.menu_item_id,
        qty=payload.qty,
        start_price=payload.start_price,
        floor_price=payload.floor_price,
        duration_min=payload.duration_min,
    )


@router.post("/restaurant/rescue/listings/{listing_id}/end")
async def rescue_end(listing_id: UUID, user: RestaurantUser, session: SessionDep) -> dict:
    restaurant = await access.restaurant_for(session, user)
    await rescue_service.end_listing(session, restaurant, listing_id)
    return await rescue_service.forecast(session, restaurant)


# --- Admin: AI cost meter ----------------------------------------------------


@router.get("/ai/usage")
async def ai_usage(user: AdminUser, session: SessionDep) -> dict:
    return await ai_service.usage_summary(session)
