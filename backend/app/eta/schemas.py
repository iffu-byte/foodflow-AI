from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class EtaOut(BaseModel):
    eta_minutes: float
    prep_minutes: float
    drive_minutes: float
    low_minutes: float
    high_minutes: float
    source: Literal["model", "fallback"]
    model_version: str
    promised_eta_at: datetime | None = None
    deadline_at: datetime | None = None
    meets_deadline: bool | None = None
