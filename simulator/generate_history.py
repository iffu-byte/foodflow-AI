"""Bulk-generate synthetic order history into the training_rows table.

Reads the seeded city (restaurants, menus, customers, riders) straight from
Postgres so historical rows reference the same entities the live API serves.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import time
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta

import asyncpg

from simulator import geo
from simulator.scenarios import Scenario, get_scenario
from simulator.world import OrderDraft, World, simulate_outcome

DEFAULT_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://foodflow:foodflow@localhost:5432/foodflow"
)

SCENARIO_WEIGHTS = [
    ("normal", 0.6),
    ("rush_hour", 0.25),
    ("rainy", 0.1),
    ("kitchen_outage", 0.05),
]

HOUR_WEIGHTS = [geo.demand_rate_per_min(hour) for hour in range(24)]

INSERT_COLUMNS = [
    "id",
    "order_id",
    "features_json",
    "actual_prep_min",
    "actual_drive_min",
    "actual_total_min",
    "completed_at",
    "source",
    "created_at",
]


def normalize_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _as_list(value: object) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        return parsed if isinstance(parsed, list) else [parsed]
    return list(value)  # type: ignore[arg-type]


async def load_world(conn: asyncpg.Connection, seed: int) -> World:
    restaurant_rows = await conn.fetch(
        """
        SELECT id, name, lat, lng, avg_prep_min, capacity_per_hr, cuisine
        FROM restaurants
        ORDER BY name
        """
    )
    menu_rows = await conn.fetch(
        """
        SELECT id, restaurant_id, name, price, category, veg, prep_complexity
        FROM menu_items
        """
    )
    customer_rows = await conn.fetch(
        """
        SELECT c.user_id AS id, u.name AS name, c.home_lat AS lat, c.home_lng AS lng
        FROM customers c
        JOIN users u ON u.id = c.user_id
        ORDER BY u.name
        """
    )
    rider_rows = await conn.fetch(
        "SELECT id, name, lat, lng, vehicle, capacity FROM riders ORDER BY name"
    )

    if not restaurant_rows or not customer_rows or not rider_rows:
        raise SystemExit(
            "database has no seeded city; run `python -m app.seed --force` first"
        )

    restaurants = [dict(row) for row in restaurant_rows]
    for restaurant in restaurants:
        restaurant["cuisine"] = _as_list(restaurant["cuisine"])

    menus_by_restaurant: dict[str, list[dict]] = {}
    for row in menu_rows:
        menus_by_restaurant.setdefault(str(row["restaurant_id"]), []).append(dict(row))

    return World.from_records(
        restaurants,
        menus_by_restaurant,
        [dict(row) for row in customer_rows],
        [dict(row) for row in rider_rows],
        seed=seed,
    )


def sample_placed_at(rng: random.Random, days: int, reference_local: datetime) -> datetime:
    day_offset = rng.randrange(days)
    date = reference_local - timedelta(days=day_offset)
    hour = rng.choices(range(24), weights=HOUR_WEIGHTS, k=1)[0]
    return date.replace(
        hour=hour,
        minute=rng.randrange(60),
        second=rng.randrange(60),
        microsecond=0,
    )


def build_rows(
    world: World,
    count: int,
    days: int,
    seed: int,
    reference_local: datetime,
) -> tuple[list[tuple], Counter, dict[str, list[float]]]:
    rng = random.Random(seed)
    day_scenarios: dict[str, Scenario] = {}
    scenario_counts: Counter = Counter()
    durations: dict[str, list[float]] = {"prep": [], "drive": [], "total": []}
    now = datetime.now(UTC)
    rows: list[tuple] = []

    for _ in range(count):
        placed_local = sample_placed_at(rng, days, reference_local)
        date_key = placed_local.date().isoformat()
        scenario = day_scenarios.get(date_key)
        if scenario is None:
            name = rng.choices(
                [name for name, _ in SCENARIO_WEIGHTS],
                weights=[weight for _, weight in SCENARIO_WEIGHTS],
                k=1,
            )[0]
            scenario = get_scenario(name)
            day_scenarios[date_key] = scenario

        draft: OrderDraft = world.random_order(placed_local, scenario, rng=rng)
        outcome = simulate_outcome(draft, scenario, rng)
        completed_at = placed_local.astimezone(UTC) + timedelta(minutes=outcome.total_min)

        scenario_counts[scenario.name] += 1
        durations["prep"].append(outcome.prep_min)
        durations["drive"].append(outcome.drive_min)
        durations["total"].append(outcome.total_min)

        rows.append(
            (
                str(uuid.uuid4()),
                None,
                json.dumps(draft.features(), ensure_ascii=True),
                outcome.prep_min,
                outcome.drive_min,
                outcome.total_min,
                completed_at,
                "history",
                now,
            )
        )

    return rows, scenario_counts, durations


async def insert_rows(
    conn: asyncpg.Connection,
    rows: list[tuple],
    batch_size: int = 5000,
) -> None:
    for start in range(0, len(rows), batch_size):
        await conn.copy_records_to_table(
            "training_rows",
            records=rows[start : start + batch_size],
            columns=INSERT_COLUMNS,
        )


async def run(args: argparse.Namespace) -> None:
    conn = await asyncpg.connect(normalize_dsn(args.database_url))
    try:
        world = await load_world(conn, args.seed)
        print(
            f"Loaded city: {len(world.restaurants)} restaurants, "
            f"{len(world.customers)} customers, {len(world.riders)} riders"
        )

        if args.replace:
            status = await conn.execute("DELETE FROM training_rows WHERE source = 'history'")
            print(f"Cleared existing history rows ({status})")

        reference = datetime.now(geo.CITY_TZ)
        started = time.perf_counter()
        rows, scenario_counts, durations = build_rows(
            world, args.orders, args.days, args.seed, reference
        )
        built = time.perf_counter() - started

        insert_started = time.perf_counter()
        await insert_rows(conn, rows)
        inserted = time.perf_counter() - insert_started
    finally:
        await conn.close()

    total = time.perf_counter() - started
    avg = {key: sum(values) / len(values) for key, values in durations.items()}
    print(
        f"Generated {len(rows)} training rows in {total:.1f}s "
        f"(build {built:.1f}s, insert {inserted:.1f}s, {len(rows) / total:.0f} rows/s)"
    )
    print(
        "Scope: "
        + ", ".join(f"{name}={count}" for name, count in sorted(scenario_counts.items()))
    )
    print(
        f"Mean durations: prep={avg['prep']:.1f} min, "
        f"drive={avg['drive']:.1f} min, total={avg['total']:.1f} min"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic FoodFlow order history into training_rows."
    )
    parser.add_argument("--orders", type=int, default=30000, help="number of rows")
    parser.add_argument("--days", type=int, default=30, help="history window in days")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--database-url",
        default=DEFAULT_DATABASE_URL,
        help="asyncpg-compatible Postgres URL",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="delete existing source='history' rows first",
    )
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
