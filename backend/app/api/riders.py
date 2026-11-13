from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import SessionDep
from app.auth.deps import require_roles
from app.domain import service
from app.domain.models import Role
from app.domain.schemas import RiderLocationUpdate, RiderOut

router = APIRouter(
    prefix="/riders",
    tags=["riders"],
    dependencies=[Depends(require_roles(Role.ADMIN))],
)


@router.get("", response_model=list[RiderOut])
async def list_riders(session: SessionDep) -> list[RiderOut]:
    riders = await service.list_riders(session)
    return [RiderOut.model_validate(rider) for rider in riders]


@router.post("/{rider_id}/location", response_model=RiderOut)
async def update_rider_location(
    rider_id: UUID,
    payload: RiderLocationUpdate,
    session: SessionDep,
) -> RiderOut:
    rider = await service.update_rider_location(
        session,
        rider_id,
        payload.lat,
        payload.lng,
        source=payload.source,
        accuracy_m=payload.accuracy_m,
    )
    return RiderOut.model_validate(rider)
