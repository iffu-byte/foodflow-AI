"""Pure geography and demand helpers shared by the simulator.

The formulas here are the hidden "ground truth" of the synthetic city: the
history generator and the live runner both use them, while the API and any
later learning phase only ever see the resulting timings.
"""

import hashlib
import math
import random
from datetime import timedelta, timezone

EARTH_RADIUS_KM = 6371.0088
DETOUR_FACTOR = 1.3
FREE_FLOW_SPEED_KMH = 24.0
CITY_CENTER = (17.4401, 78.3489)
CITY_TZ = timezone(timedelta(hours=5, minutes=30))

VEHICLE_TIME_FACTOR = {"bike": 1.0, "scooter": 1.05, "cycle": 1.35}

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


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def free_flow_minutes(road_distance_km: float) -> float:
    return road_distance_km / FREE_FLOW_SPEED_KMH * 60.0


def traffic_multiplier(hour: int) -> float:
    return TRAFFIC_BY_HOUR[hour % 24]


def demand_rate_per_min(hour: int) -> float:
    return DEMAND_BY_HOUR[hour % 24]


def zone_factor(lat: float, lng: float) -> float:
    distance = haversine_km(CITY_CENTER[0], CITY_CENTER[1], lat, lng)
    return round(1.0 + 0.12 * max(0.0, 1.0 - distance / 6.0), 4)


def vehicle_time_factor(vehicle: str) -> float:
    return VEHICLE_TIME_FACTOR.get(vehicle, 1.0)


def stable_fraction(key: str) -> float:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:16], 16) / float(16**16)


def stable_factor(key: str, low: float, high: float) -> float:
    return low + (high - low) * stable_fraction(key)


def point_along(
    start: tuple[float, float],
    end: tuple[float, float],
    fraction: float,
) -> tuple[float, float]:
    fraction = clamp(fraction, 0.0, 1.0)
    return (
        start[0] + (end[0] - start[0]) * fraction,
        start[1] + (end[1] - start[1]) * fraction,
    )


def poisson_sample(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    threshold = math.exp(-lam)
    count = 0
    product = 1.0
    while True:
        count += 1
        product *= rng.random()
        if product <= threshold:
            return count - 1
