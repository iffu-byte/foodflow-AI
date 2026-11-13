import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

EARTH_RADIUS_KM = 6371.0
DETOUR_FACTOR = 1.3
FREE_FLOW_SPEED_KMH = 24.0
CITY_CENTER = (17.4401, 78.3489)
CITY_TZ = timezone(timedelta(hours=5, minutes=30))

DEMAND_BY_HOUR = [
    0.20,
    0.15,
    0.10,
    0.08,
    0.08,
    0.10,
    0.25,
    0.40,
    0.60,
    0.80,
    1.10,
    1.90,
    3.00,
    2.80,
    1.80,
    0.90,
    1.00,
    1.40,
    2.00,
    2.60,
    2.50,
    2.40,
    1.50,
    0.70,
]

TRAFFIC_BY_HOUR = [
    0.80,
    0.78,
    0.78,
    0.80,
    0.82,
    0.85,
    0.90,
    1.00,
    1.30,
    1.35,
    1.20,
    1.10,
    1.15,
    1.15,
    1.05,
    1.00,
    1.05,
    1.20,
    1.35,
    1.40,
    1.35,
    1.15,
    0.95,
    0.85,
]

FEATURE_NAMES: tuple[str, ...] = (
    "distance_km",
    "routed_distance_km",
    "free_flow_drive_min",
    "hour_of_day",
    "day_of_week",
    "is_weekend",
    "item_count",
    "distinct_items",
    "avg_prep_complexity",
    "max_prep_complexity",
    "veg_share",
    "total_price",
    "restaurant_avg_prep_min",
    "restaurant_capacity_per_hr",
    "kitchen_load",
    "rain_intensity",
    "traffic_multiplier",
    "zone_factor",
)


@dataclass(frozen=True)
class ItemFeature:
    qty: int
    veg: bool
    prep_complexity: int


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def zone_factor(lat: float, lng: float) -> float:
    distance = haversine_km(CITY_CENTER[0], CITY_CENTER[1], lat, lng)
    return 1.0 + 0.12 * max(0.0, 1.0 - distance / 6.0)


def estimate_kitchen_load(hour: int) -> float:
    base = DEMAND_BY_HOUR[hour % 24] / 3.0
    return clamp(base * 0.7 + 0.15, 0.08, 1.0)


def local_hour(placed_at: datetime) -> datetime:
    if placed_at.tzinfo is None:
        placed_at = placed_at.replace(tzinfo=UTC)
    return placed_at.astimezone(CITY_TZ)


def build_feature_dict(
    *,
    restaurant_avg_prep_min: int,
    restaurant_capacity_per_hr: int,
    restaurant_lat: float,
    restaurant_lng: float,
    drop_lat: float,
    drop_lng: float,
    placed_at: datetime,
    total_price: float,
    items: Sequence[ItemFeature],
    rain_intensity: float = 0.0,
) -> dict[str, float]:
    local = local_hour(placed_at)
    hour = local.hour

    distance = haversine_km(restaurant_lat, restaurant_lng, drop_lat, drop_lng)
    routed = distance * DETOUR_FACTOR
    free_flow = routed / FREE_FLOW_SPEED_KMH * 60.0

    item_count = sum(item.qty for item in items)
    distinct = len(items)
    if item_count:
        avg_complexity = (
            sum(item.qty * item.prep_complexity for item in items) / item_count
        )
        veg_share = sum(item.qty for item in items if item.veg) / item_count
    else:
        avg_complexity = 1.0
        veg_share = 0.0
    max_complexity = max((item.prep_complexity for item in items), default=1)

    return {
        "distance_km": distance,
        "routed_distance_km": routed,
        "free_flow_drive_min": free_flow,
        "hour_of_day": float(hour),
        "day_of_week": float(local.weekday()),
        "is_weekend": float(local.weekday() >= 5),
        "item_count": float(item_count),
        "distinct_items": float(distinct),
        "avg_prep_complexity": avg_complexity,
        "max_prep_complexity": float(max_complexity),
        "veg_share": veg_share,
        "total_price": float(total_price),
        "restaurant_avg_prep_min": float(restaurant_avg_prep_min),
        "restaurant_capacity_per_hr": float(restaurant_capacity_per_hr),
        "kitchen_load": estimate_kitchen_load(hour),
        "rain_intensity": rain_intensity,
        "traffic_multiplier": TRAFFIC_BY_HOUR[hour % 24],
        "zone_factor": zone_factor(drop_lat, drop_lng),
    }
