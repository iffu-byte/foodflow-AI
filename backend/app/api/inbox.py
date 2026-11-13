from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import SessionDep
from app.auth.deps import CurrentUser
from app.marketplace import notifications
from app.marketplace.schemas import NotificationOut
from app.marketplace.serializers import notification_out

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    user: CurrentUser,
    session: SessionDep,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[NotificationOut]:
    rows = await notifications.list_for_user(
        session, user.id, unread_only=unread_only, limit=limit
    )
    return [notification_out(row) for row in rows]


@router.post("/{notification_id}/read", response_model=NotificationOut)
async def mark_read(
    notification_id: UUID, user: CurrentUser, session: SessionDep
) -> NotificationOut:
    row = await notifications.mark_read(session, user.id, notification_id)
    return notification_out(row)


@router.post("/read-all")
async def mark_all_read(user: CurrentUser, session: SessionDep) -> dict[str, int]:
    updated = await notifications.mark_all_read(session, user.id)
    return {"updated": updated}
