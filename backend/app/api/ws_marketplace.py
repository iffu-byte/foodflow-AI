import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket

from app.auth.security import decode_access_token
from app.db import get_sessionmaker
from app.domain import service as domain_service
from app.domain.exceptions import NotFoundError
from app.domain.models import Rider, Role, User
from app.marketplace import access
from app.realtime import service as realtime_service

router = APIRouter(tags=["marketplace-realtime"])

HEARTBEAT_SECONDS = 20.0


async def _user_for_token(token: str | None) -> User | None:
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
        if user is None or not user.is_active:
            return None
        return user


async def _order_snapshot(order_id: UUID, user: User) -> dict | None:
    async with get_sessionmaker()() as session:
        try:
            order = await domain_service.get_order(session, order_id)
            await access.assert_can_view_order(session, user, order)
        except NotFoundError:
            return None
        events = await domain_service.list_order_events(session, order_id)
        rider = (
            await session.get(Rider, order.rider_id) if order.rider_id is not None else None
        )
        return realtime_service.order_snapshot_message(order, events, rider)


async def _restaurant_id_for_token(token: str | None) -> UUID | None:
    user = await _user_for_token(token)
    if user is None or user.role is not Role.RESTAURANT:
        return None
    async with get_sessionmaker()() as session:
        try:
            return (await access.restaurant_for(session, user)).id
        except NotFoundError:
            return None


def _heartbeat() -> dict:
    return {
        "type": "heartbeat",
        "sent_at": datetime.now(UTC).isoformat(),
    }


@router.websocket("/ws/notifications")
async def stream_notifications(
    websocket: WebSocket, token: str | None = Query(default=None)
) -> None:
    user = await _user_for_token(token)
    if user is None:
        await websocket.close(code=4401, reason="authentication required")
        return
    await websocket.accept()
    stream = realtime_service.subscribe_user(user.id)
    pending = asyncio.create_task(anext(stream))
    try:
        await websocket.send_json(
            {"type": "ready", "channel": "notifications", "user_id": str(user.id)}
        )
        while True:
            try:
                message = await asyncio.wait_for(
                    asyncio.shield(pending), timeout=HEARTBEAT_SECONDS
                )
            except TimeoutError:
                await websocket.send_json(_heartbeat())
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


@router.websocket("/ws/v1/orders/{order_id}")
async def stream_order(
    websocket: WebSocket,
    order_id: UUID,
    token: str | None = Query(default=None),
) -> None:
    user = await _user_for_token(token)
    if user is None:
        await websocket.close(code=4401, reason="authentication required")
        return
    snapshot = await _order_snapshot(order_id, user)
    if snapshot is None:
        await websocket.close(code=4404, reason="order not found")
        return
    await websocket.accept()
    stream = realtime_service.subscribe_order(order_id)
    pending = asyncio.create_task(anext(stream))
    try:
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


@router.websocket("/ws/v1/restaurant/orders")
async def stream_restaurant_orders(
    websocket: WebSocket, token: str | None = Query(default=None)
) -> None:
    """Stream every order event and assigned-rider location for one kitchen."""
    restaurant_id = await _restaurant_id_for_token(token)
    if restaurant_id is None:
        await websocket.close(code=4403, reason="restaurant authentication required")
        return

    await websocket.accept()
    stream = realtime_service.subscribe_restaurant(restaurant_id)
    pending = asyncio.create_task(anext(stream))
    try:
        # The client refreshes after this message, closing the REST/WS hand-off race.
        await websocket.send_json(
            {
                "type": "restaurant_ready",
                "restaurant_id": str(restaurant_id),
                "sent_at": datetime.now(UTC).isoformat(),
            }
        )
        while True:
            try:
                message = await asyncio.wait_for(
                    asyncio.shield(pending), timeout=HEARTBEAT_SECONDS
                )
            except TimeoutError:
                await websocket.send_json(_heartbeat())
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
