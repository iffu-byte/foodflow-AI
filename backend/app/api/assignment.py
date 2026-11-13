from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import SessionDep
from app.assignment import service as assignment_service
from app.assignment.schemas import AssignmentOut, AssignRequest, CandidateOut
from app.auth.deps import require_roles
from app.domain.models import Role
from app.domain.schemas import OrderOut, RiderOut

router = APIRouter(
    prefix="/orders/{order_id}",
    tags=["assignment"],
    dependencies=[Depends(require_roles(Role.ADMIN))],
)


@router.get("/candidates", response_model=list[CandidateOut])
async def list_candidates(order_id: UUID, session: SessionDep) -> list[CandidateOut]:
    candidates = await assignment_service.list_candidates(session, order_id)
    return [
        CandidateOut(
            rider=RiderOut.model_validate(candidate.rider),
            score=candidate.score,
            pickup_distance_km=candidate.pickup_distance_km,
            pickup_eta_min=candidate.pickup_eta_min,
            active_load=candidate.active_load,
            reasons=candidate.reasons,
        )
        for candidate in candidates
    ]


@router.post("/assign", response_model=AssignmentOut)
async def assign_order(
    order_id: UUID,
    session: SessionDep,
    body: AssignRequest | None = None,
) -> AssignmentOut:
    order, candidate = await assignment_service.assign_order(
        session,
        order_id,
        rider_id=body.rider_id if body else None,
    )
    return AssignmentOut(
        order=OrderOut.model_validate(order),
        rider=RiderOut.model_validate(candidate.rider),
        score=candidate.score,
        reasons=candidate.reasons,
    )
