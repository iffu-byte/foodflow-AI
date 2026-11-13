from uuid import UUID

from pydantic import BaseModel

from app.domain.schemas import OrderOut, RiderOut


class CandidateOut(BaseModel):
    rider: RiderOut
    score: float
    pickup_distance_km: float
    pickup_eta_min: float
    active_load: int
    reasons: list[str]


class AssignRequest(BaseModel):
    rider_id: UUID | None = None


class AssignmentOut(BaseModel):
    order: OrderOut
    rider: RiderOut
    score: float
    reasons: list[str]
