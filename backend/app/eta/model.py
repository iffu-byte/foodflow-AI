import math
from collections.abc import Mapping

import joblib

from app.eta.types import EtaPrediction

REQUIRED_KEYS = (
    "version",
    "feature_names",
    "prep_model",
    "drive_model",
    "total_low_model",
    "total_high_model",
)


class EtaEngine:
    """Serving wrapper around a joblib model bundle trained by ml/train_eta.py."""

    def __init__(self, bundle: Mapping) -> None:
        missing = [key for key in REQUIRED_KEYS if key not in bundle]
        if missing:
            raise ValueError(f"ETA model bundle is missing keys: {missing}")
        self.version = str(bundle["version"])
        self.feature_names = tuple(str(name) for name in bundle["feature_names"])
        self.prep_model = bundle["prep_model"]
        self.drive_model = bundle["drive_model"]
        self.total_low_model = bundle["total_low_model"]
        self.total_high_model = bundle["total_high_model"]

    @classmethod
    def load(cls, path: str) -> "EtaEngine":
        return cls(joblib.load(path))

    def predict(self, features: Mapping[str, float]) -> EtaPrediction:
        vector = [[float(features[name]) for name in self.feature_names]]

        prep = float(self.prep_model.predict(vector)[0])
        drive = float(self.drive_model.predict(vector)[0])
        low = float(self.total_low_model.predict(vector)[0])
        high = float(self.total_high_model.predict(vector)[0])
        if not all(math.isfinite(value) for value in (prep, drive, low, high)):
            raise ValueError("ETA model produced a non-finite prediction")

        prep = max(1.0, prep)
        drive = max(0.5, drive)
        total = prep + drive
        low = max(1.0, min(low, total))
        high = max(high, total)
        return EtaPrediction(
            eta_minutes=round(total, 1),
            prep_minutes=round(prep, 1),
            drive_minutes=round(drive, 1),
            low_minutes=round(low, 1),
            high_minutes=round(high, 1),
            source="model",
            model_version=self.version,
        )
