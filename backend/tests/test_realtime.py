import asyncio
from uuid import UUID

import pytest

from app.config import settings
from app.domain import service as domain_service
from app.realtime import service as realtime
from app.realtime.broker import InMemoryBroker
from app.realtime.service import RealtimeBus


async def _create_order(client, context, **overrides):
    payload = {
        "customer_id": context["customer_id"],
        "restaurant_id": context["restaurant_id"],
        "items": [{"menu_item_id": context["item_id"], "qty": 1}],
    }
    payload.update(overrides)
    return await client.post("/orders", json=payload)


@pytest.fixture
def published(monkeypatch):
    messages: list[tuple[str, dict]] = []

    async def fake_publish(channel, message):
        messages.append((channel, message))

    monkeypatch.setattr(realtime.bus, "publish", fake_publish)
    return messages


async def test_in_memory_broker_roundtrip() -> None:
    broker = InMemoryBroker()
    stream = broker.subscribe("chan")
    consumer = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)

    await broker.publish("chan", {"type": "hello"})
    message = await asyncio.wait_for(consumer, timeout=1)

    assert message == {"type": "hello"}
    await stream.aclose()
    await broker.aclose()


async def test_bus_degrades_when_redis_is_unreachable(monkeypatch) -> None:
    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:6399/0")
    bus = RealtimeBus()

    await bus.publish("probe", {"type": "probe"})
    assert bus.kind == "memory"

    stream = bus.subscribe("probe")
    consumer = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    await bus.publish("probe", {"type": "hello"})
    message = await asyncio.wait_for(consumer, timeout=1)

    assert message == {"type": "hello"}
    await stream.aclose()
    await bus.aclose()


async def test_bus_publish_never_raises_and_degrades() -> None:
    class FailingBroker:
        async def publish(self, channel, message):
            raise RuntimeError("broker down")

        def subscribe(self, channel):
            raise RuntimeError("broker down")

        async def aclose(self):
            return None

    bus = RealtimeBus()
    bus._backend = FailingBroker()
    bus.kind = "redis"

    await bus.publish("chan", {"type": "probe"})
    assert bus.kind == "memory"

    stream = bus.subscribe("chan")
    consumer = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    await bus.publish("chan", {"type": "hello"})
    message = await asyncio.wait_for(consumer, timeout=1)
    assert message == {"type": "hello"}
    await stream.aclose()
    await bus.aclose()


async def test_order_lifecycle_publishes_events(client, order_context, published) -> None:
    response = await _create_order(client, order_context)
    assert response.status_code == 201, response.text
    order_id = response.json()["id"]

    assert [message["event"]["type"] for _, message in published] == [
        "order_placed",
        "order_placed",
        "eta_predicted",
        "eta_predicted",
    ]
    assert [channel for channel, _ in published] == [
        realtime.order_channel(UUID(order_id)),
        realtime.restaurant_channel(UUID(order_context["restaurant_id"])),
        realtime.order_channel(UUID(order_id)),
        realtime.restaurant_channel(UUID(order_context["restaurant_id"])),
    ]
    placed = published[0][1]
    assert placed["order_id"] == order_id
    assert placed["order"]["status"] == "PLACED"
    assert placed["order"]["promised_eta_at"] is not None
    assert placed["event"]["payload"]["item_count"] == 1

    accepted = await client.post(f"/restaurant/orders/{order_id}/accept")
    assert accepted.status_code == 200, accepted.text
    assert [channel for channel, _ in published[-2:]] == [
        realtime.order_channel(UUID(order_id)),
        realtime.restaurant_channel(UUID(order_context["restaurant_id"])),
    ]
    message = published[-1][1]
    assert message["event"]["type"] == "status_changed"
    assert message["event"]["payload"]["to"] == "ACCEPTED"
    assert message["order"]["status"] == "ACCEPTED"


async def test_rider_location_publishes_to_active_orders(
    client, order_context, published
) -> None:
    response = await _create_order(client, order_context)
    order_id = response.json()["id"]
    for action in ("accept", "preparing", "ready"):
        assert (await client.post(f"/restaurant/orders/{order_id}/{action}")).status_code == 200
    picked = await client.post(
        f"/orders/{order_id}/status",
        json={"status": "PICKED_UP", "rider_id": order_context["rider_id"]},
    )
    assert picked.status_code == 200, picked.text

    published.clear()
    updated = await client.post(
        f"/riders/{order_context['rider_id']}/location",
        json={
            "lat": 17.4501,
            "lng": 78.3611,
            "source": "gps",
            "accuracy_m": 7.5,
        },
    )
    assert updated.status_code == 200, updated.text

    assert [channel for channel, _ in published] == [
        realtime.order_channel(UUID(order_id)),
        realtime.restaurant_channel(UUID(order_context["restaurant_id"])),
    ]
    _, message = published[0]
    assert message["type"] == "rider_location"
    assert message["order_id"] == order_id
    assert message["rider"]["id"] == order_context["rider_id"]
    assert message["rider"]["lat"] == 17.4501
    assert message["rider"]["location_source"] == "gps"
    assert message["rider"]["location_accuracy_m"] == 7.5
    assert message["rider"]["last_seen_at"] is not None


async def test_rider_location_without_active_orders_publishes_nothing(
    client, order_context, published
) -> None:
    updated = await client.post(
        f"/riders/{order_context['rider_id']}/location",
        json={"lat": 17.45, "lng": 78.36},
    )
    assert updated.status_code == 200
    assert published == []


async def test_order_snapshot_message(client, order_context, session_factory) -> None:
    response = await _create_order(client, order_context)
    order_id = response.json()["id"]

    async with session_factory() as session:
        order = await domain_service.get_order(session, UUID(order_id))
        events = await domain_service.list_order_events(session, UUID(order_id))
        snapshot = realtime.order_snapshot_message(order, events, None)

    assert snapshot["type"] == "order_snapshot"
    assert snapshot["order_id"] == order_id
    assert snapshot["order"]["status"] == "PLACED"
    assert snapshot["rider"] is None
    assert [event["type"] for event in snapshot["events"]] == [
        "order_placed",
        "eta_predicted",
    ]
    assert snapshot["sent_at"] is not None
