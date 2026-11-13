from fastapi import APIRouter, Depends, Query

from app.api.deps import SessionDep
from app.auth.deps import require_roles
from app.domain.models import Role
from app.learning import service as learning_service
from app.learning.schemas import ModelVersionOut, RetrainOut, RetrainRequest

router = APIRouter(
    prefix="/learning",
    tags=["learning"],
    dependencies=[Depends(require_roles(Role.ADMIN))],
)


@router.get("/models", response_model=list[ModelVersionOut])
async def list_models(
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ModelVersionOut]:
    versions = await learning_service.list_versions(session, limit=limit)
    return [ModelVersionOut.model_validate(version) for version in versions]


@router.post("/retrain", response_model=RetrainOut)
async def retrain(payload: RetrainRequest, session: SessionDep) -> RetrainOut:
    result = await learning_service.retrain(
        session,
        force=payload.force,
        min_rows=payload.min_rows,
    )
    return RetrainOut(
        version=result.version,
        promoted=result.promoted,
        improved=result.improved,
        metrics=result.metrics,
        active_version=result.active_version,
        active_metrics=result.active_metrics,
    )
