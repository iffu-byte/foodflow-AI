"""Portion Studio: measure, cross-check and publish a dish's real quantity."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import service as ai_service
from app.domain.exceptions import BadRequestError, NotFoundError
from app.domain.models import MenuItem, Restaurant
from app.media import decode_image, save_image
from app.nutrition import service as nutrition_service
from app.portion import estimator

REFERENCE_TEXT = {
    "coin_10": "an Indian 10 rupee coin (2.7 cm across)",
    "coin_5": "an Indian 5 rupee coin (2.3 cm across)",
    "coin_2": "an Indian 2 rupee coin (2.5 cm across)",
    "card": "a bank/ID card (8.56 cm long edge)",
    "plate_10in": "a 10 inch (25.4 cm) dinner plate",
    "plate_12in": "a 12 inch (30.5 cm) plate",
    "custom": "a reference object of the stated size",
}

VISION_PROMPT = """You are checking a restaurant's portion photo for a food delivery menu.
Menu item: "{name}". Reference object in frame: {reference}.
Estimate the cooked food weight in grams using the reference for scale, ignoring the container.
Also say whether the photo looks like a real photo of this dish (not a stock or AI-generated image).
Return only JSON with keys:
dish_detected (string), matches_menu_item (boolean), estimated_grams (number),
pieces (integer or null), reference_visible (boolean), looks_real_photo (boolean),
notes (string, under 25 words)."""


async def _owned_item(session: AsyncSession, restaurant: Restaurant, item_id: UUID) -> MenuItem:
    item = await session.get(MenuItem, item_id)
    if item is None or item.restaurant_id != restaurant.id:
        raise NotFoundError("menu item not found")
    return item


def _estimate(item: MenuItem, payload) -> estimator.Estimate:
    profile = payload.profile or estimator.suggest_profile(
        item.name, item.category, item.tags or []
    )
    try:
        if payload.method == "photo_reference":
            return estimator.from_photo(
                reference=payload.reference or "coin_10",
                reference_px=payload.reference_px or 0,
                food_rx_px=payload.food_rx_px or 0,
                food_ry_px=payload.food_ry_px or 0,
                profile=profile,
                custom_reference_cm=payload.custom_reference_cm,
                depth_cm=payload.depth_cm,
            )
        if payload.method == "container":
            return estimator.from_container(
                capacity_ml=payload.capacity_ml or 0,
                fill_fraction=payload.fill_fraction or 0,
                profile=profile,
            )
        if payload.method == "scale":
            return estimator.from_scale(grams=payload.grams or 0, profile=profile)
        if payload.method == "pieces":
            return estimator.from_pieces(
                name=item.name, pieces=payload.pieces or 0, piece_grams=payload.piece_grams
            )
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    raise BadRequestError("unknown measurement method")


async def estimate(
    session: AsyncSession, restaurant: Restaurant, item_id: UUID, payload
) -> dict:
    item = await _owned_item(session, restaurant, item_id)
    result = _estimate(item, payload)
    confidence = result.confidence
    ai_block = None
    if payload.image and payload.method == "photo_reference":
        raw, mime = decode_image(payload.image)
        vision = await ai_service.gemini_json(
            session,
            purpose="portion_vision",
            prompt=VISION_PROMPT.format(
                name=item.name,
                reference=REFERENCE_TEXT.get(payload.reference or "coin_10", "a reference object"),
            ),
            image_bytes=raw,
            mime_type=mime,
        )
        if vision is not None:
            ai_grams = vision.data.get("estimated_grams")
            try:
                ai_grams = float(ai_grams) if ai_grams is not None else None
            except (TypeError, ValueError):
                ai_grams = None
            confidence, note = estimator.cross_check(result, ai_grams)
            ai_block = {
                "provider": "gemini",
                "dish_detected": vision.data.get("dish_detected"),
                "matches_menu_item": vision.data.get("matches_menu_item"),
                "estimated_grams": ai_grams,
                "pieces": vision.data.get("pieces"),
                "reference_visible": vision.data.get("reference_visible"),
                "looks_real_photo": vision.data.get("looks_real_photo"),
                "notes": vision.data.get("notes"),
                "agreement": note,
                "cost_usd": round(vision.cost_usd, 6),
            }
        await session.commit()
    return {
        "menu_item_id": item.id,
        "method": result.method,
        "grams": result.grams,
        "low_grams": result.low_grams,
        "high_grams": result.high_grams,
        "serves": result.serves,
        "confidence": confidence,
        "explanation": result.explanation,
        "ai_check": ai_block,
        "ai_available": ai_service.gemini_enabled(),
    }


async def publish(
    session: AsyncSession, restaurant: Restaurant, item_id: UUID, payload
) -> MenuItem:
    item = await _owned_item(session, restaurant, item_id)
    if payload.grams is not None and not 10 <= payload.grams <= 5000:
        raise BadRequestError("portion grams must be between 10 and 5000")
    if payload.serves is not None and not 1 <= payload.serves <= 12:
        raise BadRequestError("serves must be between 1 and 12")
    method = payload.method or "declared"
    if method not in {"declared", "photo_reference", "container", "scale", "pieces"}:
        raise BadRequestError("unknown portion method")
    if method == "photo_reference" and not payload.image:
        raise BadRequestError("a photo-verified portion needs the photo")

    item.portion_grams = payload.grams
    item.portion_serves = payload.serves
    item.portion_pieces = payload.pieces
    item.portion_method = method
    item.portion_confidence = payload.confidence if method != "declared" else None
    if payload.image:
        raw, mime = decode_image(payload.image)
        item.portion_photo_url = save_image("portion", item.id, raw, mime)
    if method != "declared":
        item.portion_verified_at = datetime.now(UTC)
    # Calories scale with the published grams; refresh the cached estimate.
    await nutrition_service.ensure_for_item(session, item, force=False)
    await session.commit()
    await session.refresh(item)
    return item
