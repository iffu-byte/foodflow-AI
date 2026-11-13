from typing import Literal

from pydantic import BaseModel

from app.domain.schemas import OrderOut, RiderOut


class RiskOrderOut(BaseModel):
    order: OrderOut
    rider: RiderOut | None
    severity: Literal["warning", "critical"]
    flags: list[str]
    minutes_remaining: float | None
    minutes_since_last_event: float
    risk_score: int
    reasons: list[str]


class ScanOut(BaseModel):
    scanned: int
    flagged: int
    events_appended: int
    orders: list[RiskOrderOut]


class MonitorSummaryOut(BaseModel):
    active_orders: int
    at_risk: int
    late: int
    stalled: int
    avg_minutes_remaining: float | None
