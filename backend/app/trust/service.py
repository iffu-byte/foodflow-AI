"""Kitchen reality check, shared-kitchen detection and the trust profile."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import service as ai_service
from app.config import settings
from app.domain.exceptions import BadRequestError
from app.domain.geo import haversine_km
from app.domain.models import KitchenPhoto, MenuItem, Restaurant, Review
from app.media import decode_image, save_image
from app.trust import fssai, places
from app.trust.score import TrustInputs, compute

SHARED_KITCHEN_RADIUS_M = 30.0
KITCHEN_TYPES = {"dine_in", "cloud_kitchen", "shared_kitchen"}
QUANTITY_OK = ("as_described", "more")
QUANTITY_SHORT = ("less", "much_less")


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _pick_google_match(candidates: list[dict]) -> dict | None:
    if not candidates:
        return None

    def rank(row: dict) -> float:
        distance = row.get("distance_m") or 5000.0
        return row.get("name_similarity", 0.0) * 2.0 - min(distance, 5000.0) / 1000.0

    return max(candidates, key=rank)


def _google_verdict(match: dict | None) -> str:
    if match is None:
        return "not_found"
    if match.get("business_status") in {"CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"}:
        return "closed"
    distance = match.get("distance_m")
    if (
        distance is not None
        and distance <= places.MATCH_RADIUS_M
        and match.get("name_similarity", 0) >= 0.55
    ):
        return "verified"
    return "mismatch"


def _osm_verdict(osm: dict) -> str:
    food = osm.get("food_places_at_pin", [])
    named = [row for row in food if (row.get("name_similarity") or 0) >= 0.6]
    if any((row.get("distance_m") or 9e9) <= places.MATCH_RADIUS_M for row in named):
        return "osm_match"
    if named:
        return "mismatch"
    if any((row.get("distance_m") or 9e9) <= places.OSM_RADIUS_M for row in food):
        return "osm_food_nearby"
    return "osm_no_food"


async def reality_check(
    session: AsyncSession, restaurant: Restaurant, *, refresh: bool = False
) -> dict:
    """Return the cached map check, or run it when stale or asked to refresh.

    The result is stored on the restaurant, so a listing is looked up once a
    week rather than once per customer view.
    """
    checked = _aware(restaurant.place_checked_at)
    fresh = checked is not None and _now() - checked < timedelta(days=settings.places_cache_days)
    if restaurant.place_snapshot and fresh and not refresh:
        ai_service.record(
            session,
            provider=restaurant.place_snapshot.get("provider", "cache"),
            purpose="reality_check",
            cache_hit=True,
        )
        await session.commit()
        return restaurant.place_snapshot

    snapshot: dict = {"provider": "none", "verdict": "unchecked", "checked_at": _now().isoformat()}
    if ai_service.google_maps_enabled():
        if restaurant.google_place_id:
            match = await places.google_details(
                session,
                restaurant.google_place_id,
                restaurant.name,
                restaurant.lat,
                restaurant.lng,
            )
            candidates = [match] if match else []
        else:
            candidates = await places.google_search(
                session, restaurant.name, restaurant.lat, restaurant.lng
            )
            match = _pick_google_match(candidates)
        if candidates or match:
            signals = places.analyse_reviews(match["reviews"]) if match else {}
            snapshot = {
                "provider": "google",
                "verdict": _google_verdict(match),
                "checked_at": _now().isoformat(),
                "match": match,
                "signals": signals,
                "other_candidates": [
                    {
                        "name": row["name"],
                        "distance_m": row["distance_m"],
                        "name_similarity": row["name_similarity"],
                    }
                    for row in candidates
                    if match is None or row.get("place_id") != match.get("place_id")
                ][:3],
            }

    if snapshot["provider"] == "none" or snapshot["verdict"] in {"not_found", "mismatch"}:
        osm = await places.osm_check(restaurant.name, restaurant.lat, restaurant.lng)
        if osm is not None:
            ai_service.record(session, provider="openstreetmap", purpose="reality_check")
            if snapshot["provider"] == "none":
                snapshot = {
                    "provider": "osm",
                    "verdict": _osm_verdict(osm),
                    "checked_at": _now().isoformat(),
                    "osm": osm,
                }
            else:
                snapshot["osm"] = osm

    restaurant.place_snapshot = snapshot
    # An "unchecked" result means every provider was unreachable; retry next view.
    restaurant.place_checked_at = _now() if snapshot["verdict"] != "unchecked" else None
    await session.commit()
    return snapshot


async def sibling_brands(session: AsyncSession, restaurant: Restaurant) -> list[Restaurant]:
    """Other listings cooked in the same kitchen: same map place or within 30 m."""
    rows = (
        await session.execute(
            select(Restaurant).where(
                Restaurant.id != restaurant.id, Restaurant.is_active.is_(True)
            )
        )
    ).scalars()
    siblings = []
    for other in rows:
        same_place = (
            restaurant.google_place_id is not None
            and other.google_place_id == restaurant.google_place_id
        )
        close = (
            haversine_km(restaurant.lat, restaurant.lng, other.lat, other.lng) * 1000.0
            <= SHARED_KITCHEN_RADIUS_M
        )
        if same_place or close:
            siblings.append(other)
    return siblings


def sibling_map(restaurants: list[Restaurant]) -> dict[UUID, list[str]]:
    result: dict[UUID, list[str]] = {restaurant.id: [] for restaurant in restaurants}
    for index, left in enumerate(restaurants):
        for right in restaurants[index + 1 :]:
            same_place = left.google_place_id is not None and (
                left.google_place_id == right.google_place_id
            )
            close = (
                haversine_km(left.lat, left.lng, right.lat, right.lng) * 1000.0
                <= SHARED_KITCHEN_RADIUS_M
            )
            if same_place or close:
                result[left.id].append(right.name)
                result[right.id].append(left.name)
    return result


async def _portion_counts(
    session: AsyncSession, restaurant_ids: list[UUID]
) -> dict[UUID, tuple[int, int, int]]:
    rows = (
        await session.execute(
            select(
                MenuItem.restaurant_id,
                func.count(),
                func.sum(
                    case(
                        (
                            (MenuItem.portion_grams.is_not(None))
                            | (MenuItem.portion_serves.is_not(None)),
                            1,
                        ),
                        else_=0,
                    )
                ),
                func.sum(
                    case(
                        (MenuItem.portion_method.in_(("photo_reference", "scale", "container")), 1),
                        else_=0,
                    )
                ),
            )
            .where(MenuItem.restaurant_id.in_(restaurant_ids))
            .group_by(MenuItem.restaurant_id)
        )
    ).all()
    return {row[0]: (int(row[1]), int(row[2] or 0), int(row[3] or 0)) for row in rows}


async def _quantity_counts(
    session: AsyncSession, restaurant_ids: list[UUID]
) -> dict[UUID, tuple[int, int]]:
    rows = (
        await session.execute(
            select(
                Review.restaurant_id,
                func.sum(case((Review.quantity_feedback.in_(QUANTITY_OK), 1), else_=0)),
                func.sum(case((Review.quantity_feedback.in_(QUANTITY_SHORT), 1), else_=0)),
            )
            .where(Review.restaurant_id.in_(restaurant_ids))
            .group_by(Review.restaurant_id)
        )
    ).all()
    return {row[0]: (int(row[1] or 0), int(row[2] or 0)) for row in rows}


async def _latest_photo(
    session: AsyncSession, restaurant_ids: list[UUID]
) -> dict[UUID, datetime]:
    rows = (
        await session.execute(
            select(KitchenPhoto.restaurant_id, func.max(KitchenPhoto.taken_at))
            .where(KitchenPhoto.restaurant_id.in_(restaurant_ids))
            .group_by(KitchenPhoto.restaurant_id)
        )
    ).all()
    return {row[0]: _aware(row[1]) for row in rows}


def _inputs(
    restaurant: Restaurant,
    portions: tuple[int, int, int],
    quantity: tuple[int, int],
    latest_photo: datetime | None,
    siblings: list[str],
) -> TrustInputs:
    licence = fssai.check(restaurant.fssai_license, restaurant.fssai_valid_until)
    verdict = (restaurant.place_snapshot or {}).get("verdict", "unchecked")
    age = (_now() - latest_photo).total_seconds() / 86400.0 if latest_photo else None
    return TrustInputs(
        fssai_status=licence["status"],
        location_verdict=verdict,
        kitchen_photo_age_days=age,
        menu_items=portions[0],
        items_with_portion=portions[1],
        items_portion_verified=portions[2],
        quantity_ok=quantity[0],
        quantity_short=quantity[1],
        sibling_brands=siblings,
        kitchen_type=restaurant.kitchen_type,
    )


async def scores_for(
    session: AsyncSession, restaurants: list[Restaurant]
) -> dict[UUID, dict]:
    """Batch trust scores for a browse list using cached data only."""
    if not restaurants:
        return {}
    ids = [restaurant.id for restaurant in restaurants]
    portions = await _portion_counts(session, ids)
    quantity = await _quantity_counts(session, ids)
    photos = await _latest_photo(session, ids)
    everyone = list(
        (await session.execute(select(Restaurant).where(Restaurant.is_active.is_(True))))
        .scalars()
        .all()
    )
    siblings = sibling_map(everyone)
    result = {}
    for restaurant in restaurants:
        result[restaurant.id] = compute(
            _inputs(
                restaurant,
                portions.get(restaurant.id, (0, 0, 0)),
                quantity.get(restaurant.id, (0, 0)),
                photos.get(restaurant.id),
                siblings.get(restaurant.id, []),
            )
        )
    return result


def _public_snapshot(restaurant: Restaurant, snapshot: dict) -> dict:
    """Swap Google photo resource names for our proxy URLs (no key leaves the API)."""
    public = dict(snapshot)
    match = dict(public.get("match") or {})
    if match:
        match["photos"] = [
            {
                "url": f"/api/v1/restaurants/{restaurant.id}/trust/photo/{index}",
                "attribution": photo.get("attribution", ""),
            }
            for index, photo in enumerate(match.get("photos", []))
        ]
        public["match"] = match
    return public


async def trust_profile(
    session: AsyncSession, restaurant: Restaurant, *, refresh: bool = False
) -> dict:
    snapshot = await reality_check(session, restaurant, refresh=refresh)
    siblings = await sibling_brands(session, restaurant)
    portions = (await _portion_counts(session, [restaurant.id])).get(restaurant.id, (0, 0, 0))
    quantity = (await _quantity_counts(session, [restaurant.id])).get(restaurant.id, (0, 0))
    photos = list(
        (
            await session.execute(
                select(KitchenPhoto)
                .where(KitchenPhoto.restaurant_id == restaurant.id)
                .order_by(KitchenPhoto.taken_at.desc())
                .limit(6)
            )
        )
        .scalars()
        .all()
    )
    latest = _aware(photos[0].taken_at) if photos else None
    score = compute(
        _inputs(restaurant, portions, quantity, latest, [other.name for other in siblings])
    )
    await session.commit()
    return {
        "restaurant_id": restaurant.id,
        "restaurant_name": restaurant.name,
        "lat": restaurant.lat,
        "lng": restaurant.lng,
        "address": restaurant.address,
        "kitchen_type": restaurant.kitchen_type,
        "price_parity": restaurant.price_parity,
        "fssai": fssai.check(restaurant.fssai_license, restaurant.fssai_valid_until),
        "reality": _public_snapshot(restaurant, snapshot),
        "shared_kitchen": [
            {"id": other.id, "name": other.name, "kitchen_type": other.kitchen_type}
            for other in siblings
        ],
        "kitchen_photos": [
            {"id": photo.id, "url": photo.url, "caption": photo.caption, "taken_at": photo.taken_at}
            for photo in photos
        ],
        "quantity_feedback": {"as_described": quantity[0], "short": quantity[1]},
        "portion_coverage": {
            "menu_items": portions[0],
            "declared": portions[1],
            "verified": portions[2],
        },
        "providers": {
            "google_maps": ai_service.google_maps_enabled(),
            "openstreetmap": settings.osm_enabled,
        },
        **score,
    }


async def photo_redirect(session: AsyncSession, restaurant: Restaurant, index: int) -> str | None:
    match = (restaurant.place_snapshot or {}).get("match") or {}
    photos = match.get("photos") or []
    if index < 0 or index >= len(photos):
        return None
    uri = await places.google_photo_uri(session, photos[index]["name"])
    await session.commit()
    return uri


async def update_profile(
    session: AsyncSession,
    restaurant: Restaurant,
    *,
    fssai_license: str | None,
    fssai_valid_until: date | None,
    kitchen_type: str | None,
    price_parity: bool | None,
) -> None:
    if fssai_license is not None:
        restaurant.fssai_license = fssai_license.strip() or None
    if fssai_valid_until is not None:
        restaurant.fssai_valid_until = fssai_valid_until
    if kitchen_type is not None:
        if kitchen_type not in KITCHEN_TYPES:
            raise BadRequestError("kitchen_type must be dine_in, cloud_kitchen or shared_kitchen")
        restaurant.kitchen_type = kitchen_type
    if price_parity is not None:
        restaurant.price_parity = price_parity
    await session.commit()


async def search_listings(
    session: AsyncSession, restaurant: Restaurant, query: str | None
) -> dict:
    if ai_service.google_maps_enabled():
        rows = await places.google_search(
            session, restaurant.name, restaurant.lat, restaurant.lng, query=query
        )
        await session.commit()
        return {
            "provider": "google",
            "candidates": [
                {
                    "place_id": row["place_id"],
                    "name": row["name"],
                    "address": row["address"],
                    "distance_m": row["distance_m"],
                    "rating": row["rating"],
                    "rating_count": row["rating_count"],
                }
                for row in rows
            ],
        }
    osm = await places.osm_check(query or restaurant.name, restaurant.lat, restaurant.lng)
    return {
        "provider": "osm",
        "candidates": [
            {
                "place_id": None,
                "name": row["name"],
                "address": None,
                "distance_m": row["distance_m"],
                "rating": None,
                "rating_count": None,
            }
            for row in (osm or {}).get("food_places_at_pin", [])
        ],
    }


async def link_place(session: AsyncSession, restaurant: Restaurant, place_id: str) -> dict:
    if not place_id.strip():
        raise BadRequestError("place_id is required")
    restaurant.google_place_id = place_id.strip()
    await session.commit()
    return await trust_profile(session, restaurant, refresh=True)


async def add_kitchen_photo(
    session: AsyncSession, restaurant: Restaurant, image: str, caption: str
) -> KitchenPhoto:
    raw, mime = decode_image(image)
    url = save_image("kitchen", restaurant.id, raw, mime)
    photo = KitchenPhoto(restaurant_id=restaurant.id, url=url, caption=caption[:160])
    session.add(photo)
    await session.commit()
    await session.refresh(photo)
    return photo
