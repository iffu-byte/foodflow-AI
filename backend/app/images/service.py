"""Real dish photos with credits.

Dish and restaurant-cover photos come from Wikimedia Commons: real photographs
under free licences (CC0, CC BY, CC BY-SA, public domain) that need no API key,
only a visible credit. The credit (author, licence, source page) is stored next
to every image URL and shown in the app. A restaurant can replace any stock
photo with its own photo of the dish, which then takes priority.

Photos of the restaurant's actual location come from Google Places (see
``app.trust.places``) and need ``GOOGLE_MAPS_API_KEY``.
"""

import asyncio
import hashlib
import logging
import re
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import service as ai_service
from app.domain.exceptions import NotFoundError
from app.domain.models import MenuItem, Restaurant
from app.media import decode_image, save_image
from app.nutrition.service import match_dish

logger = logging.getLogger(__name__)

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "food-demo-app/0.1 (local development; image lookup)"
FREE_LICENCE = re.compile(r"^(cc0|cc by|public domain|pd)", re.IGNORECASE)
BAD_TITLE = re.compile(
    r"\b(logo|map|menu|sign|signboard|board|diagram|icon|poster|label|packet|box|card|stamp)\b",
    re.IGNORECASE,
)
REQUEST_GAP_S = 1.0
MAX_RETRIES = 4


def _strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", value or "")).strip()


def _tokens(value: str) -> set[str]:
    stop = {"the", "and", "with", "of", "a", "veg", "special", "classic", "fresh"}
    return {t for t in re.findall(r"[a-z]+", value.lower()) if len(t) > 2 and t not in stop}


async def _get_with_backoff(client: httpx.AsyncClient, params: dict) -> httpx.Response:
    """Wikimedia rate-limits anonymous clients; honour Retry-After and try again."""
    for attempt in range(MAX_RETRIES + 1):
        response = await client.get(COMMONS_API, params=params)
        if response.status_code != 429 or attempt == MAX_RETRIES:
            return response
        wait = float(response.headers.get("Retry-After") or 0) or 5.0 * (attempt + 1)
        logger.info("commons rate limit; waiting %.0f s", wait)
        await asyncio.sleep(min(wait, 60.0))
    return response


async def commons_candidates(client: httpx.AsyncClient, query: str, limit: int = 12) -> list[dict]:
    response = await _get_with_backoff(
        client,
        {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrnamespace": 6,
            "gsrlimit": limit,
            "gsrsearch": f"{query} filetype:bitmap",
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
            "iiurlwidth": 640,
            "iiextmetadatafilter": "LicenseShortName|Artist|LicenseUrl",
        },
    )
    response.raise_for_status()
    pages = response.json().get("query", {}).get("pages", {})
    rows = []
    for page in sorted(pages.values(), key=lambda row: row.get("index", 0)):
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        licence = _strip_html(meta.get("LicenseShortName", {}).get("value", ""))
        title = page.get("title", "")
        if info.get("mime") not in {"image/jpeg", "image/png"}:
            continue
        if not FREE_LICENCE.match(licence) or BAD_TITLE.search(title):
            continue
        width, height = info.get("width", 0), info.get("height", 1)
        if width < 500 or not 0.55 <= width / max(height, 1) <= 2.0:
            continue
        rows.append(
            {
                "url": info.get("thumburl") or info.get("url"),
                "page_url": info.get("descriptionurl"),
                "title": title.removeprefix("File:"),
                "author": _strip_html(meta.get("Artist", {}).get("value", ""))[:120]
                or "Unknown author",
                "licence": licence,
                "licence_url": _strip_html(meta.get("LicenseUrl", {}).get("value", "")) or None,
                "source": "Wikimedia Commons",
                "landscape": width >= height,
            }
        )
    return rows


def rank(candidates: list[dict], wanted: str) -> list[dict]:
    tokens = _tokens(wanted)

    def score(row: dict) -> float:
        overlap = len(tokens & _tokens(row["title"])) / max(1, len(tokens))
        return overlap * 3 + (0.5 if row["landscape"] else 0)

    return sorted(candidates, key=score, reverse=True)


def _pick(rows: list[dict], key: str) -> dict | None:
    """Vary the photo between restaurants that sell the same dish."""
    if not rows:
        return None
    top = rows[: min(3, len(rows))]
    index = int(hashlib.sha1(key.encode()).hexdigest(), 16) % len(top)
    return top[index]


async def _dish_rows(
    client: httpx.AsyncClient, item: MenuItem, cache: dict[str, list[dict]]
) -> list[dict]:
    dish, _ = match_dish(item.name)
    queries = [item.name]
    if dish is not None:
        queries.append(max(dish.keys, key=len))
    queries.append(f"{item.name} food")
    for query in queries:
        key = query.lower()
        if key not in cache:
            try:
                cache[key] = rank(await commons_candidates(client, query), item.name)
            except Exception as exc:  # noqa: BLE001 - photos are optional
                logger.warning("commons lookup failed for %s: %s", query, exc)
                cache[key] = []
            await asyncio.sleep(REQUEST_GAP_S)
        if cache[key]:
            return cache[key]
    return []


async def backfill(session: AsyncSession, *, force: bool = False) -> dict:
    """Find a real photo for every dish without one, then set restaurant covers."""
    items = list((await session.execute(select(MenuItem))).scalars())
    cache: dict[str, list[dict]] = {}
    found = skipped = missing = 0
    async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": USER_AGENT}) as client:
        for item in items:
            own_photo = (item.image_credit or {}).get("source") == "restaurant"
            if own_photo or (item.image_url and not force):
                skipped += 1
                continue
            choice = _pick(await _dish_rows(client, item, cache), str(item.id))
            if choice is None:
                missing += 1
                continue
            item.image_url = choice["url"]
            item.image_credit = {k: v for k, v in choice.items() if k != "landscape"}
            found += 1
    ai_service.record(
        session, provider="wikimedia_commons", purpose="dish_photos", detail=f"{found} found"
    )
    await session.flush()
    covers = await set_restaurant_covers(session, force=force)
    await session.commit()
    return {"dishes_found": found, "dishes_skipped": skipped, "dishes_missing": missing,
            "covers_set": covers}


async def set_restaurant_covers(session: AsyncSession, *, force: bool = False) -> int:
    """Use the most expensive dish with a photo as the restaurant's cover photo."""
    count = 0
    restaurants = list((await session.execute(select(Restaurant))).scalars())
    for restaurant in restaurants:
        if restaurant.image_url and not force:
            continue
        item = (
            await session.execute(
                select(MenuItem)
                .where(MenuItem.restaurant_id == restaurant.id, MenuItem.image_url.is_not(None))
                .order_by(MenuItem.price.desc())
            )
        ).scalars().first()
        if item is None:
            continue
        restaurant.image_url = item.image_url
        restaurant.image_credit = dict(item.image_credit or {}, dish=item.name)
        count += 1
    return count


async def upload_dish_photo(
    session: AsyncSession, restaurant: Restaurant, item_id: UUID, image: str
) -> MenuItem:
    item = await session.get(MenuItem, item_id)
    if item is None or item.restaurant_id != restaurant.id:
        raise NotFoundError("menu item not found")
    raw, mime = decode_image(image)
    item.image_url = save_image("dish", item.id, raw, mime)
    item.image_credit = {"source": "restaurant", "author": restaurant.name,
                         "licence": "Photo by the restaurant"}
    # A restaurant's own photo of its priciest dish becomes its cover photo.
    top = (
        await session.execute(
            select(MenuItem)
            .where(MenuItem.restaurant_id == restaurant.id)
            .order_by(MenuItem.price.desc())
        )
    ).scalars().first()
    if top is not None and top.id == item.id:
        restaurant.image_url = item.image_url
        restaurant.image_credit = dict(item.image_credit, dish=item.name)
    await session.commit()
    await session.refresh(item)
    return item


async def main() -> None:
    import argparse

    from app.db import get_sessionmaker

    parser = argparse.ArgumentParser(description="Fetch real dish photos from Wikimedia Commons.")
    parser.add_argument("--force", action="store_true", help="replace existing stock photos")
    args = parser.parse_args()
    async with get_sessionmaker()() as session:
        print(await backfill(session, force=args.force))


if __name__ == "__main__":
    asyncio.run(main())
