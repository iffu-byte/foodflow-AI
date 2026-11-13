from uuid import UUID

from sqlalchemy import select

from app.domain.models import Notification, Role, User


# notifications are persisted in the same transaction as the business change and
# published only after commit, so clients never see an event for rolled-back work.
async def add(
    session,
    user_id: UUID,
    type_: str,
    title: str,
    body: str,
    order_id: UUID | None = None,
) -> Notification:
    notification = Notification(
        user_id=user_id,
        type=type_,
        title=title,
        body=body,
        order_id=order_id,
    )
    session.add(notification)
    return notification


async def admin_ids(session) -> list[UUID]:
    rows = (
        await session.execute(select(User.id).where(User.role == Role.ADMIN))
    ).scalars()
    return list(rows)


async def notify_admins(session, type_: str, title: str, body: str, order_id=None):
    return [
        await add(session, user_id, type_, title, body, order_id)
        for user_id in await admin_ids(session)
    ]


async def publish(notifications) -> None:
    from app.realtime import service as realtime_service

    for notification in notifications:
        if notification is not None:
            await realtime_service.publish_notification(notification)

async def list_for_user(session, user_id, *, unread_only: bool = False, limit: int = 50):
    from app.domain.models import Notification

    stmt = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    stmt = stmt.order_by(Notification.created_at.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def mark_read(session, user_id, notification_id):
    from app.domain.exceptions import NotFoundError
    from app.domain.models import Notification

    notification = await session.get(Notification, notification_id)
    if notification is None or notification.user_id != user_id:
        raise NotFoundError("notification not found")
    notification.is_read = True
    await session.commit()
    return notification


async def mark_all_read(session, user_id) -> int:
    from sqlalchemy import update

    from app.domain.models import Notification

    result = await session.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    await session.commit()
    return int(result.rowcount or 0)
