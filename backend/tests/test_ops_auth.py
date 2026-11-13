from uuid import UUID, uuid4

import pytest

from app.auth.security import create_access_token
from app.config import Settings
from app.domain.models import Role, User


@pytest.mark.parametrize(
    "path",
    [
        "/orders",
        "/customers",
        "/riders",
        "/monitor/summary",
        "/learning/models",
        f"/orders/{uuid4()}/candidates",
    ],
)
async def test_operations_routes_require_authentication(unauthenticated_client, path) -> None:
    response = await unauthenticated_client.get(path)
    assert response.status_code == 401


async def test_operations_routes_require_an_admin(client, session_factory) -> None:
    async with session_factory() as session:
        customer = User(
            name="Customer",
            role=Role.CUSTOMER,
            email=f"customer.{uuid4().hex}@test.foodflow",
            is_active=True,
        )
        session.add(customer)
        await session.commit()

    response = await client.get(
        "/orders",
        headers={
            "Authorization": f"Bearer {create_access_token(customer.id, customer.role.value)}"
        },
    )
    assert response.status_code == 403


async def test_recommendations_are_limited_to_the_customer_or_admin(
    client, unauthenticated_client, order_context, session_factory
) -> None:
    customer_id = UUID(order_context["customer_id"])
    async with session_factory() as session:
        customer = await session.get(User, customer_id)
        assert customer is not None
        customer_headers = {
            "Authorization": f"Bearer {create_access_token(customer.id, customer.role.value)}"
        }

    path = f"/recommendations/restaurants/{customer_id}"
    assert (await unauthenticated_client.get(path)).status_code == 401
    assert (await client.get(path, headers=customer_headers)).status_code == 200
    assert (
        await client.get(
            f"/recommendations/restaurants/{uuid4()}", headers=customer_headers
        )
    ).status_code == 403


def test_non_development_settings_require_auth_secret() -> None:
    with pytest.raises(ValueError, match="AUTH_SECRET"):
        Settings(env="demo", auth_secret="")
