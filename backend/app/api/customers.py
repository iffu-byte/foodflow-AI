from fastapi import APIRouter, Depends

from app.api.deps import SessionDep
from app.auth.deps import require_roles
from app.domain import service
from app.domain.models import Role
from app.domain.schemas import CustomerOut

router = APIRouter(
    prefix="/customers",
    tags=["customers"],
    dependencies=[Depends(require_roles(Role.ADMIN))],
)


@router.get("", response_model=list[CustomerOut])
async def list_customers(session: SessionDep) -> list[CustomerOut]:
    rows = await service.list_customers(session)
    return [
        CustomerOut(
            id=customer.user_id,
            name=user.name,
            home_lat=customer.home_lat,
            home_lng=customer.home_lng,
            budget_pref=customer.budget_pref,
            diet_pref=customer.diet_pref,
        )
        for customer, user in rows
    ]
