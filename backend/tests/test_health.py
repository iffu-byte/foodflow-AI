import pytest
from httpx import ASGITransport, AsyncClient

from app.api import health
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


async def test_healthz(client: AsyncClient) -> None:
    response = await client.get("/healthz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "FoodFlow AI"


async def test_readyz_ok(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def ok() -> None:
        return None

    monkeypatch.setattr(health, "_check_db", ok)
    monkeypatch.setattr(health, "_check_redis", ok)

    response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert all(check["ok"] for check in response.json()["checks"])


async def test_readyz_degraded(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def ok() -> None:
        return None

    async def fail() -> None:
        raise ConnectionError("dependency down")

    monkeypatch.setattr(health, "_check_db", ok)
    monkeypatch.setattr(health, "_check_redis", fail)

    response = await client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert any(not check["ok"] for check in response.json()["checks"])
