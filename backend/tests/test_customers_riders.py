from uuid import uuid4


async def test_customers_listing(client, order_context) -> None:
    response = await client.get("/customers")
    assert response.status_code == 200, response.text

    customers = response.json()
    match = next(
        (row for row in customers if row["id"] == order_context["customer_id"]), None
    )
    assert match is not None
    assert match["name"].startswith("Customer ")
    assert match["home_lat"] == 17.44
    assert match["home_lng"] == 78.35
    assert match["budget_pref"] == "medium"
    assert match["diet_pref"] == "veg"


async def test_riders_listing_and_location_update(client, order_context) -> None:
    response = await client.get("/riders")
    assert response.status_code == 200, response.text

    riders = response.json()
    match = next((row for row in riders if row["id"] == order_context["rider_id"]), None)
    assert match is not None
    assert match["status"] == "idle"
    assert match["lat"] == 17.441
    assert match["lng"] == 78.349
    assert match["last_seen_at"] is None

    updated = await client.post(
        f"/riders/{order_context['rider_id']}/location",
        json={"lat": 17.4501, "lng": 78.3611},
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["lat"] == 17.4501
    assert body["lng"] == 78.3611
    assert body["last_seen_at"] is not None

    listing = await client.get("/riders")
    match = next(
        row for row in listing.json() if row["id"] == order_context["rider_id"]
    )
    assert match["lat"] == 17.4501


async def test_rider_location_validation(client, order_context) -> None:
    missing = await client.post(
        f"/riders/{uuid4()}/location", json={"lat": 17.4, "lng": 78.3}
    )
    assert missing.status_code == 404

    invalid = await client.post(
        f"/riders/{order_context['rider_id']}/location",
        json={"lat": 120.0, "lng": 78.3},
    )
    assert invalid.status_code == 422
