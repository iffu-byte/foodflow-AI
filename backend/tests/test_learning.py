from pathlib import Path

from app.config import settings
from app.domain.models import TrainingRow
from app.eta.features import FEATURE_NAMES


def _features(index: int) -> dict:
    data = {name: 1.0 for name in FEATURE_NAMES}
    data.update(
        {
            "distance_km": 1.0 + index * 0.1,
            "routed_distance_km": 1.3 + index * 0.1,
            "free_flow_drive_min": 3.0 + index * 0.2,
            "hour_of_day": 12 + index % 8,
            "day_of_week": index % 7,
            "is_weekend": float(index % 7 >= 5),
            "item_count": 1 + index % 4,
            "distinct_items": 1 + index % 3,
            "avg_prep_complexity": 1 + index % 3,
            "max_prep_complexity": 1 + index % 3,
            "veg_share": 0.5,
            "total_price": 150 + index * 5,
            "restaurant_avg_prep_min": 12,
            "restaurant_capacity_per_hr": 30,
            "kitchen_load": 0.2,
            "rain_intensity": 0.0,
            "traffic_multiplier": 1.0,
            "zone_factor": 1.0,
        }
    )
    return data


async def _insert_rows(session_factory, count: int = 40) -> None:
    async with session_factory() as session:
        for index in range(count):
            prep = 10.0 + index % 5
            drive = 5.0 + (index % 4) * 0.5
            session.add(
                TrainingRow(
                    features_json=_features(index),
                    actual_prep_min=prep,
                    actual_drive_min=drive,
                    actual_total_min=prep + drive,
                    source="test",
                )
            )
        await session.commit()


async def test_retrain_requires_enough_rows(
    client, session_factory, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "eta_model_path", str(tmp_path / "eta_model.joblib"))
    response = await client.post("/learning/retrain", json={"min_rows": 100_000})
    assert response.status_code == 400
    assert "usable training rows" in response.json()["detail"]


async def test_retrain_promotes_then_keeps_regressions_out(
    client, session_factory, tmp_path, monkeypatch
) -> None:
    model_path = tmp_path / "eta_model.joblib"
    monkeypatch.setattr(settings, "eta_model_path", str(model_path))
    await _insert_rows(session_factory)

    first = await client.post("/learning/retrain", json={"min_rows": 20})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["promoted"] is True
    assert body["improved"] is True
    assert body["active_version"] == body["version"]
    assert body["metrics"]["total_mae"] >= 0
    assert Path(model_path).exists()

    models = (await client.get("/learning/models")).json()
    active = [model for model in models if model["is_active"]]
    assert len(active) == 1
    assert active[0]["version"] == body["version"]

    second = await client.post("/learning/retrain", json={"min_rows": 20})
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["promoted"] is False
    assert second_body["improved"] is False
    assert second_body["active_version"] == body["version"]

    models = (await client.get("/learning/models")).json()
    active = [model for model in models if model["is_active"]]
    assert len(active) == 1
    assert active[0]["version"] == body["version"]
    assert len(models) == 2

    forced = await client.post(
        "/learning/retrain", json={"min_rows": 20, "force": True}
    )
    assert forced.status_code == 200, forced.text
    forced_body = forced.json()
    assert forced_body["promoted"] is True
    assert forced_body["active_version"] == forced_body["version"]

    models = (await client.get("/learning/models")).json()
    active = [model for model in models if model["is_active"]]
    assert len(active) == 1
    assert active[0]["version"] == forced_body["version"]
    assert len(models) == 3
