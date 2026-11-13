from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import update

from app.domain.models import Order, OrderEvent
from app.realtime import service as realtime


async def _create_order(client, context):
    response = await client.post(
        "/orders",
        json={
            "customer_id": context["customer_id"],
            "restaurant_id": context["restaurant_id"],
            "items": [{"menu_item_id": context["item_id"], "qty": 1}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _set_promised_eta(session_factory, order_id: str, when: datetime) -> None:
    async with session_factory() as session:
        await session.execute(
            update(Order).where(Order.id == UUID(order_id)).values(promised_eta_at=when)
        )
        await session.commit()


async def test_late_order_is_flagged_and_scan_is_idempotent(
    client, order_context, session_factory, monkeypatch
) -> None:
    messages: list[tuple[str, dict]] = []

    async def fake_publish(channel, message):
        messages.append((channel, message))

    monkeypatch.setattr(realtime.bus, "publish", fake_publish)

    order = await _create_order(client, order_context)
    past = datetime.now(UTC) - timedelta(minutes=5)
    await _set_promised_eta(session_factory, order["id"], past)

    risk = await client.get("/monitor/at-risk")
    assert risk.status_code == 200, risk.text
    rows = risk.json()
    match = next(row for row in rows if row["order"]["id"] == order["id"])
    assert "late" in match["flags"]
    assert match["severity"] == "critical"
    assert match["risk_score"] >= 60
    assert match["minutes_remaining"] < 0

    events_before = (await client.get(f"/orders/{order['id']}/events")).json()
    scan = await client.post("/monitor/scan")
    assert scan.status_code == 200, scan.text
    body = scan.json()
    assert body["flagged"] >= 1
    assert body["events_appended"] >= 1
    assert any(row["order"]["id"] == order["id"] for row in body["orders"])

    events_after = (await client.get(f"/orders/{order['id']}/events")).json()
    delay_events = [event for event in events_after if event["type"] == "delay_flagged"]
    assert len(delay_events) == len(events_after) - len(events_before)
    assert len(delay_events) == 1
    assert "late" in delay_events[0]["payload"]["new_flags"]
    assert messages[-1][1]["event"]["type"] == "delay_flagged"

    stored = (await client.get(f"/orders/{order['id']}")).json()
    assert "late" in stored["delay_flags"]

    again = await client.post("/monitor/scan")
    assert again.json()["events_appended"] == 0

    await _set_promised_eta(session_factory, order["id"], datetime.now(UTC) + timedelta(minutes=90))
    resolved = await client.post("/monitor/scan")
    assert resolved.status_code == 200
    stored = (await client.get(f"/orders/{order['id']}")).json()
    assert stored["delay_flags"] == []


async def test_stalled_order_is_detected(client, order_context, session_factory) -> None:
    order = await _create_order(client, order_context)
    await _set_promised_eta(
        session_factory, order["id"], datetime.now(UTC) + timedelta(minutes=90)
    )
    old = datetime.now(UTC) - timedelta(minutes=45)
    async with session_factory() as session:
        await session.execute(
            update(OrderEvent)
            .where(OrderEvent.order_id == UUID(order["id"]))
            .values(created_at=old)
        )
        await session.commit()

    risk = await client.get("/monitor/at-risk")
    rows = risk.json()
    match = next(row for row in rows if row["order"]["id"] == order["id"])
    assert "stalled" in match["flags"]
    assert match["minutes_since_last_event"] >= 44


async def test_monitor_summary(client, order_context, session_factory) -> None:
    await _create_order(client, order_context)
    response = await client.get("/monitor/summary")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["active_orders"] >= 1
    assert body["at_risk"] >= 0
