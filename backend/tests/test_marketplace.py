from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update

from app.auth.security import hash_password
from app.domain.models import (
    Customer,
    CustomerAddress,
    DeliveryAssignment,
    MenuItem,
    Restaurant,
    RestaurantStaff,
    Rider,
    RiderStatus,
    Role,
    User,
)
from app.marketplace import customer as customer_service
from app.marketplace import dispatch
from app.realtime import service as realtime_service


@pytest.fixture
async def market(client, session_factory):
    suffix = uuid4().hex[:8]
    password = "demo1234"
    async with session_factory() as session:
        customer_user = User(
            name=f"Market Customer {suffix}",
            role=Role.CUSTOMER,
            email=f"customer.{suffix}@example.com",
            phone="+919111100000",
            password_hash=hash_password(password),
            is_active=True,
        )
        rider_user = User(
            name=f"Market Rider {suffix}",
            role=Role.RIDER,
            email=f"rider.{suffix}@example.com",
            password_hash=hash_password(password),
            is_active=True,
        )
        manager_user = User(
            name=f"Market Manager {suffix}",
            role=Role.RESTAURANT,
            email=f"manager.{suffix}@example.com",
            password_hash=hash_password(password),
            is_active=True,
        )
        session.add_all([customer_user, rider_user, manager_user])
        await session.flush()

        customer = Customer(
            user_id=customer_user.id,
            home_lat=17.44,
            home_lng=78.35,
            budget_pref="medium",
            diet_pref=None,
        )
        rider = Rider(
            user_id=rider_user.id,
            name=rider_user.name,
            lat=17.441,
            lng=78.349,
            status=RiderStatus.IDLE,
            verification_status="APPROVED",
            last_seen_at=datetime.now(UTC),
        )
        restaurant = Restaurant(
            name=f"Market Kitchen {suffix}",
            lat=17.442,
            lng=78.348,
            cuisine=["test"],
            avg_prep_min=10,
            capacity_per_hr=30,
            rating=Decimal("4.4"),
            rating_count=10,
            address="1 Market Road",
            description="Test kitchen",
            min_order_value=Decimal("0.00"),
            delivery_fee=Decimal("29.00"),
            is_active=True,
        )
        other = Restaurant(
            name=f"Other Kitchen {suffix}",
            lat=17.443,
            lng=78.349,
            cuisine=["test"],
            avg_prep_min=12,
            capacity_per_hr=20,
            rating=Decimal("4.1"),
            min_order_value=Decimal("0.00"),
            delivery_fee=Decimal("19.00"),
            is_active=True,
        )
        session.add_all([customer, rider, restaurant, other])
        await session.flush()
        await session.execute(
            update(Rider)
            .where(Rider.id != rider.id)
            .values(status=RiderStatus.OFFLINE, last_seen_at=None)
        )
        session.add(
            RestaurantStaff(
                restaurant_id=restaurant.id,
                user_id=manager_user.id,
            )
        )
        session.add(
            CustomerAddress(
                customer_id=customer.user_id,
                label="Home",
                line1="1 Test Residency",
                city="Hyderabad",
                lat=17.44,
                lng=78.35,
                phone="+919111100000",
                is_default=True,
            )
        )
        item = MenuItem(
            restaurant_id=restaurant.id,
            name="Market Dish",
            price=Decimal("199.00"),
            category="mains",
            veg=True,
            prep_complexity=1,
            tags=["test"],
            description="Fresh test dish",
            available=True,
        )
        other_item = MenuItem(
            restaurant_id=other.id,
            name="Other Dish",
            price=Decimal("149.00"),
            category="mains",
            veg=True,
            prep_complexity=1,
            tags=["test"],
            available=True,
        )
        session.add_all([item, other_item])
        await session.commit()

        payloads = {
            "customer": {
                "email": customer_user.email,
                "password": password,
            },
            "rider": {"email": rider_user.email, "password": password},
            "manager": {"email": manager_user.email, "password": password},
        }

    tokens = {}
    for name, payload in payloads.items():
        response = await client.post("/api/v1/auth/login", json=payload)
        assert response.status_code == 200, response.text
        tokens[name] = {
            "Authorization": f"Bearer {response.json()['access_token']}"
        }
    return {
        "suffix": suffix,
        "customer": tokens["customer"],
        "rider": tokens["rider"],
        "manager": tokens["manager"],
        "rider_id": str(rider.id),
        "restaurant_id": str(restaurant.id),
        "other_restaurant_id": str(other.id),
        "item_id": str(item.id),
        "other_item_id": str(other_item.id),
    }


async def _add_item(client, market, item_id, qty=1):
    return await client.post(
        "/api/v1/cart/items",
        json={"menu_item_id": item_id, "qty": qty},
        headers=market["customer"],
    )


async def _checkout(client, market):
    return await client.post(
        "/api/v1/checkout",
        json={"payment_method": "COD"},
        headers=market["customer"],
    )


async def test_register_customer(client) -> None:
    email = f"new.{uuid4().hex[:8]}@example.com"
    payload = {
        "name": "New Customer",
        "email": email,
        "password": "demo1234",
        "phone": "+919876543210",
    }
    registered = await client.post("/api/v1/auth/register", json=payload)
    assert registered.status_code == 201, registered.text
    body = registered.json()
    assert body["user"]["role"] == "customer"
    assert body["access_token"]

    duplicate = await client.post("/api/v1/auth/register", json=payload)
    assert duplicate.status_code == 409


async def test_browse_cart_coupons_and_rbac(client, market) -> None:
    browsing = await client.get(
        "/api/v1/restaurants",
        params={"q": "Market Kitchen", "lat": 17.44, "lng": 78.35},
    )
    assert browsing.status_code == 200, browsing.text
    names = [row["name"] for row in browsing.json()]
    assert any(name.startswith("Market Kitchen") for name in names)

    menu = await client.get(f"/api/v1/restaurants/{market['restaurant_id']}/menu")
    assert menu.status_code == 200
    assert any(item["id"] == market["item_id"] for item in menu.json())

    added = await _add_item(client, market, market["item_id"], qty=1)
    assert added.status_code == 200, added.text
    assert Decimal(added.json()["subtotal"]) == Decimal("199.00")

    cross_restaurant = await _add_item(client, market, market["other_item_id"])
    assert cross_restaurant.status_code == 409

    coupon = await client.post(
        "/api/v1/cart/coupon",
        json={"code": "FEAST10"},
        headers=market["customer"],
    )
    assert coupon.status_code == 200, coupon.text
    assert Decimal(coupon.json()["discount"]) == Decimal("19.90")

    forbidden = await client.get("/api/v1/rider/me", headers=market["customer"])
    assert forbidden.status_code == 403

    anonymous = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "wrongpass"},
    )
    assert anonymous.status_code == 401


async def test_checkout_cancel_and_tracking(client, market) -> None:
    assert (await _add_item(client, market, market["item_id"], qty=2)).status_code == 200
    created = await _checkout(client, market)
    assert created.status_code == 201, created.text
    order = created.json()
    assert order["order_number"].startswith("FF-")
    assert order["payment_method"] == "COD"
    assert order["payment_status"] == "PENDING"
    assert Decimal(order["total_amount"]) == Decimal("446.90")
    order_id = order["id"]

    cart = await client.get("/api/v1/cart", headers=market["customer"])
    assert cart.json()["items"] == []

    orders = await client.get("/api/v1/orders", headers=market["customer"])
    assert orders.status_code == 200
    assert any(row["id"] == order_id for row in orders.json())
    assert all(row["can_review"] is False for row in orders.json())

    tracking = await client.get(
        f"/api/v1/orders/{order_id}/tracking", headers=market["customer"]
    )
    assert tracking.status_code == 200, tracking.text
    payload = tracking.json()
    assert payload["simulated"] is True
    assert payload["rider"] is None
    assert payload["eta_minutes"] is not None

    cancelled = await client.post(
        f"/api/v1/orders/{order_id}/cancel",
        json={"reason": "changed my mind"},
        headers=market["customer"],
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "CANCELLED"


async def test_checkout_allocates_monotonic_order_numbers(client, market) -> None:
    assert (await _add_item(client, market, market["item_id"], qty=1)).status_code == 200
    first = await _checkout(client, market)
    assert first.status_code == 201, first.text

    assert (await _add_item(client, market, market["item_id"], qty=1)).status_code == 200
    second = await _checkout(client, market)
    assert second.status_code == 201, second.text

    first_number = int(first.json()["order_number"].rsplit("-", maxsplit=1)[1])
    second_number = int(second.json()["order_number"].rsplit("-", maxsplit=1)[1])
    assert second_number == first_number + 1


async def test_expired_offer_advances_to_the_next_nearby_rider(
    client, market, session_factory
) -> None:
    async with session_factory() as session:
        next_user = User(name="Next Nearby Rider", role=Role.RIDER, is_active=True)
        session.add(next_user)
        await session.flush()
        next_rider = Rider(
            user_id=next_user.id,
            name=next_user.name,
            lat=17.444,
            lng=78.350,
            status=RiderStatus.IDLE,
            verification_status="APPROVED",
            last_seen_at=datetime.now(UTC),
        )
        session.add(next_rider)
        await session.commit()

    assert (await _add_item(client, market, market["item_id"])).status_code == 200
    created = await _checkout(client, market)
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]
    for action in ("accept", "prepare", "ready"):
        response = await client.post(
            f"/api/v1/restaurant/orders/{order_id}/{action}", headers=market["manager"]
        )
        assert response.status_code == 200, response.text

    offers = await client.get("/api/v1/rider/offers", headers=market["rider"])
    assert offers.status_code == 200, offers.text
    assignment_id = UUID(offers.json()[0]["assignment_id"])
    async with session_factory() as session:
        assignment = await session.get(DeliveryAssignment, assignment_id)
        assert assignment is not None
        assignment.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
        assert await dispatch.sweep_expired_offers(session) == 1

    expired = await client.get("/api/v1/rider/offers", headers=market["rider"])
    assert expired.status_code == 200, expired.text
    assert expired.json() == []

    async with session_factory() as session:
        assignments = list(
            (
                await session.execute(
                    select(DeliveryAssignment).where(
                        DeliveryAssignment.order_id == UUID(order_id)
                    )
                )
            )
            .scalars()
            .all()
        )
    assert {assignment.status for assignment in assignments} == {"EXPIRED", "OFFERED"}
    replacement = next(assignment for assignment in assignments if assignment.status == "OFFERED")
    assert replacement.rider_id == next_rider.id


async def test_full_delivery_lifecycle_review_and_earnings(client, market, monkeypatch) -> None:
    published: list[tuple[str, dict]] = []

    async def capture_publish(channel, message) -> None:
        published.append((channel, message))

    monkeypatch.setattr(realtime_service.bus, "publish", capture_publish)
    assert (await _add_item(client, market, market["item_id"], qty=1)).status_code == 200
    created = await _checkout(client, market)
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]

    restaurant_orders = await client.get(
        "/api/v1/restaurant/orders",
        headers=market["manager"],
    )
    assert restaurant_orders.status_code == 200, restaurant_orders.text
    listed_order = next(row for row in restaurant_orders.json() if row["id"] == order_id)
    assert listed_order["items"][0]["name"]

    for action in ("accept", "prepare", "ready"):
        response = await client.post(
            f"/api/v1/restaurant/orders/{order_id}/{action}",
            headers=market["manager"],
        )
        assert response.status_code == 200, response.text

    offers = await client.get("/api/v1/rider/offers", headers=market["rider"])
    assert offers.status_code == 200, offers.text
    mine = [offer for offer in offers.json() if offer["order_id"] == order_id]
    assert mine, offers.text
    assignment_id = mine[0]["assignment_id"]

    accepted = await client.post(
        f"/api/v1/rider/offers/{assignment_id}/accept", headers=market["rider"]
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["order"]["rider_id"] == market["rider_id"]

    published.clear()
    location = await client.post(
        "/api/v1/rider/location",
        json={
            "lat": 17.4431,
            "lng": 78.3499,
            "source": "gps",
            "accuracy_m": 6.5,
        },
        headers=market["rider"],
    )
    assert location.status_code == 200, location.text
    assert location.json()["location_source"] == "gps"
    assert location.json()["location_accuracy_m"] == 6.5
    assert [channel for channel, _ in published] == [
        realtime_service.order_channel(UUID(order_id)),
        realtime_service.restaurant_channel(UUID(market["restaurant_id"])),
    ]
    assert all(message["type"] == "rider_location" for _, message in published)
    assert published[1][1]["rider"]["location_source"] == "gps"

    route = await client.get(
        f"/api/v1/orders/{order_id}/route", headers=market["customer"]
    )
    assert route.status_code == 200, route.text
    route_payload = route.json()
    assert route_payload["phase"] == "to_pickup"
    assert route_payload["routing_provider"] == "haversine"
    assert route_payload["is_estimated"] is True
    assert route_payload["points"][0]["lat"] == 17.4431
    assert route_payload["points"][-1]["lat"] == 17.442

    live_tracking = await client.get(
        f"/api/v1/orders/{order_id}/tracking", headers=market["customer"]
    )
    assert live_tracking.status_code == 200, live_tracking.text
    live_payload = live_tracking.json()
    assert live_payload["simulated"] is False
    assert live_payload["rider"]["location_source"] == "gps"
    assert live_payload["rider"]["location_accuracy_m"] == 6.5
    assert live_payload["points"][-1]["lat"] == 17.4431

    rider_tracking = await client.get(
        f"/api/v1/orders/{order_id}/tracking", headers=market["rider"]
    )
    assert rider_tracking.status_code == 200, rider_tracking.text
    assert rider_tracking.json()["rider"]["id"] == market["rider_id"]

    for action in ("arrived-restaurant", "pickup", "arrived-customer", "complete"):
        response = await client.post(
            f"/api/v1/rider/assignments/{assignment_id}/{action}",
            headers=market["rider"],
        )
        assert response.status_code == 200, response.text

    delivered = await client.get(
        f"/api/v1/orders/{order_id}", headers=market["customer"]
    )
    assert delivered.json()["status"] == "DELIVERED"
    assert delivered.json()["payment_status"] == "PAID"
    assert delivered.json()["can_review"] is True

    earnings = await client.get("/api/v1/rider/earnings", headers=market["rider"])
    assert earnings.status_code == 200
    assert any(entry["order_id"] == order_id for entry in earnings.json()["entries"])

    review = await client.post(
        f"/api/v1/orders/{order_id}/review",
        json={"restaurant_rating": 5, "rider_rating": 5, "comment": "Great"},
        headers=market["customer"],
    )
    assert review.status_code == 201, review.text

    duplicate = await client.post(
        f"/api/v1/orders/{order_id}/review",
        json={"restaurant_rating": 4},
        headers=market["customer"],
    )
    assert duplicate.status_code == 409

    analytics = await client.get(
        "/api/v1/restaurant/analytics", headers=market["manager"]
    )
    assert analytics.status_code == 200
    assert analytics.json()["completed_today"] >= 1

    notifications = await client.get(
        "/api/v1/notifications", headers=market["customer"]
    )
    assert notifications.status_code == 200
    assert len(notifications.json()) >= 3


async def test_restaurant_rejects_order(client, market) -> None:
    assert (await _add_item(client, market, market["item_id"], qty=1)).status_code == 200
    created = await _checkout(client, market)
    order_id = created.json()["id"]

    rejected = await client.post(
        f"/api/v1/restaurant/orders/{order_id}/reject",
        json={"reason": "kitchen is closed"},
        headers=market["manager"],
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "CANCELLED"

    accept_again = await client.post(
        f"/api/v1/restaurant/orders/{order_id}/accept",
        headers=market["manager"],
    )
    assert accept_again.status_code == 409


async def test_customer_cancel_clears_rider_assignment(client, market) -> None:
    assert (await _add_item(client, market, market["item_id"], qty=1)).status_code == 200
    created = await _checkout(client, market)
    order_id = created.json()["id"]

    for action in ("accept", "prepare", "ready"):
        response = await client.post(
            f"/api/v1/restaurant/orders/{order_id}/{action}",
            headers=market["manager"],
        )
        assert response.status_code == 200, response.text

    offers = await client.get("/api/v1/rider/offers", headers=market["rider"])
    mine = [offer for offer in offers.json() if offer["order_id"] == order_id]
    assert mine, offers.text
    accepted = await client.post(
        f"/api/v1/rider/offers/{mine[0]['assignment_id']}/accept",
        headers=market["rider"],
    )
    assert accepted.status_code == 200, accepted.text
    active = await client.get("/api/v1/rider/deliveries/active", headers=market["rider"])
    assert active.status_code == 200
    assert active.json()["order"]["id"] == order_id

    cancelled = await client.post(
        f"/api/v1/orders/{order_id}/cancel",
        json={"reason": "plans changed"},
        headers=market["customer"],
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "CANCELLED"

    active_after = await client.get(
        "/api/v1/rider/deliveries/active", headers=market["rider"]
    )
    assert active_after.status_code == 200
    assert active_after.json() is None
    profile = await client.get("/api/v1/rider/me", headers=market["rider"])
    assert profile.json()["status"] == "idle"


async def test_rider_cannot_accept_an_offer_after_reaching_capacity(
    client, market, session_factory
) -> None:
    assert (await _add_item(client, market, market["item_id"], qty=1)).status_code == 200
    created = await _checkout(client, market)
    order_id = created.json()["id"]
    for action in ("accept", "prepare", "ready"):
        response = await client.post(
            f"/api/v1/restaurant/orders/{order_id}/{action}", headers=market["manager"]
        )
        assert response.status_code == 200, response.text

    offers = await client.get("/api/v1/rider/offers", headers=market["rider"])
    offer = next(item for item in offers.json() if item["order_id"] == order_id)
    async with session_factory() as session:
        rider = await session.get(Rider, UUID(market["rider_id"]))
        assert rider is not None
        rider.capacity = 1
        rider.active_order_ids = [str(uuid4())]
        await session.commit()

    accepted = await client.post(
        f"/api/v1/rider/offers/{offer['assignment_id']}/accept", headers=market["rider"]
    )
    assert accepted.status_code == 409


async def test_customer_cancellation_rolls_back_when_cleanup_fails(
    client, market, monkeypatch
) -> None:
    assert (await _add_item(client, market, market["item_id"], qty=1)).status_code == 200
    created = await _checkout(client, market)
    order_id = created.json()["id"]

    async def fail_notification(*args, **kwargs):
        raise RuntimeError("notification persistence failed")

    monkeypatch.setattr(customer_service.notifications, "add", fail_notification)
    with pytest.raises(RuntimeError, match="notification persistence failed"):
        await client.post(
            f"/api/v1/orders/{order_id}/cancel",
            headers=market["customer"],
        )

    stored = await client.get(
        f"/api/v1/orders/{order_id}", headers=market["customer"]
    )
    assert stored.status_code == 200
    assert stored.json()["status"] == "PLACED"
