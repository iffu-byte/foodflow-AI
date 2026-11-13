from decimal import Decimal
from uuid import uuid4


async def _create_order(client, context, **overrides):
    payload = {
        "customer_id": context["customer_id"],
        "restaurant_id": context["restaurant_id"],
        "items": [{"menu_item_id": context["item_id"], "qty": 2}],
    }
    payload.update(overrides)
    return await client.post("/orders", json=payload)


async def test_order_lifecycle_and_event_log(client, order_context) -> None:
    response = await _create_order(client, order_context)
    assert response.status_code == 201, response.text
    order = response.json()
    assert order["status"] == "PLACED"
    assert Decimal(order["total_price"]) == Decimal("398.00")
    assert order["drop_lat"] == 17.44
    order_id = order["id"]

    for action in ("accept", "preparing", "ready"):
        result = await client.post(f"/restaurant/orders/{order_id}/{action}")
        assert result.status_code == 200, result.text

    picked = await client.post(
        f"/orders/{order_id}/status",
        json={"status": "PICKED_UP", "rider_id": order_context["rider_id"]},
    )
    assert picked.status_code == 200, picked.text
    assert picked.json()["rider_id"] == order_context["rider_id"]

    delivered = await client.post(
        f"/orders/{order_id}/status",
        json={"status": "DELIVERED", "rider_id": order_context["rider_id"]},
    )
    assert delivered.status_code == 200, delivered.text
    assert delivered.json()["status"] == "DELIVERED"

    events_response = await client.get(f"/orders/{order_id}/events")
    assert events_response.status_code == 200
    events = events_response.json()
    assert events[0]["type"] == "order_placed"
    transitions = [event["payload"]["to"] for event in events if event["type"] == "status_changed"]
    assert transitions == ["ACCEPTED", "PREPARING", "READY", "PICKED_UP", "DELIVERED"]


async def test_illegal_transitions_rejected(client, order_context) -> None:
    response = await _create_order(client, order_context)
    order_id = response.json()["id"]

    premature_ready = await client.post(f"/restaurant/orders/{order_id}/ready")
    assert premature_ready.status_code == 409

    cancelled = await client.post(
        f"/orders/{order_id}/cancel", json={"reason": "changed my mind"}
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"

    accept_cancelled = await client.post(f"/restaurant/orders/{order_id}/accept")
    assert accept_cancelled.status_code == 409


async def test_cannot_cancel_after_pickup(client, order_context) -> None:
    response = await _create_order(client, order_context)
    order_id = response.json()["id"]
    for action in ("accept", "preparing", "ready"):
        assert (await client.post(f"/restaurant/orders/{order_id}/{action}")).status_code == 200

    picked = await client.post(
        f"/orders/{order_id}/status",
        json={"status": "PICKED_UP", "rider_id": order_context["rider_id"]},
    )
    assert picked.status_code == 200

    cancel = await client.post(f"/orders/{order_id}/cancel")
    assert cancel.status_code == 409


async def test_invalid_cart_is_rejected(client, order_context) -> None:
    unknown_item = await _create_order(
        client,
        order_context,
        items=[{"menu_item_id": str(uuid4()), "qty": 1}],
    )
    assert unknown_item.status_code == 400

    duplicate_item = await _create_order(
        client,
        order_context,
        items=[
            {"menu_item_id": order_context["item_id"], "qty": 1},
            {"menu_item_id": order_context["item_id"], "qty": 2},
        ],
    )
    assert duplicate_item.status_code == 400


async def test_order_listing_filters_and_limit(client, order_context) -> None:
    created = await _create_order(client, order_context)
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]

    listing = await client.get("/orders", params={"limit": 5})
    assert listing.status_code == 200
    rows = listing.json()
    assert len(rows) <= 5
    assert any(row["id"] == order_id for row in rows)
    assert all("items" in row for row in rows)

    placed = await client.get("/orders", params={"status": "PLACED", "limit": 200})
    assert placed.status_code == 200
    placed_rows = placed.json()
    assert all(row["status"] == "PLACED" for row in placed_rows)
    assert any(row["id"] == order_id for row in placed_rows)

    cancelled = await client.post(f"/orders/{order_id}/cancel")
    assert cancelled.status_code == 200
    placed = await client.get("/orders", params={"status": "PLACED", "limit": 200})
    assert all(row["id"] != order_id for row in placed.json())

    assert (await client.get("/orders", params={"status": "NOPE"})).status_code == 422
    assert (await client.get("/orders", params={"limit": 0})).status_code == 422


async def test_unknown_order_returns_404(client) -> None:
    missing = await client.get(f"/orders/{uuid4()}")
    assert missing.status_code == 404
    events = await client.get(f"/orders/{uuid4()}/events")
    assert events.status_code == 404


async def test_restaurant_listing_and_menu(client, order_context) -> None:
    listing = await client.get("/restaurants", params={"lat": 17.44, "lng": 78.35})
    assert listing.status_code == 200
    rows = listing.json()
    row = next(item for item in rows if item["id"] == order_context["restaurant_id"])
    assert row["distance_km"] is not None
    assert row["distance_km"] < 1

    menu = await client.get(f"/restaurants/{order_context['restaurant_id']}/menu")
    assert menu.status_code == 200
    menu_items = menu.json()
    assert [item["id"] for item in menu_items] == [order_context["item_id"]]

    unpaired = await client.get("/restaurants", params={"lat": 17.44})
    assert unpaired.status_code == 422
