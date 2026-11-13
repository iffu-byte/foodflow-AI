"""Train gradient-boosted ETA models from simulator training_rows.

Examples:
    docker compose run --rm api python /ml/train_eta.py
    docker compose exec api python /ml/train_eta.py --output artifacts/eta_model.joblib
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import asyncpg
import joblib


def _ensure_app_importable() -> None:
    candidates = []
    env_root = os.environ.get("BACKEND_ROOT")
    if env_root:
        candidates.append(Path(env_root))
    candidates.append(Path("/app"))
    candidates.append(Path(__file__).resolve().parents[1] / "backend")
    for candidate in candidates:
        if (candidate / "app" / "eta" / "features.py").exists():
            sys.path.insert(0, str(candidate))
            return
    raise SystemExit("could not locate the backend app package; set BACKEND_ROOT")


_ensure_app_importable()

from app.learning.trainer import TrainingDataError, train_model  # noqa: E402

DEFAULT_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://foodflow:foodflow@localhost:5432/foodflow"
)


async def fetch_rows(database_url: str) -> list[asyncpg.Record]:
    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        return await conn.fetch(
            """
            SELECT features_json, actual_prep_min, actual_drive_min, actual_total_min
            FROM training_rows
            """
        )
    finally:
        await conn.close()


async def run(args: argparse.Namespace) -> None:
    rows = await fetch_rows(args.database_url)
    try:
        bundle = train_model(rows, min_rows=args.min_rows, seed=args.seed)
    except TrainingDataError as exc:
        raise SystemExit(str(exc)) from exc

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, output)

    metrics = bundle["metrics"]
    print(
        f"Trained {bundle['version']} on {bundle['n_samples']} rows "
        f"({metrics['n_train']} train / {metrics['n_val']} val, "
        f"skipped {bundle['skipped_rows']})"
    )
    print(
        f"MAE: prep={metrics['prep_mae']:.2f} min, drive={metrics['drive_mae']:.2f} min, "
        f"total={metrics['total_mae']:.2f} min"
    )
    print(
        f"P10-P90 coverage: {metrics['p10_p90_coverage']:.1%}, "
        f"mean interval width {metrics['avg_interval_width']:.1f} min"
    )
    print(f"Saved bundle to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the FoodFlow ETA model.")
    parser.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    parser.add_argument(
        "--output",
        default="artifacts/eta_model.joblib",
        help="path for the joblib model bundle",
    )
    parser.add_argument("--min-rows", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
