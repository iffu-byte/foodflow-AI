"""Estimate a dish's weight from measurements the restaurant takes in the app.

A single photo cannot give absolute size on its own: a small plate close to the
camera looks like a big plate far away. Every photo method here therefore needs
a reference of known size in the same plane as the food (a coin, a plate, a
card, or the restaurant's own registered container). The estimate comes with a
range and a confidence so the menu never shows a measurement as more precise
than it is.

Methods
- ``photo_reference``: the owner marks the reference object and the food
  outline on the photo; pixels become centimetres, the footprint area becomes a
  volume through a dish-shape depth, and density turns volume into grams.
- ``container``: the dish is packed in a container of known volume; the owner
  sets how full it is.
- ``scale``: grams read off a kitchen scale (highest confidence).
- ``pieces``: count-based dishes (naan, idli, momos) use pieces x piece weight.
"""

import math
from dataclasses import dataclass

REFERENCES_CM = {
    "coin_10": 2.7,  # ₹10 bimetallic coin diameter
    "coin_5": 2.3,
    "coin_2": 2.5,
    "card": 8.56,  # ID-1 card long edge
    "plate_10in": 25.4,
    "plate_12in": 30.5,
    "custom": None,
}

# depth_cm: typical heap height over the footprint; fill: how much of the
# footprint-times-depth prism the food really occupies; density in g/cm^3.
DISH_PROFILES: dict[str, dict] = {
    "rice": {"label": "Rice / biryani / pulao", "depth_cm": 4.5, "fill": 0.55, "density": 0.72},
    "curry": {"label": "Curry / gravy / dal", "depth_cm": 4.0, "fill": 0.75, "density": 1.02},
    "noodles": {"label": "Noodles / pasta", "depth_cm": 4.0, "fill": 0.55, "density": 0.62},
    "dry": {"label": "Dry starter / stir fry", "depth_cm": 3.5, "fill": 0.45, "density": 0.70},
    "flat": {"label": "Dosa / pizza / flatbread", "depth_cm": 1.0, "fill": 0.85, "density": 0.60},
    "salad": {"label": "Salad / greens", "depth_cm": 4.0, "fill": 0.40, "density": 0.35},
    "dessert": {"label": "Dessert / sweet", "depth_cm": 3.0, "fill": 0.70, "density": 0.95},
    "burger": {"label": "Burger / sandwich", "depth_cm": 6.5, "fill": 0.70, "density": 0.55},
}

PIECE_GRAMS = {
    "naan": 90,
    "roti": 40,
    "paratha": 80,
    "idli": 40,
    "vada": 50,
    "momo": 30,
    "kebab": 45,
    "wing": 35,
    "samosa": 60,
    "gulab jamun": 40,
    "dosa": 180,
}

DEFAULT_PORTION_PER_PERSON_G = 300


@dataclass(frozen=True)
class Estimate:
    grams: int
    low_grams: int
    high_grams: int
    confidence: float
    method: str
    serves: int
    explanation: list[str]


def _serves(grams: float, profile: str) -> int:
    per_person = 350 if profile == "rice" else 250 if profile in {"curry", "noodles"} else 300
    return max(1, round(grams / per_person))


def suggest_profile(name: str, category: str, tags: list[str]) -> str:
    text = " ".join([name, category, *tags]).lower()
    for profile, words in (
        ("rice", ("biryani", "rice", "pulao", "khichdi", "bowl")),
        ("noodles", ("noodle", "pasta", "penne", "spaghetti", "hakka", "chowmein")),
        ("flat", ("dosa", "pizza", "uttapam", "naan", "paratha", "roti")),
        ("burger", ("burger", "sandwich", "wrap", "roll")),
        ("dessert", ("dessert", "cake", "brownie", "ice cream", "kheer", "halwa", "jamun")),
        ("salad", ("salad",)),
        ("curry", ("curry", "masala", "gravy", "dal", "makhani", "korma", "sambar", "paneer")),
    ):
        if any(word in text for word in words):
            return profile
    return "dry"


def from_photo(
    *,
    reference: str,
    reference_px: float,
    food_rx_px: float,
    food_ry_px: float,
    profile: str,
    custom_reference_cm: float | None = None,
    depth_cm: float | None = None,
) -> Estimate:
    """Footprint (ellipse radii in pixels) plus a reference diameter in pixels."""
    if profile not in DISH_PROFILES:
        raise ValueError("unknown dish profile")
    reference_cm = (
        custom_reference_cm if reference == "custom" else REFERENCES_CM.get(reference)
    )
    if not reference_cm or reference_cm <= 0:
        raise ValueError("reference size is required")
    if reference_px < 8:
        raise ValueError("mark the reference object on the photo first")
    if food_rx_px <= 0 or food_ry_px <= 0:
        raise ValueError("outline the food on the photo first")

    px_per_cm = reference_px / reference_cm
    rx_cm = food_rx_px / px_per_cm
    ry_cm = food_ry_px / px_per_cm
    area_cm2 = math.pi * rx_cm * ry_cm
    shape = DISH_PROFILES[profile]
    depth = depth_cm if depth_cm and depth_cm > 0 else shape["depth_cm"]
    volume_cm3 = area_cm2 * depth * shape["fill"]
    grams = volume_cm3 * shape["density"]

    # The reference's apparent size drives the measurement error: a coin only
    # 20 px wide gives roughly +/-10% scale error, which squares in the area.
    scale_error = min(0.25, 2.0 / reference_px + 0.03)
    spread = min(0.45, 2 * scale_error + 0.18)
    confidence = round(max(0.35, min(0.8, 0.85 - spread)), 2)
    return Estimate(
        grams=round(grams),
        low_grams=round(grams * (1 - spread)),
        high_grams=round(grams * (1 + spread)),
        confidence=confidence,
        method="photo_reference",
        serves=_serves(grams, profile),
        explanation=[
            f"Reference: {reference_cm:g} cm across = {reference_px:.0f} px "
            f"({px_per_cm:.1f} px per cm).",
            f"Food footprint: {2 * rx_cm:.1f} x {2 * ry_cm:.1f} cm, area {area_cm2:.0f} cm².",
            f"{shape['label']}: {depth:g} cm heap, {int(shape['fill'] * 100)}% fill "
            f"-> {volume_cm3:.0f} cm³.",
            f"Density {shape['density']} g/cm³ -> about {grams:.0f} g "
            f"(range {grams * (1 - spread):.0f}-{grams * (1 + spread):.0f} g).",
        ],
    )


def from_container(*, capacity_ml: float, fill_fraction: float, profile: str) -> Estimate:
    if profile not in DISH_PROFILES:
        raise ValueError("unknown dish profile")
    if capacity_ml <= 0 or not 0 < fill_fraction <= 1.0:
        raise ValueError("container capacity and fill level are required")
    shape = DISH_PROFILES[profile]
    # Loose foods leave air gaps even in a "full" box; fill already captures
    # that for a heaped footprint, so use a milder packing factor here.
    packing = 0.85 if profile in {"curry", "dessert"} else 0.75
    grams = capacity_ml * fill_fraction * packing * shape["density"]
    spread = 0.12
    return Estimate(
        grams=round(grams),
        low_grams=round(grams * (1 - spread)),
        high_grams=round(grams * (1 + spread)),
        confidence=0.85,
        method="container",
        serves=_serves(grams, profile),
        explanation=[
            f"Container {capacity_ml:.0f} ml filled to {fill_fraction * 100:.0f}%.",
            f"{shape['label']}: packing {packing}, density {shape['density']} g/cm³.",
            f"About {grams:.0f} g (+/-{int(spread * 100)}%).",
        ],
    )


def from_scale(*, grams: float, profile: str) -> Estimate:
    if grams <= 0 or grams > 10000:
        raise ValueError("enter the weight shown on the scale in grams")
    return Estimate(
        grams=round(grams),
        low_grams=round(grams * 0.97),
        high_grams=round(grams * 1.03),
        confidence=0.95,
        method="scale",
        serves=_serves(grams, profile if profile in DISH_PROFILES else "dry"),
        explanation=[f"Weighed on a kitchen scale: {grams:.0f} g (packaging excluded)."],
    )


def from_pieces(*, name: str, pieces: int, piece_grams: float | None = None) -> Estimate:
    if pieces <= 0:
        raise ValueError("piece count must be positive")
    per_piece = piece_grams
    if not per_piece:
        lowered = name.lower()
        per_piece = next(
            (grams for word, grams in PIECE_GRAMS.items() if word in lowered), 50
        )
    grams = pieces * per_piece
    return Estimate(
        grams=round(grams),
        low_grams=round(grams * 0.9),
        high_grams=round(grams * 1.1),
        confidence=0.8,
        method="pieces",
        serves=max(1, round(grams / DEFAULT_PORTION_PER_PERSON_G)),
        explanation=[f"{pieces} pieces x about {per_piece:g} g each = {grams:.0f} g."],
    )


def cross_check(local: Estimate, ai_grams: float | None) -> tuple[float, str | None]:
    """Raise confidence when an independent AI read agrees; flag a big gap."""
    if not ai_grams or ai_grams <= 0:
        return local.confidence, None
    gap = abs(ai_grams - local.grams) / max(local.grams, 1)
    if gap <= 0.25:
        return round(max(local.confidence, min(0.9, local.confidence + 0.1)), 2), (
            f"AI vision read about {ai_grams:.0f} g, within {gap * 100:.0f}% of the measurement."
        )
    return round(max(0.3, local.confidence - 0.1), 2), (
        f"AI vision read about {ai_grams:.0f} g, {gap * 100:.0f}% away from the measurement; "
        "re-check the reference marks."
    )
