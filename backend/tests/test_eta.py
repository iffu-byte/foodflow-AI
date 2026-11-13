from datetime import UTC, datetime, timedelta
from uuid import uuid4

import joblib
from sklearn.dummy import DummyRegressor

from app.config import settings
from app.eta import engine as eta_engine
from app.eta.fallback import fallback_eta
from app.eta.features import FEATURE_NAMES, ItemFeature, build_feature_dict
from app.eta.model import EtaEngine


def _features() -> dict[str, float]:
    return build_feature_dict(
        restaurant_avg_prep_min=15,
        restaurant_capacity_per_hr=40,
        restaurant_lat=17.442,
        restaurant_lng=78.348,
        drop_lat=17.45,
        drop_lng=78.36,
        placed_at=datetime(2026, 1, 5, 14, 30, tzinfo=UTC),
        total_price=398.0,
        items=[
            ItemFeature(qty=2, veg=True, prep_complexity=2),
            ItemFeature(qty=1, veg=False, prep_complexity=3),
        ],
    )


def _write_dummy_bundle(path) -> None:
    x = [[0.0] * len(FEATURE_NAMES)]
    joblib.dump(
        {
            "version": "test-v1",
            "feature_names": list(FEATURE_NAMES),
            "prep_model": DummyRegressor(strategy="constant", constant=18.0).fit(x, [18.0]),
            "drive_model": DummyRegressor(strategy="constant", constant=9.0).fit(x, [9.0]),
            "total_low_model": DummyRegressor(strategy="constant", constant=20.0).fit(
                x, [20.0]
            ),
            "total_high_model": DummyRegressor(strategy="constant", constant=40.0).fit(
                x, [40.0]
            ),
        },
        path,
    )


def _order_payload(context: dict, **overrides) -> dict:
    payload = {
        "customer_id": context["customer_id"],
        "restaurant_id": context["restaurant_id"],
        "items": [{"menu_item_id": context["item_id"], "qty": 2}],
    }
    payload.update(overrides)
    return payload


def test_feature_builder_matches_training_schema() -> None:
    features = _features()
    assert set(features) == set(FEATURE_NAMES)
    assert features["hour_of_day"] == 20.0
    assert features["day_of_week"] == 0.0
    assert features["is_weekend"] == 0.0
    assert features["distance_km"] > 0
    assert features["free_flow_drive_min"] > 0
    assert features["item_count"] == 3.0
    assert 0.08 <= features["kitchen_load"] <= 1.0
    assert features["zone_factor"] >= 1.0


def test_fallback_eta_is_sane() -> None:
    prediction = fallback_eta(_features())
    assert prediction.source == "fallback"
    assert prediction.prep_minutes > 0
    assert prediction.drive_minutes > 0
    assert prediction.low_minutes <= prediction.eta_minutes <= prediction.high_minutes


def test_engine_predicts_from_bundle(tmp_path) -> None:
    path = tmp_path / "eta_model.joblib"
    _write_dummy_bundle(path)

    engine = EtaEngine.load(str(path))
    prediction = engine.predict(_features())

    assert prediction.source == "model"
    assert prediction.model_version == "test-v1"
    assert prediction.eta_minutes == 27.0
    assert prediction.prep_minutes == 18.0
    assert prediction.drive_minutes == 9.0
    assert prediction.low_minutes == 20.0
    assert prediction.high_minutes == 40.0


def test_predict_eta_prefers_model(tmp_path, monkeypatch) -> None:
    path = tmp_path / "eta_model.joblib"
    _write_dummy_bundle(path)
    monkeypatch.setattr(settings, "eta_model_path", str(path))
    eta_engine.reset_engine_cache()
    try:
        prediction = eta_engine.predict_eta(_features())
    finally:
        eta_engine.reset_engine_cache()
        monkeypatch.undo()

    assert prediction.source == "model"


def test_predict_eta_falls_back_without_model(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "eta_model_path", str(tmp_path / "missing.joblib"))
    eta_engine.reset_engine_cache()
    try:
        prediction = eta_engine.predict_eta(_features())
    finally:
        eta_engine.reset_engine_cache()
        monkeypatch.undo()

    assert prediction.source == "fallback"


async def test_order_creation_emits_eta_event_and_promise(client, order_context) -> None:
    response = await client.post("/orders", json=_order_payload(order_context))
    assert response.status_code == 201, response.text
    order = response.json()
    assert order["promised_eta_at"] is not None

    events = (await client.get(f"/orders/{order['id']}/events")).json()
    eta_event = next(event for event in events if event["type"] == "eta_predicted")
    payload = eta_event["payload"]
    assert payload["source"] in {"model", "fallback"}
    assert payload["low_minutes"] <= payload["eta_minutes"] <= payload["high_minutes"]
    assert payload["promised_eta_at"] is not None
    assert payload["meets_deadline"] is None

    eta = await client.get(f"/orders/{order['id']}/eta")
    assert eta.status_code == 200, eta.text
    body = eta.json()
    assert body["source"] == payload["source"]
    assert body["promised_eta_at"] is not None
    assert body["meets_deadline"] is None
    assert body["low_minutes"] <= body["eta_minutes"] <= body["high_minutes"]


async def test_eta_deadline_flag(client, order_context) -> None:
    deadline = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    response = await client.post(
        "/orders", json=_order_payload(order_context, deadline_at=deadline)
    )
    assert response.status_code == 201, response.text
    order = response.json()

    events = (await client.get(f"/orders/{order['id']}/events")).json()
    eta_event = next(event for event in events if event["type"] == "eta_predicted")
    assert eta_event["payload"]["meets_deadline"] is True

    eta = await client.get(f"/orders/{order['id']}/eta")
    assert eta.status_code == 200
    assert eta.json()["meets_deadline"] is True


async def test_eta_for_unknown_order_returns_404(client) -> None:
    response = await client.get(f"/orders/{uuid4()}/eta")
    assert response.status_code == 404
