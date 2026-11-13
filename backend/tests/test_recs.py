from decimal import Decimal
from uuid import UUID, uuid4

from app.domain.models import MenuItem, Restaurant
from app.recs import service as recs_service


async def test_restaurant_recommendations_include_reasons(
    client, session_factory, order_context
) -> None:
    customer_id = order_context["customer_id"]
    restaurant_id = order_context["restaurant_id"]

    async with session_factory() as session:
        restaurant = await session.get(Restaurant, restaurant_id)
        restaurant.rating = Decimal("4.9")
        await session.commit()

    response = await client.get(f"/recommendations/restaurants/{customer_id}")
    assert response.status_code == 200, response.text
    assert len(response.json()) <= 8

    async with session_factory() as session:
        picks = await recs_service.recommend_restaurants(
            session, UUID(customer_id), limit=500
        )
    match = next(pick for pick in picks if str(pick.restaurant.id) == restaurant_id)
    assert 0.0 <= match.score <= 1.0
    assert match.distance_km < 1.0
    assert match.reasons
    assert any("vegetarian-friendly" in reason for reason in match.reasons)
    assert any("medium budget" in reason for reason in match.reasons)


async def test_menu_recommendations_respect_vegetarian_preference(
    client, session_factory, order_context
) -> None:
    customer_id = order_context["customer_id"]
    restaurant_id = order_context["restaurant_id"]

    async with session_factory() as session:
        session.add(
            MenuItem(
                restaurant_id=restaurant_id,
                name="Chicken Special",
                price=Decimal("299.00"),
                category="mains",
                veg=False,
                prep_complexity=3,
                tags=["test"],
            )
        )
        await session.commit()

    response = await client.get(
        f"/recommendations/menu/{customer_id}/{restaurant_id}"
    )
    assert response.status_code == 200, response.text
    recs = response.json()
    names = [rec["item"]["name"] for rec in recs]
    assert "Test Dish" in names
    assert "Chicken Special" not in names

    dish = next(rec for rec in recs if rec["item"]["name"] == "Test Dish")
    assert "vegetarian" in dish["reasons"]
    assert any("medium budget" in reason for reason in dish["reasons"])
    assert any("quick to prepare" in reason for reason in dish["reasons"])


async def test_recommendations_use_location_override(client, order_context) -> None:
    customer_id = order_context["customer_id"]
    response = await client.get(
        f"/recommendations/restaurants/{customer_id}",
        params={"lat": 17.50, "lng": 78.35},
    )
    assert response.status_code == 200, response.text
    recs = response.json()
    assert recs
    assert all(rec["distance_km"] > 5 for rec in recs)

    invalid = await client.get(
        f"/recommendations/restaurants/{customer_id}", params={"lat": 17.50}
    )
    assert invalid.status_code == 422


async def test_recommendations_unknown_ids(client, order_context) -> None:
    customer_id = order_context["customer_id"]
    restaurant_id = order_context["restaurant_id"]
    missing = uuid4()

    assert (
        await client.get(f"/recommendations/restaurants/{missing}")
    ).status_code == 404
    assert (
        await client.get(f"/recommendations/menu/{missing}/{restaurant_id}")
    ).status_code == 404
    assert (
        await client.get(f"/recommendations/menu/{customer_id}/{missing}")
    ).status_code == 404
