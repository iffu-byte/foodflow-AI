"""Proof of delivery: the door OTP and the GPS geofence at handover.

A rider cannot mark an order delivered from down the road. Completion needs
two independent proofs: the rider's last location is fresh and within the
geofence of the customer's pin, and the four-digit code that only the
customer's app shows is entered. The proof is stored on the order, so a
"delivered but never received" dispute can be answered with evidence.
"""

import hmac
import secrets
from datetime import UTC, datetime, timedelta

from app.config import settings
from app.domain.exceptions import ConflictError
from app.domain.geo import haversine_km
from app.domain.models import Order, Rider

LOCATION_FRESH = timedelta(minutes=2)
ARRIVAL_RADIUS_M = 400.0
MAX_ACCURACY_ALLOWANCE_M = 100.0


def generate_otp() -> str:
    return f"{secrets.randbelow(10_000):04d}"


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def distance_to_drop_m(order: Order, rider: Rider) -> float:
    return haversine_km(rider.lat, rider.lng, order.drop_lat, order.drop_lng) * 1000.0


def _allowance(rider: Rider) -> float:
    if rider.location_source == "gps" and rider.location_accuracy_m:
        return min(float(rider.location_accuracy_m), MAX_ACCURACY_ALLOWANCE_M)
    return 0.0


def _require_fresh(rider: Rider) -> None:
    seen = _aware(rider.last_seen_at)
    if seen is None or datetime.now(UTC) - seen > LOCATION_FRESH:
        raise ConflictError(
            "your location is out of date; send a location update before continuing"
        )


def check_arrival(order: Order, rider: Rider) -> float:
    """Arrival is allowed only near the pin, so the customer isn't told too early."""
    _require_fresh(rider)
    distance = distance_to_drop_m(order, rider)
    limit = ARRIVAL_RADIUS_M + _allowance(rider)
    if distance > limit:
        raise ConflictError(
            f"you are {distance:,.0f} m from the drop pin; get within {limit:,.0f} m "
            "to mark arrival"
        )
    return distance


def verify_handover(order: Order, rider: Rider, otp: str | None) -> dict:
    """Validate geofence and OTP; return the proof to store on the order.

    The OTP attempt counter is incremented by the caller on failure so the
    attempt is persisted even though the request is rejected.
    """
    if order.otp_attempts >= settings.otp_max_attempts:
        raise ConflictError(
            "too many wrong codes; this delivery is locked for support review"
        )
    _require_fresh(rider)
    distance = distance_to_drop_m(order, rider)
    radius = settings.geofence_radius_m + _allowance(rider)
    if distance > radius:
        raise ConflictError(
            f"you are {distance:,.0f} m from the customer's pin; "
            f"delivery can be completed within {radius:,.0f} m"
        )
    if order.delivery_otp is None:
        raise ConflictError("this order has no delivery code; contact support")
    code = (otp or "").strip()
    if not code:
        raise ConflictError("ask the customer for the 4-digit delivery code")
    if not hmac.compare_digest(code, order.delivery_otp):
        raise ConflictError("wrong_otp")
    return {
        "method": "otp_geofence",
        "verified_at": datetime.now(UTC).isoformat(),
        "distance_m": round(distance, 1),
        "radius_m": round(radius, 1),
        "location_source": rider.location_source,
        "location_accuracy_m": rider.location_accuracy_m,
        "rider_lat": round(rider.lat, 6),
        "rider_lng": round(rider.lng, 6),
    }
