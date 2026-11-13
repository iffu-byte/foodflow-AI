from collections.abc import Mapping

from app.eta.types import EtaPrediction

FALLBACK_VERSION = "heuristic-v1"


def fallback_eta(features: Mapping[str, float]) -> EtaPrediction:
    """Deterministic heuristic used whenever the trained model is unavailable."""
    complexity = 1.0 + 0.1 * (features["avg_prep_complexity"] - 1.0)
    prep = (
        features["restaurant_avg_prep_min"]
        * complexity
        * (1.0 + 0.5 * features["kitchen_load"])
    )
    drive = (
        features["free_flow_drive_min"]
        * features["traffic_multiplier"]
        * features["zone_factor"]
        * (1.0 + 0.35 * features["rain_intensity"])
    )
    total = max(3.0, prep + drive)
    margin = max(3.0, 0.18 * total)
    return EtaPrediction(
        eta_minutes=round(total, 1),
        prep_minutes=round(max(1.0, prep), 1),
        drive_minutes=round(max(0.5, drive), 1),
        low_minutes=round(max(1.0, total - margin), 1),
        high_minutes=round(total + margin, 1),
        source="fallback",
        model_version=FALLBACK_VERSION,
    )
