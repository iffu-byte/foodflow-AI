from dataclasses import dataclass

from app.domain.geo import haversine_km
from app.domain.models import Order, Rider, RiderStatus

PICKUP_SPEED_KMH = 24.0
LOAD_PENALTY_MIN = 4.0
STATUS_DELAY_MIN = {
    RiderStatus.IDLE: 0.0,
    RiderStatus.TO_PICKUP: 2.0,
    RiderStatus.TO_DROP: 4.0,
}
LARGE_ORDER_ITEMS = 6
BIKE_PENALTY_MIN = 2.0


@dataclass(frozen=True)
class Candidate:
    rider: Rider
    score: float
    pickup_distance_km: float
    pickup_eta_min: float
    active_load: int
    reasons: list[str]


def _vehicle_penalty(rider: Rider, item_count: int) -> float:
    if item_count >= LARGE_ORDER_ITEMS and rider.vehicle not in ("car", "van"):
        return BIKE_PENALTY_MIN
    return 0.0


def rank_candidates(
    order: Order,
    riders: list[Rider],
    restaurant_lat: float,
    restaurant_lng: float,
) -> list[Candidate]:
    item_count = sum(item.qty for item in order.items)
    candidates: list[Candidate] = []

    for rider in riders:
        if rider.status is RiderStatus.OFFLINE:
            continue
        load = len(rider.active_order_ids or [])
        if load >= rider.capacity:
            continue

        distance = haversine_km(rider.lat, rider.lng, restaurant_lat, restaurant_lng)
        pickup_eta = distance / PICKUP_SPEED_KMH * 60.0
        penalty = STATUS_DELAY_MIN.get(rider.status, 0.0) + _vehicle_penalty(rider, item_count)
        score = round(pickup_eta + load * LOAD_PENALTY_MIN + penalty, 2)

        reasons = [f"{distance:.1f} km from restaurant"]
        if load:
            reasons.append(f"{load} active order(s) already assigned")
        if penalty:
            reasons.append(f"+{penalty:.0f} min for current status/vehicle fit")

        candidates.append(
            Candidate(
                rider=rider,
                score=score,
                pickup_distance_km=round(distance, 2),
                pickup_eta_min=round(pickup_eta, 1),
                active_load=load,
                reasons=reasons,
            )
        )

    return sorted(candidates, key=lambda candidate: (candidate.score, candidate.rider.name))
