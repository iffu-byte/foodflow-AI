"""Quantity-aware calories and macros for every dish.

Lookup order, cheapest first: the cached estimate on the menu item; the local
dish table; Gemini (only for dishes the table cannot place, once per dish,
under the daily AI budget); a category default. The result is stored on the
menu item, so customer views never trigger an AI call.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import service as ai_service
from app.domain.models import Customer, MenuItem, Order, OrderItem, OrderStatus
from app.nutrition.dataset import ALLERGEN_WORDS, CATEGORY_DEFAULTS, DISHES, GENERIC_DEFAULT

NUTRITION_VERSION = 2
DEFAULT_KCAL_GOAL = 2000

GEMINI_PROMPT = """Estimate typical Indian restaurant nutrition for this dish.
Dish: "{name}". Menu category: {category}. Description: "{description}".
Return only JSON with keys: kcal, protein_g, carbs_g, fat_g, fibre_g (all per 100 g, numbers),
typical_portion_g (number), allergens (array from: dairy, gluten, egg, nuts, peanuts,
shellfish, fish, soy, sesame)."""


def _text(item: MenuItem) -> str:
    return " ".join(
        [
            item.name,
            item.description or "",
            " ".join(item.tags or []),
            " ".join(item.ingredients or []),
        ]
    ).lower()


def match_dish(name: str):
    lowered = name.lower()
    best = None
    best_len = 0
    for dish in DISHES:
        for key in dish.keys:
            if key in lowered and len(key) > best_len:
                best, best_len = dish, len(key)
    return best, best_len


def detect_allergens(item: MenuItem, base: tuple[str, ...] = ()) -> list[str]:
    text = _text(item)
    found = set(base)
    for allergen, words in ALLERGEN_WORDS.items():
        if any(word in text for word in words):
            found.add(allergen)
    return sorted(found)


def local_estimate(item: MenuItem) -> dict:
    dish, matched_len = match_dish(item.name)
    if dish is not None:
        per100 = {
            "kcal": dish.kcal,
            "protein_g": dish.protein,
            "carbs_g": dish.carbs,
            "fat_g": dish.fat,
            "fibre_g": dish.fibre,
        }
        return {
            "version": NUTRITION_VERSION,
            "source": "dish_table",
            "matched": max(dish.keys, key=len),
            "confidence": 0.75 if matched_len >= 8 else 0.6,
            "per100g": per100,
            "typical_portion_g": dish.portion_g,
            "typical_pieces": dish.pieces,
            "allergens": detect_allergens(item, dish.allergens),
            "computed_at": datetime.now(UTC).isoformat(),
        }
    kcal, protein, carbs, fat, fibre, portion = CATEGORY_DEFAULTS.get(
        (item.category or "").lower(), GENERIC_DEFAULT
    )
    return {
        "version": NUTRITION_VERSION,
        "source": "category_default",
        "matched": item.category,
        "confidence": 0.35,
        "per100g": {
            "kcal": kcal,
            "protein_g": protein,
            "carbs_g": carbs,
            "fat_g": fat,
            "fibre_g": fibre,
        },
        "typical_portion_g": portion,
        "typical_pieces": None,
        "allergens": detect_allergens(item),
        "computed_at": datetime.now(UTC).isoformat(),
    }


def _number(value, low: float, high: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if low <= number <= high else None


async def ensure_for_item(
    session: AsyncSession, item: MenuItem, *, force: bool = False, allow_ai: bool = True
) -> dict:
    """Return the cached estimate, computing and storing it when missing."""
    cached = item.nutrition or {}
    if cached.get("version") == NUTRITION_VERSION and not force:
        return cached
    estimate = local_estimate(item)
    if estimate["source"] == "category_default" and allow_ai:
        result = await ai_service.gemini_json(
            session,
            purpose="nutrition_estimate",
            prompt=GEMINI_PROMPT.format(
                name=item.name, category=item.category, description=item.description or ""
            ),
        )
        if result is not None:
            data = result.data
            per100 = {
                "kcal": _number(data.get("kcal"), 5, 900),
                "protein_g": _number(data.get("protein_g"), 0, 90),
                "carbs_g": _number(data.get("carbs_g"), 0, 100),
                "fat_g": _number(data.get("fat_g"), 0, 100),
                "fibre_g": _number(data.get("fibre_g"), 0, 40),
            }
            if all(value is not None for value in per100.values()):
                allergens = [
                    str(value)
                    for value in data.get("allergens", [])
                    if str(value) in ALLERGEN_WORDS
                ]
                estimate.update(
                    source="gemini",
                    matched=item.name,
                    confidence=0.55,
                    per100g=per100,
                    typical_portion_g=int(
                        _number(data.get("typical_portion_g"), 20, 1500)
                        or estimate["typical_portion_g"]
                    ),
                    allergens=sorted(set(allergens) | set(detect_allergens(item))),
                )
    item.nutrition = estimate
    return estimate


def portion_view(item: MenuItem) -> dict:
    """Nutrition for the portion the customer actually receives."""
    data = item.nutrition or local_estimate(item)
    if item.portion_grams:
        grams = item.portion_grams
        measured = item.portion_method not in {"declared", "unknown"}
        grams_source = "measured" if measured else "declared"
    else:
        grams = data.get("typical_portion_g") or 250
        grams_source = "typical"
    factor = grams / 100.0
    per100 = data["per100g"]
    return {
        "grams": grams,
        "grams_source": grams_source,
        "kcal": round(per100["kcal"] * factor),
        "protein_g": round(per100["protein_g"] * factor, 1),
        "carbs_g": round(per100["carbs_g"] * factor, 1),
        "fat_g": round(per100["fat_g"] * factor, 1),
        "fibre_g": round(per100["fibre_g"] * factor, 1),
        "allergens": data.get("allergens", []),
        "source": data.get("source"),
        "confidence": data.get("confidence"),
        "per100g": per100,
        "estimate": True,
    }


async def ensure_for_items(session: AsyncSession, items: list[MenuItem]) -> None:
    """Fill missing estimates for a menu from the local table only (no AI per view)."""
    changed = False
    for item in items:
        if (item.nutrition or {}).get("version") != NUTRITION_VERSION:
            await ensure_for_item(session, item, allow_ai=False)
            changed = True
    if changed:
        await session.commit()


async def today_intake(session: AsyncSession, customer_id: UUID) -> dict:
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (
        await session.execute(
            select(OrderItem, MenuItem, Order)
            .join(Order, Order.id == OrderItem.order_id)
            .join(MenuItem, MenuItem.id == OrderItem.menu_item_id)
            .where(
                Order.customer_id == customer_id,
                Order.placed_at >= start,
                Order.status.not_in((OrderStatus.CANCELLED, OrderStatus.FAILED)),
            )
        )
    ).all()
    totals = {"kcal": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0, "fibre_g": 0.0}
    lines = []
    for order_item, menu_item, order in rows:
        if (menu_item.nutrition or {}).get("version") != NUTRITION_VERSION:
            await ensure_for_item(session, menu_item, allow_ai=False)
        view = portion_view(menu_item)
        for key in totals:
            totals[key] += view[key] * order_item.qty
        lines.append(
            {
                "order_id": order.id,
                "order_number": order.order_number,
                "name": order_item.name,
                "qty": order_item.qty,
                "kcal": view["kcal"] * order_item.qty,
                "protein_g": round(view["protein_g"] * order_item.qty, 1),
            }
        )
    customer = await session.get(Customer, customer_id)
    goal = (customer.daily_kcal_goal if customer else None) or DEFAULT_KCAL_GOAL
    await session.commit()
    return {
        "goal_kcal": goal,
        "goal_is_default": not (customer and customer.daily_kcal_goal),
        "totals": {key: round(value, 1) for key, value in totals.items()},
        "remaining_kcal": round(goal - totals["kcal"]),
        "lines": lines,
        "estimate": True,
    }
