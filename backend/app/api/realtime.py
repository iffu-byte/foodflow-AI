import asyncio
from contextlib import suppress
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket

from app.auth.security import decode_access_token
from app.db import get_sessionmaker
from app.domain import service as domain_service
from app.domain.exceptions import NotFoundError
from app.domain.models import Rider, Role, User
from app.realtime import service as realtime_service

router = APIRouter(tags=["realtime"])

HEARTBEAT_SECONDS = 20.0


async def _load_snapshot(order_id: UUID) -> dict | None:
    async with get_sessionmaker()() as session:
        try:
            order = await domain_service.get_order(session, order_id)
        except NotFoundError:
            return None

        events = await domain_service.list_order_events(session, order_id)
        rider = (
            await session.get(Rider, order.rider_id) if order.rider_id is not None else None
        )
        return realtime_service.order_snapshot_message(order, events, rider)


async def _admin_for_token(token: str | None) -> User | None:
    if not token:
        return None
    payload = decode_access_token(token)
    if payload is None:
        return None
    try:
        user_id = UUID(str(payload.get("sub")))
    except (TypeError, ValueError):
        return None
    async with get_sessionmaker()() as session:
        user = await session.get(User, user_id)
        if user is None or not user.is_active or user.role is not Role.ADMIN:
            return None
        return user


@router.websocket("/ws/orders/{order_id}")
async def stream_order(
    websocket: WebSocket,
    order_id: UUID,
    token: str | None = Query(default=None),
) -> None:
    if await _admin_for_token(token) is None:
        await websocket.close(code=4401, reason="administrator authentication required")
        return
    await websocket.accept()

    stream = realtime_service.subscribe_order(order_id)
    pending = asyncio.create_task(anext(stream))
    try:
        snapshot = await _load_snapshot(order_id)
        if snapshot is None:
            await websocket.close(code=4404, reason="order not found")
            return

        await websocket.send_json(snapshot)

        while True:
            try:
                message = await asyncio.wait_for(
                    asyncio.shield(pending), timeout=HEARTBEAT_SECONDS
                )
            except TimeoutError:
                await websocket.send_json(realtime_service.heartbeat_message(order_id))
                continue
            pending = asyncio.create_task(anext(stream))
            await websocket.send_json(message)
    except Exception:
        pass
    finally:
        pending.cancel()
        with suppress(asyncio.CancelledError, StopAsyncIteration):
            await pending
        await stream.aclose()
