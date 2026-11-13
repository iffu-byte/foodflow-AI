"""Train ETA model bundles from training_rows-style records."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split

from app.eta.features import FEATURE_NAMES

DEFAULT_MIN_ROWS = 500


class TrainingDataError(RuntimeError):
    pass


def _value(row: Any, key: str) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return getattr(row, key)


def build_dataset(
    rows: Any, min_rows: int = DEFAULT_MIN_ROWS
) -> tuple[list[list[float]], dict[str, list[float]], int]:
    x: list[list[float]] = []
    targets: dict[str, list[float]] = {"prep": [], "drive": [], "total": []}
    skipped = 0

    for row in rows:
        raw = _value(row, "features_json")
        features = json.loads(raw) if isinstance(raw, str) else raw
        try:
            vector = [float(features[name]) for name in FEATURE_NAMES]
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        x.append(vector)
        targets["prep"].append(float(_value(row, "actual_prep_min")))
        targets["drive"].append(float(_value(row, "actual_drive_min")))
        targets["total"].append(float(_value(row, "actual_total_min")))

    if len(x) < min_rows:
        raise TrainingDataError(
            f"need at least {min_rows} usable training rows, found {len(x)}; "
            "run make sim-history first"
        )
    return x, targets, skipped


def _regressor(loss: str, quantile: float | None = None) -> HistGradientBoostingRegressor:
    kwargs: dict[str, Any] = {
        "loss": loss,
        "max_iter": 250,
        "learning_rate": 0.06,
        "min_samples_leaf": 20,
        "random_state": 42,
    }
    if quantile is not None:
        kwargs["quantile"] = quantile
    return HistGradientBoostingRegressor(**kwargs)


def train_bundle(
    x: list[list[float]],
    targets: dict[str, list[float]],
    *,
    seed: int = 42,
) -> dict:
    x_train, x_val, prep_train, prep_val = train_test_split(
        x, targets["prep"], test_size=0.2, random_state=seed
    )
    _, _, drive_train, drive_val = train_test_split(
        x, targets["drive"], test_size=0.2, random_state=seed
    )
    _, _, total_train, total_val = train_test_split(
        x, targets["total"], test_size=0.2, random_state=seed
    )

    prep_model = _regressor("squared_error").fit(x_train, prep_train)
    drive_model = _regressor("squared_error").fit(x_train, drive_train)
    low_model = _regressor("quantile", 0.1).fit(x_train, total_train)
    high_model = _regressor("quantile", 0.9).fit(x_train, total_train)

    prep_pred = prep_model.predict(x_val)
    drive_pred = drive_model.predict(x_val)
    total_pred = prep_pred + drive_pred
    low = low_model.predict(x_val)
    high = high_model.predict(x_val)

    coverage = float(((total_val >= low) & (total_val <= high)).mean())
    metrics = {
        "prep_mae": float(mean_absolute_error(prep_val, prep_pred)),
        "drive_mae": float(mean_absolute_error(drive_val, drive_pred)),
        "total_mae": float(mean_absolute_error(total_val, total_pred)),
        "p10_p90_coverage": coverage,
        "avg_interval_width": float((high - low).mean()),
        "n_train": len(x_train),
        "n_val": len(x_val),
    }

    trained_at = datetime.now(UTC)
    return {
        "version": f"eta-hgb-{trained_at:%Y%m%d%H%M%S%f}",
        "trained_at": trained_at.isoformat(),
        "feature_names": list(FEATURE_NAMES),
        "n_samples": len(x),
        "metrics": metrics,
        "prep_model": prep_model,
        "drive_model": drive_model,
        "total_low_model": low_model,
        "total_high_model": high_model,
    }


def train_model(
    rows: Any,
    *,
    min_rows: int = DEFAULT_MIN_ROWS,
    seed: int = 42,
) -> dict:
    x, targets, skipped = build_dataset(rows, min_rows=min_rows)
    bundle = train_bundle(x, targets, seed=seed)
    bundle["skipped_rows"] = skipped
    return bundle
