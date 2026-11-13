import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

from app.config import settings
from app.domain.models import Order, OrderEvent, Rider
from app.domain.schemas import OrderEventOut, OrderOut
from app.realtime.broker import Broker, InMemoryBroker, Message, RedisBroker

logger = logging.getLogger(__name__)

CHANNEL_PREFIX = "foodflow:realtime"


def order_channel(order_id: UUID) -> str:
    return f"{CHANNEL_PREFIX}:order:{order_id}"


def restaurant_channel(restaurant_id: UUID) -> str:
    """Channel carrying all order and rider updates for one restaurant."""
    return f"{CHANNEL_PREFIX}:restaurant:{restaurant_id}"


def user_channel(user_id: UUID) -> str:
    return f"{CHANNEL_PREFIX}:user:{user_id}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


class RealtimeBus:
    """Publishes to Redis when available and degrades to in-process fanout.

    Publishing must never break order processing, so failures are logged and
    swallowed. Subscribers are moved to the in-memory broker when Redis drops.
    """

    def __init__(self) -> None:
        self._backend: Broker | None = None
        self._memory = InMemoryBroker()
        self.kind = "uninitialized"

    async def _backend_or_create(self) -> Broker:
        if self._backend is None:
            self._backend = await self._create_backend()
        return self._backend

    async def _create_backend(self) -> Broker:
        candidate = RedisBroker(settings.redis_url)
        try:
            await candidate.ping()
        except Exception:
            logger.warning(
                "realtime: Redis unavailable at %s, using in-memory fanout",
                settings.redis_url,
            )
            await _safe_close(candidate)
            self.kind = "memory"
            return self._memory
        self.kind = "redis"
        return candidate

    async def _degrade(self) -> None:
        backend = self._backend
        if backend is None or backend is self._memory:
            return
        self._backend = self._memory
        self.kind = "memory"
        await _safe_close(backend)

    async def publish(self, channel: str, message: Message) -> None:
        try:
            backend = await self._backend_or_create()
            await backend.publish(channel, message)
        except Exception:
            logger.warning("realtime: publish failed, degrading to in-memory", exc_info=True)
            await self._degrade()
            try:
                await self._memory.publish(channel, message)
            except Exception:
                logger.debug("realtime: fallback publish failed", exc_info=True)

    async def subscribe(self, channel: str) -> AsyncIterator[Message]:
        backend = await self._backend_or_create()
        try:
            async for message in backend.subscribe(channel):
                yield message
        except Exception:
            if backend is self._memory:
                raise
            logger.warning(
                "realtime: subscription failed, degrading to in-memory", exc_info=True
            )
            await self._degrade()
            async for message in self._memory.subscribe(channel):
                yield message

    async def aclose(self) -> None:
        if self._backend is not None:
            await _safe_close(self._backend)
            self._backend = None
        await self._memory.aclose()
        self.kind = "uninitialized"


async def _safe_close(broker: Broker) -> None:
    try:
        await broker.aclose()
    except Exception:
        logger.debug("realtime: broker close failed", exc_info=True)


bus = RealtimeBus()


def _order_state(order: Order) -> dict:
    return {
        "id": str(order.id),
        "status": order.status.value,
        "rider_id": str(order.rider_id) if order.rider_id is not None else None,
        "promised_eta_at": _iso(order.promised_eta_at),
        "deadline_at": _iso(order.deadline_at),
        "drop_lat": order.drop_lat,
        "drop_lng": order.drop_lng,
    }


def _rider_state(rider: Rider) -> dict:
    return {
        "id": str(rider.id),
        "name": rider.name,
        "lat": rider.lat,
        "lng": rider.lng,
        "location_source": rider.location_source,
        "location_accuracy_m": rider.location_accuracy_m,
        "last_seen_at": _iso(rider.last_seen_at),
    }


def _event_state(event: OrderEvent) -> dict:
    return OrderEventOut.model_validate(event).model_dump(mode="json")


def order_event_message(order: Order, event: OrderEvent) -> Message:
    return {
        "type": "order_event",
        "order_id": str(order.id),
        "sent_at": _now(),
        "order": _order_state(order),
        "event": _event_state(event),
    }


def rider_location_message(order_id: UUID, rider: Rider) -> Message:
    return {
        "type": "rider_location",
        "order_id": str(order_id),
        "sent_at": _now(),
        "rider": _rider_state(rider),
    }


def order_snapshot_message(
    order: Order,
    events: list[OrderEvent],
    rider: Rider | None,
) -> Message:
    return {
        "type": "order_snapshot",
        "order_id": str(order.id),
        "sent_at": _now(),
        "order": OrderOut.model_validate(order).model_dump(mode="json"),
        "rider": _rider_state(rider) if rider is not None else None,
        "events": [_event_state(event) for event in events],
    }


def heartbeat_message(order_id: UUID) -> Message:
    return {"type": "heartbeat", "order_id": str(order_id), "sent_at": _now()}


def notification_message(notification) -> Message:
    return {
        "type": "notification_created",
        "event_id": str(notification.id),
        "notification_id": str(notification.id),
        "sent_at": _now(),
        "notification": {
            "id": str(notification.id),
            "type": notification.type,
            "title": notification.title,
            "body": notification.body,
            "order_id": (
                str(notification.order_id) if notification.order_id is not None else None
            ),
            "is_read": notification.is_read,
            "created_at": _iso(notification.created_at),
        },
    }


async def publish_order_event(order: Order, event: OrderEvent) -> None:
    message = order_event_message(order, event)
    await bus.publish(order_channel(order.id), message)
    await bus.publish(restaurant_channel(order.restaurant_id), message)


async def publish_rider_location(
    rider: Rider, active_orders: list[tuple[UUID, UUID]]
) -> None:
    """Fan out a rider position to each active order and its restaurant.

    The tuple contains ``(order_id, restaurant_id)`` so the realtime layer can
    publish without another database lookup.  This keeps a GPS update cheap
    while allowing a restaurant board to stay synchronized before pickup.
    """
    for order_id, restaurant_id in active_orders:
        message = rider_location_message(order_id, rider)
        await bus.publish(order_channel(order_id), message)
        await bus.publish(restaurant_channel(restaurant_id), message)


async def publish_notification(notification) -> None:
    await bus.publish(
        user_channel(notification.user_id), notification_message(notification)
    )


def subscribe_order(order_id: UUID) -> AsyncIterator[Message]:
    return bus.subscribe(order_channel(order_id))


def subscribe_restaurant(restaurant_id: UUID) -> AsyncIterator[Message]:
    return bus.subscribe(restaurant_channel(restaurant_id))


def subscribe_user(user_id: UUID) -> AsyncIterator[Message]:
    return bus.subscribe(user_channel(user_id))
