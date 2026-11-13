import asyncio
import os
from decimal import Decimal
from uuid import uuid4

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.security import create_access_token
from app.config import settings
from app.db import Base, get_session
from app.domain.models import (
    Customer,
    MenuItem,
    Restaurant,
    Rider,
    RiderStatus,
    Role,
    User,
)
from app.main import app

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or str(
    make_url(settings.database_url).set(database="foodflow_test").render_as_string(
        hide_password=False
    )
)


async def _prepare_database() -> None:
    url = make_url(TEST_DATABASE_URL)
    admin = await asyncpg.connect(
        host=url.host,
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        database="postgres",
    )
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{url.database}"')
    finally:
        await admin.close()

    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    asyncio.run(_prepare_database())


@pytest.fixture
async def session_factory(database):
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    yield factory
    app.dependency_overrides.pop(get_session, None)
    await engine.dispose()


@pytest.fixture
async def client(session_factory):
    async with session_factory() as session:
        admin = User(
            name="Operations Admin",
            role=Role.ADMIN,
            email=f"admin.{uuid4().hex}@test.foodflow",
            is_active=True,
        )
        session.add(admin)
        await session.commit()
        headers = {
            "Authorization": f"Bearer {create_access_token(admin.id, admin.role.value)}"
        }

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=headers
    ) as test_client:
        yield test_client


@pytest.fixture
async def unauthenticated_client(session_factory):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


@pytest.fixture
async def order_context(session_factory):
    suffix = uuid4().hex[:8]
    async with session_factory() as session:
        customer_user = User(name=f"Customer {suffix}", role=Role.CUSTOMER)
        rider_user = User(name=f"Rider {suffix}", role=Role.RIDER)
        session.add_all([customer_user, rider_user])
        await session.flush()

        customer = Customer(
            user_id=customer_user.id,
            home_lat=17.44,
            home_lng=78.35,
            budget_pref="medium",
            diet_pref="veg",
        )
        rider = Rider(
            user_id=rider_user.id,
            name=rider_user.name,
            lat=17.441,
            lng=78.349,
            status=RiderStatus.IDLE,
        )
        restaurant = Restaurant(
            name=f"Test Kitchen {suffix}",
            lat=17.442,
            lng=78.348,
            cuisine=["test"],
            avg_prep_min=10,
            capacity_per_hr=30,
            rating=Decimal("4.4"),
        )
        session.add_all([customer, rider, restaurant])
        await session.flush()

        item = MenuItem(
            restaurant_id=restaurant.id,
            name="Test Dish",
            price=Decimal("199.00"),
            category="mains",
            veg=True,
            prep_complexity=1,
            tags=["test"],
        )
        session.add(item)
        await session.commit()

        return {
            "customer_id": str(customer.user_id),
            "rider_id": str(rider.id),
            "restaurant_id": str(restaurant.id),
            "item_id": str(item.id),
        }
