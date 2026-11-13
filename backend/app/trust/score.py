"""Restaurant trust score: an explainable 0-100 built from checkable signals.

Each component reports its points, maximum and a plain sentence, so the
customer sees why a kitchen scored what it did rather than a bare number.
"""

from dataclasses import dataclass, field

LOCATION_POINTS = {
    "verified": 20,
    "osm_match": 15,
    "osm_food_nearby": 8,
    "mismatch": 4,
    "closed": 0,
    "not_found": 0,
    "osm_no_food": 0,
    "unchecked": 0,
}

LOCATION_TEXT = {
    "verified": "A matching listing exists at this exact location on Google Maps.",
    "osm_match": "OpenStreetMap shows a food business with this name at the pin.",
    "osm_food_nearby": "Food businesses are mapped at the pin, but none with this name.",
    "mismatch": "The closest map listing is far from the pin or has a different name.",
    "closed": "The map listing at this location is marked closed.",
    "not_found": "No map listing matches this kitchen near its pin.",
    "osm_no_food": "No food business is mapped at this pin on OpenStreetMap.",
    "unchecked": "The location has not been checked against a map yet.",
}


@dataclass
class TrustInputs:
    fssai_status: str
    location_verdict: str
    kitchen_photo_age_days: float | None
    menu_items: int
    items_with_portion: int
    items_portion_verified: int
    quantity_ok: int
    quantity_short: int
    sibling_brands: list[str] = field(default_factory=list)
    kitchen_type: str = "dine_in"


def compute(inputs: TrustInputs) -> dict:
    components: list[dict] = []

    licence = 15 if inputs.fssai_status == "format_ok" else 0
    components.append(
        {
            "key": "licence",
            "label": "Food licence",
            "points": licence,
            "max": 15,
            "detail": {
                "format_ok": "FSSAI number on file with a valid format.",
                "missing": "No FSSAI number on file.",
                "invalid": "The FSSAI number on file has an invalid format.",
                "expired": "The FSSAI licence on file has expired.",
            }.get(inputs.fssai_status, "Licence not checked."),
        }
    )

    location = LOCATION_POINTS.get(inputs.location_verdict, 0)
    components.append(
        {
            "key": "location",
            "label": "Real location",
            "points": location,
            "max": 20,
            "detail": LOCATION_TEXT.get(inputs.location_verdict, LOCATION_TEXT["unchecked"]),
        }
    )

    age = inputs.kitchen_photo_age_days
    if age is None:
        photos, photo_text = 0, "No kitchen photos uploaded."
    elif age <= 14:
        photos, photo_text = 10, f"Kitchen photographed {int(age)} days ago."
    elif age <= 45:
        photos, photo_text = 6, f"Latest kitchen photo is {int(age)} days old."
    else:
        photos, photo_text = 2, f"Latest kitchen photo is {int(age)} days old (stale)."
    components.append(
        {
            "key": "kitchen_photos",
            "label": "Kitchen photos",
            "points": photos,
            "max": 10,
            "detail": photo_text,
        }
    )

    total = max(1, inputs.menu_items)
    declared = inputs.items_with_portion / total
    verified = inputs.items_portion_verified / total
    portion = round(12 * declared + 8 * verified, 1)
    components.append(
        {
            "key": "portions",
            "label": "Portion transparency",
            "points": portion,
            "max": 20,
            "detail": (
                f"{inputs.items_with_portion}/{inputs.menu_items} dishes show grams or servings; "
                f"{inputs.items_portion_verified} are photo- or scale-verified."
            ),
        }
    )

    reviews = inputs.quantity_ok + inputs.quantity_short
    if reviews < 3:
        quantity = 12.5
        quantity_text = (
            f"Only {reviews} quantity rating{'s' if reviews != 1 else ''} so far; "
            "scored as neutral."
        )
    else:
        share = inputs.quantity_ok / reviews
        quantity = round(25 * share, 1)
        quantity_text = (
            f"{inputs.quantity_ok} of {reviews} customers said the quantity matched the menu."
        )
    components.append(
        {
            "key": "quantity",
            "label": "Quantity as described",
            "points": quantity,
            "max": 25,
            "detail": quantity_text,
        }
    )

    disclosed = inputs.kitchen_type in {"cloud_kitchen", "shared_kitchen"}
    if not inputs.sibling_brands:
        honesty, honesty_text = 10, "No other brands are listed from this kitchen."
    elif disclosed:
        honesty = 10
        honesty_text = (
            "Shares its kitchen with " + ", ".join(inputs.sibling_brands) + " and says so."
        )
    else:
        honesty = 0
        honesty_text = (
            "Shares a kitchen with "
            + ", ".join(inputs.sibling_brands)
            + " but lists itself as a dine-in restaurant."
        )
    components.append(
        {
            "key": "kitchen_honesty",
            "label": "Kitchen disclosure",
            "points": honesty,
            "max": 10,
            "detail": honesty_text,
        }
    )

    score = round(sum(component["points"] for component in components))
    badges: list[str] = []
    if inputs.location_verdict in {"verified", "osm_match"}:
        badges.append("Real kitchen verified")
    if declared >= 0.8:
        badges.append("Portions declared")
    if verified >= 0.5:
        badges.append("Portion photos verified")
    if age is not None and age <= 14:
        badges.append("Fresh kitchen photos")
    warnings: list[str] = []
    if inputs.sibling_brands and not disclosed:
        warnings.append("Undisclosed shared kitchen")
    if inputs.location_verdict in {"not_found", "osm_no_food", "closed", "mismatch"}:
        warnings.append("Location could not be confirmed")
    if inputs.fssai_status in {"missing", "invalid", "expired"}:
        warnings.append("Licence problem")
    if reviews >= 3 and inputs.quantity_short / reviews > 0.4:
        warnings.append("Frequent short-quantity reports")

    grade = "A" if score >= 80 else "B" if score >= 65 else "C" if score >= 45 else "D"
    return {
        "score": score,
        "grade": grade,
        "components": components,
        "badges": badges,
        "warnings": warnings,
    }
