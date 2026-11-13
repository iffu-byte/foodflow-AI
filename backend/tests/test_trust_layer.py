"""Tests for the trust layer: delivery proof, portions, nutrition, rescue,
kitchen trust, shared rides and fair-delay accounting."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update

from app.auth.security import hash_password
from app.batching.service import plan_route
from app.domain.models import (
    Customer,
    CustomerAddress,
    MenuItem,
    Order,
    RescueListing,
    Restaurant,
    RestaurantStaff,
    Rider,
    RiderStatus,
    Role,
    User,
)
from app.honesty.service import attribute, compensation_for
from app.nutrition.service import local_estimate, match_dish, portion_view
from app.portion import estimator
from app.rescue.service import price_at
from app.trust import fssai
from app.trust.score import TrustInputs, compute
from app.trust.service import sibling_map

PASSWORD = "demo1234"


# --- Pure logic ---------------------------------------------------------------


def test_photo_estimate_scales_with_reference_and_reports_a_range() -> None:
    # A 25.4 cm plate spanning 900 px; food mound 16 cm across.
    px_per_cm = 900 / 25.4
    result = estimator.from_photo(
        reference="plate_10in",
        reference_px=900,
        food_rx_px=8 * px_per_cm,
        food_ry_px=8 * px_per_cm,
        profile="rice",
    )
    assert 300 <= result.grams <= 420
    assert result.low_grams < result.grams < result.high_grams
    assert result.method == "photo_reference"
    # The same footprint measured with a tiny reference is less certain.
    coarse = estimator.from_photo(
        reference="coin_10", reference_px=12, food_rx_px=36, food_ry_px=36, profile="rice"
    )
    assert coarse.confidence < result.confidence


def test_photo_estimate_requires_marks() -> None:
    with pytest.raises(ValueError):
        estimator.from_photo(
            reference="coin_10", reference_px=0, food_rx_px=10, food_ry_px=10, profile="rice"
        )


def test_container_scale_and_pieces_methods() -> None:
    box = estimator.from_container(capacity_ml=750, fill_fraction=0.8, profile="rice")
    assert 250 <= box.grams <= 400
    assert estimator.from_scale(grams=412, profile="rice").grams == 412
    naan = estimator.from_pieces(name="Garlic Naan", pieces=2)
    assert naan.grams == 180


def test_ai_cross_check_moves_confidence() -> None:
    local = estimator.from_scale(grams=400, profile="rice")
    agree, note = estimator.cross_check(local, 420)
    disagree, _ = estimator.cross_check(local, 900)
    assert agree >= local.confidence - 0.01 and disagree < local.confidence
    assert note and "within" in note


def test_nutrition_matches_specific_dish_and_scales_with_grams() -> None:
    dish, _ = match_dish("Hyderabadi Chicken Biryani")
    assert dish is not None and "chicken biryani" in dish.keys
    item = MenuItem(
        name="Chicken Biryani", category="rice", tags=["biryani"], description="", ingredients=[]
    )
    item.nutrition = local_estimate(item)
    item.portion_grams = None
    item.portion_method = "unknown"
    typical = portion_view(item)
    item.portion_grams = 200
    item.portion_method = "scale"
    measured = portion_view(item)
    assert typical["grams_source"] == "typical"
    assert measured["grams_source"] == "measured"
    assert measured["kcal"] == round(item.nutrition["per100g"]["kcal"] * 2)
    assert "dairy" in measured["allergens"]


def test_rescue_price_falls_linearly_to_floor() -> None:
    start = datetime.now(UTC) - timedelta(minutes=30)
    listing = RescueListing(
        start_price=Decimal("200"),
        floor_price=Decimal("100"),
        original_price=Decimal("300"),
        starts_at=start,
        ends_at=start + timedelta(minutes=60),
        qty_left=3,
        status="LIVE",
    )
    assert price_at(listing, start) == Decimal("200")
    assert price_at(listing, start + timedelta(minutes=30)) == Decimal("150")
    assert price_at(listing, start + timedelta(minutes=90)) == Decimal("100")


def test_fssai_format_check() -> None:
    assert fssai.check("13619000100000")["status"] == "format_ok"
    assert fssai.check("1361900010000")["status"] == "invalid"
    assert fssai.check(None)["status"] == "missing"
    yesterday = datetime.now(UTC).date() - timedelta(days=1)
    assert fssai.check("13619000100000", yesterday)["status"] == "expired"


def test_trust_score_flags_undisclosed_shared_kitchen() -> None:
    base = dict(
        fssai_status="format_ok",
        location_verdict="verified",
        kitchen_photo_age_days=3,
        menu_items=4,
        items_with_portion=4,
        items_portion_verified=2,
        quantity_ok=5,
        quantity_short=0,
    )
    honest = compute(TrustInputs(**base, sibling_brands=["Wrap Co"], kitchen_type="cloud_kitchen"))
    hidden = compute(TrustInputs(**base, sibling_brands=["Wrap Co"], kitchen_type="dine_in"))
    assert honest["score"] - hidden["score"] == 10
    assert "Undisclosed shared kitchen" in hidden["warnings"]
    assert honest["grade"] == "A"


def test_sibling_map_finds_brands_within_30_metres() -> None:
    a = Restaurant(id=uuid4(), name="A", lat=17.44, lng=78.35, google_place_id=None)
    b = Restaurant(id=uuid4(), name="B", lat=17.44004, lng=78.35002, google_place_id=None)
    c = Restaurant(id=uuid4(), name="C", lat=17.45, lng=78.36, google_place_id=None)
    siblings = sibling_map([a, b, c])
    assert siblings[a.id] == ["B"] and siblings[c.id] == []


def test_shared_route_plan_saves_distance() -> None:
    first, batched, separate, extra = plan_route((17.44, 78.35), (17.45, 78.35), (17.452, 78.351))
    assert batched < separate
    assert extra < 12


def test_delay_attribution_credits_platform_delays_only() -> None:
    placed = datetime.now(UTC) - timedelta(minutes=90)
    order = SimpleNamespace(
        estimated_prep_min=10,
        delivery_distance_km=2.0,
        promised_eta_at=placed + timedelta(minutes=40),
        total_price=Decimal("500.00"),
    )
    marks = {
        "placed": placed,
        "accepted": placed + timedelta(minutes=2),
        "ready": placed + timedelta(minutes=12),
        "rider_assigned": placed + timedelta(minutes=45),
        "picked_up": placed + timedelta(minutes=52),
        "delivered": placed + timedelta(minutes=62),
    }
    result = attribute(order, marks, est_pickup_min=4)
    assert result["over_by_owner"]["platform"] > 25
    assert result["over_by_owner"]["restaurant"] == 0
    amount, message = compensation_for(order, result)
    assert amount == Decimal("50") and "credited" in message

    kitchen_marks = dict(marks)
    kitchen_marks["ready"] = placed + timedelta(minutes=44)
    kitchen_marks["rider_assigned"] = placed + timedelta(minutes=45)
    kitchen = attribute(order, kitchen_marks, est_pickup_min=4)
    amount, message = compensation_for(order, kitchen)
    assert amount == 0 and "kitchen" in message


# --- API flows ---------------------------------------------------------------


@pytest.fixture
async def world(client, session_factory):
    suffix = uuid4().hex[:8]
    async with session_factory() as session:
        users = {
            name: User(
                name=f"{name.title()} {suffix}",
                role=role,
                email=f"{name}.{suffix}@test.foodflow",
                phone="+919100000000",
                password_hash=hash_password(PASSWORD),
                is_active=True,
            )
            for name, role in (
                ("asha", Role.CUSTOMER),
                ("ravi", Role.CUSTOMER),
                ("rider", Role.RIDER),
                ("manager", Role.RESTAURANT),
            )
        }
        session.add_all(users.values())
        await session.flush()
        for name, lat, lng in (("asha", 17.4400, 78.3500), ("ravi", 17.4410, 78.3512)):
            session.add(
                Customer(user_id=users[name].id, home_lat=lat, home_lng=lng)
            )
            session.add(
                CustomerAddress(
                    customer_id=users[name].id,
                    line1=f"{name} home",
                    lat=lat,
                    lng=lng,
                    phone="+919100000001",
                    is_default=True,
                )
            )
        rider = Rider(
            user_id=users["rider"].id,
            name=users["rider"].name,
            lat=17.4418,
            lng=78.3482,
            status=RiderStatus.IDLE,
            verification_status="APPROVED",
            last_seen_at=datetime.now(UTC),
            capacity=2,
        )
        restaurant = Restaurant(
            name=f"Trust Kitchen {suffix}",
            lat=17.442,
            lng=78.348,
            cuisine=["biryani"],
            avg_prep_min=10,
            capacity_per_hr=30,
            rating=Decimal("4.4"),
            min_order_value=Decimal("0.00"),
            delivery_fee=Decimal("29.00"),
            is_active=True,
        )
        session.add_all([rider, restaurant])
        await session.flush()
        await session.execute(
            update(Rider)
            .where(Rider.id != rider.id)
            .values(status=RiderStatus.OFFLINE, last_seen_at=None)
        )
        session.add(RestaurantStaff(restaurant_id=restaurant.id, user_id=users["manager"].id))
        biryani = MenuItem(
            restaurant_id=restaurant.id,
            name="Chicken Biryani",
            price=Decimal("300.00"),
            category="rice",
            veg=False,
            prep_complexity=2,
            tags=["biryani"],
            available=True,
        )
        session.add(biryani)
        await session.commit()

    headers = {}
    for name in ("asha", "ravi", "rider", "manager"):
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": f"{name}.{suffix}@test.foodflow", "password": PASSWORD},
        )
        assert response.status_code == 200, response.text
        headers[name] = {"Authorization": f"Bearer {response.json()['access_token']}"}
    return {
        **headers,
        "rider_id": str(rider.id),
        "restaurant_id": str(restaurant.id),
        "item_id": str(biryani.id),
    }


async def _place(client, world, who: str, mode: str = "solo") -> dict:
    added = await client.post(
        "/api/v1/cart/items", json={"menu_item_id": world["item_id"]}, headers=world[who]
    )
    assert added.status_code == 200, added.text
    placed = await client.post(
        "/api/v1/checkout",
        json={"payment_method": "COD", "delivery_mode": mode},
        headers=world[who],
    )
    assert placed.status_code == 201, placed.text
    return placed.json()


async def _ready(client, world, order_id: str) -> None:
    for action in ("accept", "prepare", "ready"):
        response = await client.post(
            f"/api/v1/restaurant/orders/{order_id}/{action}", headers=world["manager"]
        )
        assert response.status_code == 200, response.text


async def _accept_offer(client, world, order_id: str) -> str:
    offers = (await client.get("/api/v1/rider/offers", headers=world["rider"])).json()
    mine = [offer for offer in offers if offer["order_id"] == order_id]
    assert mine, offers
    accepted = await client.post(
        f"/api/v1/rider/offers/{mine[0]['assignment_id']}/accept", headers=world["rider"]
    )
    assert accepted.status_code == 200, accepted.text
    return mine[0]["assignment_id"]


async def _move(client, world, lat: float, lng: float) -> None:
    moved = await client.post(
        "/api/v1/rider/location",
        json={"lat": lat, "lng": lng, "source": "gps", "accuracy_m": 5},
        headers=world["rider"],
    )
    assert moved.status_code == 200, moved.text


async def test_otp_and_geofence_gate_delivery(client, world) -> None:
    order = await _place(client, world, "asha")
    assert order["delivery_otp"] and len(order["delivery_otp"]) == 4
    await _ready(client, world, order["id"])
    assignment = await _accept_offer(client, world, order["id"])

    rider_view = await client.get("/api/v1/rider/deliveries/active", headers=world["rider"])
    assert rider_view.json()["order"]["delivery_otp"] is None

    for action in ("arrived-restaurant", "pickup"):
        response = await client.post(
            f"/api/v1/rider/assignments/{assignment}/{action}", headers=world["rider"]
        )
        assert response.status_code == 200, response.text

    # About 1 km short of the pin: arrival is refused.
    await _move(client, world, 17.449, 78.350)
    far = await client.post(
        f"/api/v1/rider/assignments/{assignment}/arrived-customer", headers=world["rider"]
    )
    assert far.status_code == 409 and "m from the drop pin" in far.json()["detail"]

    await _move(client, world, 17.4401, 78.3501)
    arrived = await client.post(
        f"/api/v1/rider/assignments/{assignment}/arrived-customer", headers=world["rider"]
    )
    assert arrived.status_code == 200, arrived.text

    wrong = "0000" if order["delivery_otp"] != "0000" else "1111"
    rejected = await client.post(
        f"/api/v1/rider/assignments/{assignment}/complete",
        json={"otp": wrong},
        headers=world["rider"],
    )
    assert rejected.status_code == 409 and "attempts left" in rejected.json()["detail"]

    done = await client.post(
        f"/api/v1/rider/assignments/{assignment}/complete",
        json={"otp": order["delivery_otp"]},
        headers=world["rider"],
    )
    assert done.status_code == 200, done.text
    detail = (await client.get(f"/api/v1/orders/{order['id']}", headers=world["asha"])).json()
    assert detail["status"] == "DELIVERED"
    assert detail["delivery_proof"]["method"] == "otp_geofence"
    assert detail["delivery_proof"]["distance_m"] < 50
    assert detail["otp_attempts"] == 1

    dispute = await client.post(
        f"/api/v1/orders/{order['id']}/not-received", json={}, headers=world["asha"]
    )
    assert dispute.status_code == 200 and dispute.json()["verdict"] == "proof_on_file"

    status = await client.get(f"/api/v1/orders/{order['id']}/honest-status", headers=world["asha"])
    assert status.status_code == 200 and status.json()["headline"] == "Delivered"


async def test_shared_orders_ride_together(client, world, session_factory) -> None:
    first = await _place(client, world, "asha", "shared")
    second = await _place(client, world, "ravi", "shared")
    assert Decimal(first["shared_saving"]) == Decimal("15.00")
    assert Decimal(first["delivery_fee"]) == Decimal("14.00")

    await _ready(client, world, first["id"])
    first_assignment = await _accept_offer(client, world, first["id"])
    await _ready(client, world, second["id"])

    offers = (await client.get("/api/v1/rider/offers", headers=world["rider"])).json()
    batched = [offer for offer in offers if offer["order_id"] == second["id"]]
    assert batched and batched[0]["batched_with"] == first["order_number"]
    accepted = await client.post(
        f"/api/v1/rider/offers/{batched[0]['assignment_id']}/accept", headers=world["rider"]
    )
    assert accepted.status_code == 200, accepted.text
    assert len(accepted.json()["batch"]) == 2

    async with session_factory() as session:
        rows = (
            await session.execute(
                select(Order).where(Order.id.in_([UUID(first["id"]), UUID(second["id"])]))
            )
        ).scalars().all()
        assert len({row.batch_id for row in rows}) == 1
        assert sorted(row.batch_sequence for row in rows) == [1, 2]

    # One arrival and one pickup move both bags.
    for action in ("arrived-restaurant", "pickup"):
        response = await client.post(
            f"/api/v1/rider/assignments/{first_assignment}/{action}", headers=world["rider"]
        )
        assert response.status_code == 200, response.text
    for order in (first, second):
        detail = (
            await client.get(f"/api/v1/orders/{order['id']}", headers=world["asha"])
            if order is first
            else await client.get(f"/api/v1/orders/{order['id']}", headers=world["ravi"])
        ).json()
        assert detail["status"] == "PICKED_UP"


async def test_portion_studio_publishes_measured_portion(client, world) -> None:
    config = await client.get("/api/v1/restaurant/portion/config", headers=world["manager"])
    assert config.status_code == 200 and config.json()["profiles"]

    estimate = await client.post(
        f"/api/v1/restaurant/menu/{world['item_id']}/portion/estimate",
        json={"method": "container", "capacity_ml": 750, "fill_fraction": 0.9, "profile": "rice"},
        headers=world["manager"],
    )
    assert estimate.status_code == 200, estimate.text
    body = estimate.json()
    assert body["method"] == "container" and body["grams"] > 0

    published = await client.post(
        f"/api/v1/restaurant/menu/{world['item_id']}/portion",
        json={
            "method": "container",
            "grams": body["grams"],
            "serves": body["serves"],
            "confidence": body["confidence"],
        },
        headers=world["manager"],
    )
    assert published.status_code == 200, published.text
    item = published.json()
    assert item["portion_grams"] == body["grams"]
    assert item["nutrition"]["grams_source"] == "measured"

    menu = await client.get(f"/api/v1/restaurants/{world['restaurant_id']}/menu")
    dish = next(row for row in menu.json() if row["id"] == world["item_id"])
    assert dish["portion_method"] == "container"
    assert dish["nutrition"]["kcal"] > 0


async def test_rescue_listing_prices_cart_and_checkout(client, world, session_factory) -> None:
    prep = await client.post(
        "/api/v1/restaurant/rescue/prep",
        json={"menu_item_id": world["item_id"], "prepared_qty": 10},
        headers=world["manager"],
    )
    assert prep.status_code == 200, prep.text
    row = next(r for r in prep.json()["items"] if r["menu_item_id"] == world["item_id"])
    assert row["prepared"] == 10

    created = await client.post(
        "/api/v1/restaurant/rescue/listings",
        json={
            "menu_item_id": world["item_id"],
            "qty": 2,
            "start_price": "180",
            "floor_price": "120",
            "duration_min": 60,
        },
        headers=world["manager"],
    )
    assert created.status_code == 201, created.text
    listing = created.json()

    live = await client.get("/api/v1/rescue/live", params={"lat": 17.44, "lng": 78.35})
    assert any(row["id"] == listing["id"] for row in live.json())

    cart = await client.post(
        "/api/v1/cart/items",
        json={"menu_item_id": world["item_id"], "qty": 5, "rescue_listing_id": listing["id"]},
        headers=world["asha"],
    )
    assert cart.status_code == 200, cart.text
    line = cart.json()["items"][0]
    assert line["qty"] == 2  # capped at what is left
    assert Decimal(line["price"]) <= Decimal("180")
    assert Decimal(cart.json()["rescue_saving"]) >= Decimal("240")
    assert cart.json()["nutrition"]["kcal"] > 0

    placed = await client.post(
        "/api/v1/checkout", json={"payment_method": "COD"}, headers=world["asha"]
    )
    assert placed.status_code == 201, placed.text
    assert Decimal(placed.json()["items"][0]["unit_price"]) <= Decimal("180")
    async with session_factory() as session:
        stored = await session.get(RescueListing, UUID(listing["id"]))
        assert stored.qty_left == 0 and stored.status == "SOLD_OUT"

    intake = await client.get("/api/v1/me/nutrition/today", headers=world["asha"])
    assert intake.status_code == 200 and intake.json()["totals"]["kcal"] > 0


async def test_trust_profile_and_ai_meter(client, world, monkeypatch) -> None:
    from app.trust import places

    async def fake_osm(name, lat, lng):
        return {
            "food_places_at_pin": [
                {"name": name, "amenity": "restaurant", "distance_m": 12.0,
                 "name_similarity": 1.0, "source": "test"}
            ],
            "object_at_pin": {"category": "amenity", "type": "restaurant", "name": name},
            "address": "Test address",
        }

    monkeypatch.setattr(places, "osm_check", fake_osm)
    patched = await client.patch(
        "/api/v1/restaurant/trust",
        json={"fssai_license": "13619000100000", "kitchen_type": "dine_in"},
        headers=world["manager"],
    )
    assert patched.status_code == 200, patched.text
    profile = await client.get(f"/api/v1/restaurants/{world['restaurant_id']}/trust")
    body = profile.json()
    assert body["reality"]["verdict"] == "osm_match"
    assert "Real kitchen verified" in body["badges"]
    assert body["fssai"]["status"] == "format_ok"

    # A second view is served from the cached snapshot.
    again = await client.get(f"/api/v1/restaurants/{world['restaurant_id']}/trust")
    assert again.status_code == 200

    usage = await client.get("/api/v1/ai/usage")
    assert usage.status_code == 200
    assert usage.json()["cache_hits"] >= 1
