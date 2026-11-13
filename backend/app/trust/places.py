"""Find out what is physically at a restaurant's pin.

Google Places (New) is used when ``GOOGLE_MAPS_API_KEY`` is set: it returns the
listing, real photos, opening hours and recent reviews. Without a key the
check falls back to OpenStreetMap (Overpass + Nominatim), which reports which
food businesses and buildings are mapped at the pin. Both providers sit behind
the same result shape, and every paid call goes through the AI usage meter.
"""

import asyncio
import logging
import re
import time
from difflib import SequenceMatcher

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import service as ai_service
from app.config import settings
from app.domain.geo import haversine_km

logger = logging.getLogger(__name__)

PLACES_BASE = "https://places.googleapis.com/v1"
PLACE_FIELDS = (
    "id,displayName,formattedAddress,location,rating,userRatingCount,businessStatus,"
    "types,photos,googleMapsUri,reviews,regularOpeningHours"
)
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
MATCH_RADIUS_M = 150.0
OSM_RADIUS_M = 80

QUANTITY_WORDS = re.compile(
    r"\b(quantity|portion|one piece|1 piece|single piece|less (rice|chicken|food)|"
    r"very less|small(er)? (box|portion|quantity)|not sufficient|insufficient|"
    r"half (filled|empty))\b",
    re.IGNORECASE,
)
CLOUD_KITCHEN_WORDS = re.compile(
    r"\b(cloud kitchen|delivery only|only delivery|no (dine|seating|sitting)|"
    r"takeaway only|no place to sit)\b",
    re.IGNORECASE,
)
HYGIENE_WORDS = re.compile(
    r"\b(hygien\w*|dirty|cockroach|insect|hair in|stale|food poisoning|unclean)\b",
    re.IGNORECASE,
)

# Resolved photo URLs are short-lived; keep them briefly to avoid paying per view.
_photo_cache: dict[str, tuple[str, float]] = {}
PHOTO_CACHE_TTL_S = 3600.0


def _normalize(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^a-z0-9 ]+", " ", name)
    stop = {"the", "restaurant", "kitchen", "hotel", "cafe", "and", "&", "family", "dhaba"}
    return " ".join(token for token in name.split() if token not in stop)


def name_similarity(a: str, b: str) -> float:
    left, right = _normalize(a), _normalize(b)
    if not left or not right:
        return 0.0
    ratio = SequenceMatcher(None, left, right).ratio()
    tokens_a, tokens_b = set(left.split()), set(right.split())
    overlap = len(tokens_a & tokens_b) / max(1, min(len(tokens_a), len(tokens_b)))
    return round(max(ratio, overlap), 2)


def _distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    return round(haversine_km(lat1, lng1, lat2, lng2) * 1000.0, 1)


def analyse_reviews(reviews: list[dict]) -> dict:
    """Pull quantity, hygiene and cloud-kitchen signals out of review text."""
    quantity = [r for r in reviews if QUANTITY_WORDS.search(r.get("text", ""))]
    cloud = [r for r in reviews if CLOUD_KITCHEN_WORDS.search(r.get("text", ""))]
    hygiene = [r for r in reviews if HYGIENE_WORDS.search(r.get("text", ""))]
    for review in reviews:
        text = review.get("text", "")
        review["flags"] = [
            flag
            for flag, pattern in (
                ("quantity", QUANTITY_WORDS),
                ("cloud_kitchen", CLOUD_KITCHEN_WORDS),
                ("hygiene", HYGIENE_WORDS),
            )
            if pattern.search(text)
        ]
    return {
        "quantity_mentions": len(quantity),
        "cloud_kitchen_mentions": len(cloud),
        "hygiene_mentions": len(hygiene),
        "reviews_read": len(reviews),
    }


def _google_place_out(place: dict, lat: float, lng: float, name: str) -> dict:
    location = place.get("location") or {}
    plat, plng = location.get("latitude"), location.get("longitude")
    display = (place.get("displayName") or {}).get("text", "")
    reviews = [
        {
            "rating": review.get("rating"),
            "text": ((review.get("text") or {}).get("text") or "")[:600],
            "author": (review.get("authorAttribution") or {}).get("displayName"),
            "relative_time": review.get("relativePublishTimeDescription"),
        }
        for review in (place.get("reviews") or [])[:5]
    ]
    return {
        "place_id": place.get("id"),
        "name": display,
        "address": place.get("formattedAddress"),
        "lat": plat,
        "lng": plng,
        "distance_m": _distance_m(lat, lng, plat, plng) if plat is not None else None,
        "name_similarity": name_similarity(name, display),
        "rating": place.get("rating"),
        "rating_count": place.get("userRatingCount"),
        "business_status": place.get("businessStatus"),
        "types": place.get("types", [])[:6],
        "maps_url": place.get("googleMapsUri"),
        "opening_hours": (place.get("regularOpeningHours") or {}).get(
            "weekdayDescriptions", []
        ),
        "photos": [
            {
                "name": photo.get("name"),
                "attribution": ", ".join(
                    author.get("displayName", "")
                    for author in photo.get("authorAttributions", [])
                ),
            }
            for photo in (place.get("photos") or [])[:6]
        ],
        "reviews": reviews,
    }


async def google_search(
    session: AsyncSession, name: str, lat: float, lng: float, *, query: str | None = None
) -> list[dict]:
    if not ai_service.google_maps_enabled():
        return []
    cost = ai_service.PLACES_COST_USD["places_text_search"]
    if not await ai_service.within_budget(session, cost):
        ai_service.record(
            session, provider="google_places", purpose="text_search", ok=False,
            detail="daily budget spent",
        )
        return []
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(
                f"{PLACES_BASE}/places:searchText",
                headers={
                    "X-Goog-Api-Key": settings.google_maps_api_key,
                    "X-Goog-FieldMask": ",".join(
                        f"places.{field}" for field in PLACE_FIELDS.split(",")
                    ),
                },
                json={
                    "textQuery": query or name,
                    "locationBias": {
                        "circle": {
                            "center": {"latitude": lat, "longitude": lng},
                            "radius": 1500.0,
                        }
                    },
                    "maxResultCount": 5,
                },
            )
        response.raise_for_status()
        places = response.json().get("places", [])
        ai_service.record(
            session, provider="google_places", purpose="text_search", cost_usd=cost,
            detail=f"{len(places)} results",
        )
        return [_google_place_out(place, lat, lng, name) for place in places]
    except Exception as exc:  # noqa: BLE001
        logger.warning("google text search failed: %s", exc)
        ai_service.record(
            session, provider="google_places", purpose="text_search", ok=False,
            detail=str(exc)[:200],
        )
        return []


async def google_details(
    session: AsyncSession, place_id: str, name: str, lat: float, lng: float
) -> dict | None:
    if not ai_service.google_maps_enabled():
        return None
    cost = ai_service.PLACES_COST_USD["places_details"]
    if not await ai_service.within_budget(session, cost):
        return None
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(
                f"{PLACES_BASE}/places/{place_id}",
                headers={
                    "X-Goog-Api-Key": settings.google_maps_api_key,
                    "X-Goog-FieldMask": PLACE_FIELDS,
                },
            )
        response.raise_for_status()
        ai_service.record(
            session, provider="google_places", purpose="place_details", cost_usd=cost
        )
        return _google_place_out(response.json(), lat, lng, name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("google place details failed: %s", exc)
        ai_service.record(
            session, provider="google_places", purpose="place_details", ok=False,
            detail=str(exc)[:200],
        )
        return None


async def google_photo_uri(session: AsyncSession, photo_name: str) -> str | None:
    cached = _photo_cache.get(photo_name)
    if cached and time.monotonic() - cached[1] < PHOTO_CACHE_TTL_S:
        ai_service.record(session, provider="google_places", purpose="photo", cache_hit=True)
        return cached[0]
    if not ai_service.google_maps_enabled() or not photo_name.startswith("places/"):
        return None
    cost = ai_service.PLACES_COST_USD["places_photo"]
    if not await ai_service.within_budget(session, cost):
        return None
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(
                f"{PLACES_BASE}/{photo_name}/media",
                params={"maxWidthPx": 800, "skipHttpRedirect": "true"},
                headers={"X-Goog-Api-Key": settings.google_maps_api_key},
            )
        response.raise_for_status()
        uri = response.json().get("photoUri")
        ai_service.record(session, provider="google_places", purpose="photo", cost_usd=cost)
        if uri:
            _photo_cache[photo_name] = (uri, time.monotonic())
        return uri
    except Exception as exc:  # noqa: BLE001
        logger.warning("google photo failed: %s", exc)
        ai_service.record(
            session, provider="google_places", purpose="photo", ok=False, detail=str(exc)[:200]
        )
        return None


FOOD_AMENITIES = {"restaurant", "fast_food", "cafe", "food_court", "ice_cream", "bar", "pub"}
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_GAP_S = 1.1  # Nominatim's usage policy allows about one request per second.


def _food_row(name: str, label: str, kind: str | None, lat: float, lng: float,
              elat, elng, source: str) -> dict:
    return {
        "name": label,
        "amenity": kind,
        "distance_m": (
            _distance_m(lat, lng, float(elat), float(elng)) if elat is not None else None
        ),
        "name_similarity": name_similarity(name, label),
        "source": source,
    }


async def osm_check(name: str, lat: float, lng: float) -> dict | None:
    """Ask OpenStreetMap which food businesses sit at the pin.

    Nominatim answers "what is at this point" (reverse) and "is a place with
    this name nearby" (bounded search). Overpass adds every mapped food
    business within 80 m when its public servers have capacity; it is tried
    once with a short timeout because those servers are often overloaded.
    """
    if not settings.osm_enabled:
        return None
    headers = {"User-Agent": settings.osm_user_agent}
    food: list[dict] = []
    address = None
    at_pin = None
    reached = False
    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        try:
            reverse = await client.get(
                NOMINATIM_URL,
                params={"format": "jsonv2", "lat": lat, "lon": lng, "zoom": 18},
            )
            if reverse.status_code == 200:
                reached = True
                data = reverse.json()
                address = data.get("display_name")
                at_pin = {
                    "category": data.get("category"),
                    "type": data.get("type"),
                    "name": data.get("name") or None,
                    "distance_m": (
                        _distance_m(lat, lng, float(data["lat"]), float(data["lon"]))
                        if data.get("lat") and data.get("lon")
                        else None
                    ),
                }
                if data.get("category") == "amenity" and data.get("type") in FOOD_AMENITIES:
                    food.append(
                        _food_row(name, data.get("name") or "Unnamed food place",
                                  data.get("type"), lat, lng, data.get("lat"), data.get("lon"),
                                  "nominatim_reverse")
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("nominatim reverse failed: %s", exc)

        for query, span in ((name, 0.0045), ("restaurant", 0.0012)):
            await asyncio.sleep(NOMINATIM_GAP_S)
            try:
                search = await client.get(
                    NOMINATIM_SEARCH_URL,
                    params={
                        "format": "jsonv2",
                        "q": query,
                        "viewbox": f"{lng - span},{lat + span},{lng + span},{lat - span}",
                        "bounded": 1,
                        "limit": 8,
                    },
                )
                if search.status_code != 200:
                    continue
                reached = True
                for row in search.json():
                    if row.get("category") == "amenity" and row.get("type") in FOOD_AMENITIES:
                        food.append(
                            _food_row(name, row.get("name") or "Unnamed food place",
                                      row.get("type"), lat, lng, row.get("lat"), row.get("lon"),
                                      "nominatim_search")
                        )
            except Exception as exc:  # noqa: BLE001
                logger.warning("nominatim search failed: %s", exc)

        query = (
            f"[out:json][timeout:5];"
            f'nwr(around:{OSM_RADIUS_M},{lat},{lng})["amenity"~"^(restaurant|fast_food|cafe|'
            f'food_court|ice_cream)$"];out center tags 15;'
        )
        try:
            overpass = await client.post(OVERPASS_URL, data={"data": query}, timeout=6.0)
            if overpass.status_code == 200:
                reached = True
                for element in overpass.json().get("elements", []):
                    tags = element.get("tags", {})
                    elat = element.get("lat") or (element.get("center") or {}).get("lat")
                    elng = element.get("lon") or (element.get("center") or {}).get("lon")
                    food.append(
                        _food_row(name, tags.get("name") or "Unnamed food place",
                                  tags.get("amenity"), lat, lng, elat, elng, "overpass")
                    )
        except Exception as exc:  # noqa: BLE001
            logger.info("overpass unavailable: %s", exc)

    if not reached:
        return None
    unique: dict[tuple, dict] = {}
    for row in food:
        key = (row["name"].lower(), round(row["distance_m"] or 0, -1))
        unique.setdefault(key, row)
    rows = sorted(
        unique.values(),
        key=lambda row: (-(row["name_similarity"] or 0), row["distance_m"] or 9e9),
    )
    near = [row for row in rows if (row["distance_m"] or 9e9) <= OSM_RADIUS_M * 2
            or (row["name_similarity"] or 0) >= 0.6]
    return {
        "food_places_at_pin": near[:8],
        "object_at_pin": at_pin,
        "address": address,
    }
