from dataclasses import dataclass


@dataclass(frozen=True)
class EtaPrediction:
    eta_minutes: float
    prep_minutes: float
    drive_minutes: float
    low_minutes: float
    high_minutes: float
    source: str
    model_version: str

    def event_payload(self) -> dict:
        return {
            "eta_minutes": self.eta_minutes,
            "prep_minutes": self.prep_minutes,
            "drive_minutes": self.drive_minutes,
            "low_minutes": self.low_minutes,
            "high_minutes": self.high_minutes,
            "source": self.source,
            "model_version": self.model_version,
        }
