from uuid import uuid4

from app.assignment import service as assignment_service
from app.assignment.scoring import Candidate
from app.domain.models import Order, Restaurant, Rider, RiderStatus, Role, User
from app.marketplace import dispatch
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


async def _ready_order(client, context):
    order = await _create_order(client, context)
    for action in ("accept", "preparing", "ready"):
        response = await client.post(f"/restaurant/orders/{order['id']}/{action}")
        assert response.status_code == 200, response.text
    return order


async def _add_rider(session_factory, lat: float, lng: float, status=RiderStatus.IDLE) -> str:
    async with session_factory() as session:
        user = User(name=f"Rider {uuid4().hex[:6]}", role=Role.RIDER)
        session.add(user)
        await session.flush()
        rider = Rider(
            user_id=user.id,
            name=user.name,
            lat=lat,
            lng=lng,
            status=status,
            capacity=2,
        )
        session.add(rider)
        await session.commit()
        return str(rider.id)


async def test_candidates_are_ranked_by_eta(client, order_context, session_factory) -> None:
    far_rider_id = await _add_rider(session_factory, 17.60, 78.42)
    order = await _ready_order(client, order_context)

    response = await client.get(f"/orders/{order['id']}/candidates")
    assert response.status_code == 200, response.text

    candidates = response.json()
    ids = [candidate["rider"]["id"] for candidate in candidates]
    assert order_context["rider_id"] in ids
    assert far_rider_id in ids

    scores = [candidate["score"] for candidate in candidates]
    assert scores == sorted(scores)
    near_index = ids.index(order_context["rider_id"])
    far_index = ids.index(far_rider_id)
    assert near_index < far_index

    near = candidates[near_index]
    assert near["pickup_distance_km"] < 1
    assert near["pickup_eta_min"] >= 0
    assert near["reasons"]


async def test_auto_assign_and_rider_lifecycle(client, order_context, monkeypatch) -> None:
    messages: list[tuple[str, dict]] = []

    async def fake_publish(channel, message):
        messages.append((channel, message))

    monkeypatch.setattr(realtime.bus, "publish", fake_publish)

    order = await _ready_order(client, order_context)
    candidates = (await client.get(f"/orders/{order['id']}/candidates")).json()
    assert candidates
    best_rider_id = candidates[0]["rider"]["id"]

    response = await client.post(f"/orders/{order['id']}/assign")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["order"]["rider_id"] == best_rider_id
    assert body["rider"]["id"] == best_rider_id
    assert body["rider"]["status"] == "to_pickup"
    assert order["id"] in body["rider"]["active_order_ids"]
    assert body["reasons"]

    assert messages[-1][1]["event"]["type"] == "rider_assigned"
    assert messages[-1][1]["event"]["payload"]["auto"] is True

    events = (await client.get(f"/orders/{order['id']}/events")).json()
    assigned = [event for event in events if event["type"] == "rider_assigned"]
    assert len(assigned) == 1
    assert assigned[0]["payload"]["rider_id"] == best_rider_id

    picked = await client.post(
        f"/orders/{order['id']}/status",
        json={"status": "PICKED_UP", "rider_id": best_rider_id},
    )
    assert picked.status_code == 200, picked.text
    riders = (await client.get("/riders")).json()
    rider = next(row for row in riders if row["id"] == best_rider_id)
    assert rider["status"] == "to_drop"
    assert order["id"] in rider["active_order_ids"]

    delivered = await client.post(
        f"/orders/{order['id']}/status",
        json={"status": "DELIVERED", "rider_id": best_rider_id},
    )
    assert delivered.status_code == 200, delivered.text
    riders = (await client.get("/riders")).json()
    rider = next(row for row in riders if row["id"] == best_rider_id)
    assert rider["status"] == "idle"
    assert order["id"] not in rider["active_order_ids"]


async def test_assign_rejects_unready_and_assigned_orders(client, order_context) -> None:
    placed = await _create_order(client, order_context)
    early = await client.post(f"/orders/{placed['id']}/assign")
    assert early.status_code == 400

    order = await _ready_order(client, order_context)
    first = await client.post(f"/orders/{order['id']}/assign")
    assert first.status_code == 200, first.text
    second = await client.post(f"/orders/{order['id']}/assign")
    assert second.status_code == 409
    candidates = await client.get(f"/orders/{order['id']}/candidates")
    assert candidates.status_code == 409


async def test_assign_rejects_ineligible_rider(client, order_context, session_factory) -> None:
    offline_rider_id = await _add_rider(session_factory, 17.44, 78.35, status=RiderStatus.OFFLINE)
    order = await _ready_order(client, order_context)

    response = await client.post(
        f"/orders/{order['id']}/assign", json={"rider_id": offline_rider_id}
    )
    assert response.status_code == 400


async def test_assign_revalidates_a_rider_after_locking(
    client, order_context, session_factory, monkeypatch
) -> None:
    order = await _ready_order(client, order_context)
    async with session_factory() as session:
        rider = await session.get(Rider, order_context["rider_id"])
        assert rider is not None
        rider.capacity = 1
        rider.active_order_ids = [str(uuid4())]
        await session.commit()
        stale_candidate = Candidate(
            rider=rider,
            score=0.0,
            pickup_distance_km=0.0,
            pickup_eta_min=0.0,
            active_load=0,
            reasons=[],
        )

    async def stale_rank(*args, **kwargs):
        return [stale_candidate]

    monkeypatch.setattr(assignment_service, "_rank", stale_rank)
    response = await client.post(f"/orders/{order['id']}/assign")
    assert response.status_code == 409


async def test_unknown_order_candidates_return_404(client) -> None:
    response = await client.get(f"/orders/{uuid4()}/candidates")
    assert response.status_code == 404


async def test_marketplace_dispatch_uses_route_eta_for_nearby_riders(monkeypatch) -> None:
    restaurant = Restaurant(name="Route Kitchen", lat=17.442, lng=78.348, cuisine=[])
    near = Rider(
        id=uuid4(),
        user_id=uuid4(),
        name="Near but slow",
        lat=17.443,
        lng=78.349,
        status=RiderStatus.IDLE,
        capacity=2,
    )
    faster = Rider(
        id=uuid4(),
        user_id=uuid4(),
        name="Further but fast",
        lat=17.46,
        lng=78.36,
        status=RiderStatus.IDLE,
        capacity=2,
    )
    too_far = Rider(
        id=uuid4(),
        user_id=uuid4(),
        name="Too far",
        lat=17.62,
        lng=78.50,
        status=RiderStatus.IDLE,
        capacity=2,
    )

    class FakeRouter:
        async def matrix(self, origins, destinations):
            assert len(origins) == 2
            assert len(destinations) == 1
            return [[600.0], [60.0]]

    monkeypatch.setattr(dispatch, "get_router", lambda: FakeRouter())
    candidates = await dispatch._rank_nearby_riders(
        Order(), [near, faster, too_far], restaurant
    )

    assert [candidate.rider.name for candidate in candidates] == [
        "Further but fast",
        "Near but slow",
    ]
    assert candidates[0].pickup_eta_min == 1.0
    assert "1.0 min route ETA" in candidates[0].reasons
