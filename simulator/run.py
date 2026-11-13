"""Drive the FoodFlow API with a live synthetic dinner service.

The runner simulates demand, restaurant actions, just-in-time rider dispatch,
GPS pings and deliveries against a virtual clock. Delivered orders are also
logged as `training_rows` (source='live') when a database is reachable.
"""

from __future__ import annotations

import argparse
import asyncio
import heapq
import itertools
import json
import os
import random
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

import asyncpg

from simulator import geo
from simulator.api_client import ApiError, FoodFlowClient
from simulator.generate_history import DEFAULT_DATABASE_URL, normalize_dsn
from simulator.scenarios import Scenario, get_scenario
from simulator.world import (
    OrderDraft,
    RiderInfo,
    World,
    simulate_leg,
    simulate_outcome,
)

DEFAULT_API_URL = os.environ.get("API_URL", "http://localhost:8000")


@dataclass
class RiderState:
    info: RiderInfo
    lat: float
    lng: float
    busy: bool = False
    leg_from: tuple[float, float] | None = None
    leg_to: tuple[float, float] | None = None
    leg_start: datetime | None = None
    leg_end: datetime | None = None


@dataclass
class LiveOrder:
    draft: OrderDraft
    order_id: str
    placed_at: datetime
    prep_min: float
    drive_min: float = 0.0
    state: str = "PLACED"
    ready_at: datetime | None = None
    pickup_at: datetime | None = None
    rider: RiderState | None = None
    events: dict[str, datetime] = field(default_factory=dict)


class LiveSimulator:
    def __init__(
        self,
        client: FoodFlowClient,
        world: World,
        scenario: Scenario,
        *,
        seed: int,
        speed: float,
        tick: float,
        duration_min: float,
        start_hour: int,
        max_active: int,
        gps_every: int,
        drain_minutes: float,
        conn: asyncpg.Connection | None,
        no_training: bool,
        verbose: bool,
    ) -> None:
        self.client = client
        self.world = world
        self.scenario = scenario
        self.speed = speed
        self.tick = tick
        self.max_active = max_active
        self.gps_every = gps_every
        self.conn = conn
        self.no_training = no_training
        self.verbose = verbose

        self.rng = random.Random(seed)
        self.clock_now = datetime.now(geo.CITY_TZ).replace(
            hour=start_hour, minute=0, second=0, microsecond=0
        )
        self.end_at = self.clock_now + timedelta(minutes=duration_min)
        self.drain_deadline = self.end_at + timedelta(minutes=drain_minutes)

        self.riders = [
            RiderState(info=info, lat=info.lat, lng=info.lng) for info in world.riders
        ]
        self.riders_by_id = {rider.info.id: rider for rider in self.riders}
        self.orders: dict[str, LiveOrder] = {}
        self.pending: list[LiveOrder] = []
        self.restaurant_active: Counter[str] = Counter()
        self.events: list[tuple[datetime, int, str, LiveOrder]] = []
        self.seq = itertools.count()
        self.tick_index = 0
        self.stats: Counter[str] = Counter()
        self.api_errors = 0
        self.training_rows = 0
        self.total_minutes: list[float] = []
        self.started_real = time.perf_counter()

    def schedule(self, when: datetime, kind: str, order: LiveOrder) -> None:
        heapq.heappush(self.events, (when, next(self.seq), kind, order))

    async def run(self) -> None:
        self._print_header()
        while True:
            if self.clock_now >= self.end_at and not self.orders and not self.pending:
                break
            if self.clock_now >= self.drain_deadline:
                for order in list(self.orders.values()):
                    await self._drop_order(order, "drain timeout exceeded", None)
                self.pending.clear()
                break

            self.clock_now += timedelta(seconds=self.tick * self.speed)
            await self._process_events()
            if self.clock_now < self.end_at:
                await self._maybe_place_orders()
            await self._dispatch_pending()
            await self._update_gps()

            self.tick_index += 1
            if self.tick_index % 10 == 0:
                self._print_progress()
            await asyncio.sleep(self.tick)

        self._print_summary()

    async def _process_events(self) -> None:
        while self.events and self.events[0][0] <= self.clock_now:
            _, _, kind, order = heapq.heappop(self.events)
            if order.state in {"FAILED", "CANCELLED"}:
                continue
            if kind == "accept":
                await self._handle_accept(order)
            elif kind == "ready":
                await self._handle_ready(order)
            elif kind == "pickup":
                await self._handle_pickup(order)
            elif kind == "deliver":
                await self._handle_deliver(order)

    async def _maybe_place_orders(self) -> None:
        rate = geo.demand_rate_per_min(self.clock_now.hour) * self.scenario.demand_multiplier
        virtual_minutes = self.tick * self.speed / 60.0
        arrivals = geo.poisson_sample(self.rng, rate * virtual_minutes)
        for _ in range(arrivals):
            if len(self.orders) >= self.max_active:
                break
            await self._place_order()

    async def _place_order(self) -> None:
        restaurant = self.world.pick_restaurant(self.rng)
        capacity_window = max(1.0, restaurant.capacity_per_hr / 12.0)
        kitchen_load = geo.clamp(
            self.restaurant_active[restaurant.id] / capacity_window, 0.0, 1.0
        )
        draft = self.world.random_order(
            self.clock_now,
            self.scenario,
            kitchen_load=kitchen_load,
            rng=self.rng,
        )
        payload = {
            "customer_id": draft.customer.id,
            "restaurant_id": draft.restaurant.id,
            "items": [
                {"menu_item_id": item.menu_item_id, "qty": item.qty} for item in draft.items
            ],
        }
        try:
            created = await self.client.create_order(payload)
        except ApiError as exc:
            self._record_api_error("place", exc)
            return

        outcome = simulate_outcome(draft, self.scenario, self.rng)
        live = LiveOrder(
            draft=draft,
            order_id=created["id"],
            placed_at=self.clock_now,
            prep_min=outcome.prep_min,
        )
        live.events["placed"] = self.clock_now
        self.orders[live.order_id] = live
        self.restaurant_active[restaurant.id] += 1
        self.stats["placed"] += 1

        accept_delay = self.rng.uniform(0.5, 2.0)
        self.schedule(
            self.clock_now + timedelta(minutes=accept_delay), "accept", live
        )

    async def _handle_accept(self, order: LiveOrder) -> None:
        try:
            await self.client.accept_order(order.order_id)
            await self.client.start_preparing(order.order_id)
        except ApiError as exc:
            await self._drop_order(order, "accept failed", exc)
            return

        order.state = "PREPARING"
        order.events["preparing"] = self.clock_now
        order.ready_at = self.clock_now + timedelta(minutes=order.prep_min)
        self.schedule(order.ready_at, "ready", order)

    async def _handle_ready(self, order: LiveOrder) -> None:
        try:
            await self.client.mark_ready(order.order_id)
        except ApiError as exc:
            await self._drop_order(order, "ready failed", exc)
            return

        order.state = "READY"
        order.events["ready"] = self.clock_now
        self.restaurant_active[order.draft.restaurant.id] = max(
            0, self.restaurant_active[order.draft.restaurant.id] - 1
        )
        self.pending.append(order)

    async def _dispatch_pending(self) -> None:
        if not self.pending:
            return

        remaining: list[LiveOrder] = []
        for order in self.pending:
            rider = await self._assign_rider(order)
            if rider is None:
                remaining.append(order)
                continue

            rider.busy = True
            _, _, minutes = simulate_leg(
                rider.lat,
                rider.lng,
                order.draft.restaurant.lat,
                order.draft.restaurant.lng,
                hour=self.clock_now.hour,
                rain_intensity=self.scenario.rain_intensity,
                vehicle=rider.info.vehicle,
                rider_id=rider.info.id,
                rng=self.rng,
            )
            rider.leg_from = (rider.lat, rider.lng)
            rider.leg_to = (order.draft.restaurant.lat, order.draft.restaurant.lng)
            rider.leg_start = self.clock_now
            rider.leg_end = self.clock_now + timedelta(minutes=minutes)

            order.rider = rider
            order.state = "TO_PICKUP"
            self.schedule(rider.leg_end, "pickup", order)

        self.pending = remaining

    async def _handle_pickup(self, order: LiveOrder) -> None:
        rider = order.rider
        if rider is None:
            await self._drop_order(order, "pickup without rider", None)
            return

        try:
            await self.client.update_status(order.order_id, "PICKED_UP", rider.info.id)
        except ApiError as exc:
            await self._drop_order(order, "pickup failed", exc)
            return

        order.state = "PICKED_UP"
        order.events["picked_up"] = self.clock_now
        rider.lat = order.draft.restaurant.lat
        rider.lng = order.draft.restaurant.lng

        _, _, minutes = simulate_leg(
            rider.lat,
            rider.lng,
            order.draft.drop_lat,
            order.draft.drop_lng,
            hour=self.clock_now.hour,
            rain_intensity=self.scenario.rain_intensity,
            vehicle=rider.info.vehicle,
            rider_id=rider.info.id,
            rng=self.rng,
        )
        order.drive_min = minutes
        rider.leg_from = (rider.lat, rider.lng)
        rider.leg_to = (order.draft.drop_lat, order.draft.drop_lng)
        rider.leg_start = self.clock_now
        rider.leg_end = self.clock_now + timedelta(minutes=minutes)
        self.schedule(rider.leg_end, "deliver", order)

    async def _handle_deliver(self, order: LiveOrder) -> None:
        rider = order.rider
        if rider is None:
            await self._drop_order(order, "delivery without rider", None)
            return

        try:
            await self.client.update_status(order.order_id, "DELIVERED", rider.info.id)
        except ApiError as exc:
            await self._drop_order(order, "delivery failed", exc)
            return

        order.state = "DELIVERED"
        order.events["delivered"] = self.clock_now
        rider.lat = order.draft.drop_lat
        rider.lng = order.draft.drop_lng
        self._release_rider(rider)
        self.orders.pop(order.order_id, None)
        self.stats["delivered"] += 1
        total_minutes = (self.clock_now - order.placed_at).total_seconds() / 60.0
        self.total_minutes.append(total_minutes)
        await self._write_training_row(order, total_minutes)

    async def _drop_order(
        self,
        order: LiveOrder,
        reason: str,
        error: ApiError | None,
    ) -> None:
        if order.order_id in self.orders:
            self.orders.pop(order.order_id, None)
        self.stats["failed"] += 1
        if order.rider is not None and order.rider.busy:
            self._release_rider(order.rider)
        if error is not None:
            self._record_api_error(reason, error)
        elif self.verbose:
            print(f"  dropped order {order.order_id[:8]}: {reason}")
        if order.state != "FAILED":
            order.state = "FAILED"
            try:
                await self.client.cancel_order(order.order_id, reason=f"simulator: {reason}")
            except ApiError:
                pass

    def _release_rider(self, rider: RiderState) -> None:
        rider.busy = False
        rider.leg_from = None
        rider.leg_to = None
        rider.leg_start = None
        rider.leg_end = None

    def _nearest_idle(self, lat: float, lng: float) -> RiderState | None:
        candidates = [rider for rider in self.riders if not rider.busy]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda rider: geo.haversine_km(rider.lat, rider.lng, lat, lng),
        )

    async def _assign_rider(self, order: LiveOrder) -> RiderState | None:
        try:
            candidates = await self.client.list_candidates(order.order_id)
        except ApiError as exc:
            self._record_api_error("candidates", exc)
            return self._nearest_idle(
                order.draft.restaurant.lat, order.draft.restaurant.lng
            )

        for candidate in candidates:
            rider = self.riders_by_id.get(candidate["rider"]["id"])
            if rider is None or rider.busy:
                continue
            try:
                await self.client.assign_order(order.order_id, rider.info.id)
            except ApiError as exc:
                self._record_api_error("assign", exc)
                continue
            return rider
        return None

    async def _update_gps(self) -> None:
        if self.gps_every <= 0 or self.tick_index % self.gps_every != 0:
            return
        for rider in self.riders:
            if (
                not rider.busy
                or rider.leg_from is None
                or rider.leg_to is None
                or rider.leg_start is None
                or rider.leg_end is None
            ):
                continue
            span = (rider.leg_end - rider.leg_start).total_seconds()
            progress = (
                1.0
                if span <= 0
                else (self.clock_now - rider.leg_start).total_seconds() / span
            )
            rider.lat, rider.lng = geo.point_along(rider.leg_from, rider.leg_to, progress)
            try:
                await self.client.update_rider_location(
                    rider.info.id, round(rider.lat, 6), round(rider.lng, 6)
                )
            except ApiError as exc:
                self._record_api_error("gps", exc)

    async def _write_training_row(self, order: LiveOrder, total_minutes: float) -> None:
        if self.conn is None or self.no_training:
            return
        rider_info = order.rider.info if order.rider else None
        draft = replace(order.draft, rider=rider_info)
        try:
            await self.conn.execute(
                """
                INSERT INTO training_rows
                    (id, order_id, features_json, actual_prep_min, actual_drive_min,
                     actual_total_min, completed_at, source, created_at)
                VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7, 'live', now())
                """,
                str(uuid.uuid4()),
                order.order_id,
                json.dumps(draft.features(), ensure_ascii=True),
                round(order.prep_min, 3),
                round(order.drive_min, 3),
                round(total_minutes, 3),
                order.events.get("delivered", self.clock_now).astimezone(UTC),
            )
            self.training_rows += 1
        except Exception as exc:  # noqa: BLE001 - training logging is best effort
            if self.verbose:
                print(f"  warning: could not write training row ({exc})")

    def _record_api_error(self, stage: str, error: ApiError) -> None:
        self.api_errors += 1
        if self.verbose:
            print(f"  api error during {stage}: {error}")

    def _print_header(self) -> None:
        real_seconds_per_minute = 60.0 / self.speed if self.speed else 0.0
        kitchens = len(self.world.restaurants)
        print("FoodFlow live simulator")
        print(f"Scenario: {self.scenario.name} - {self.scenario.description}")
        print(
            f"City: {kitchens} restaurants, {len(self.world.customers)} customers, "
            f"{len(self.riders)} riders"
        )
        print(
            f"Window: {self.clock_now:%H:%M} -> {self.end_at:%H:%M} "
            f"({(self.end_at - self.clock_now).total_seconds() / 60:.0f} virtual min) "
            f"at {real_seconds_per_minute:.2f}s per virtual min"
        )
        print("-" * 72)

    def _print_progress(self) -> None:
        busy = sum(1 for rider in self.riders if rider.busy)
        print(
            f"[{self.clock_now:%H:%M}] placed={self.stats['placed']} "
            f"delivered={self.stats['delivered']} active={len(self.orders)} "
            f"waiting={len(self.pending)} riders={busy}/{len(self.riders)}"
        )

    def _print_summary(self) -> None:
        elapsed = time.perf_counter() - self.started_real
        avg_total = (
            sum(self.total_minutes) / len(self.total_minutes) if self.total_minutes else 0.0
        )
        print("-" * 72)
        print(
            f"Finished in {elapsed:.1f}s real time. placed={self.stats['placed']} "
            f"delivered={self.stats['delivered']} failed={self.stats['failed']} "
            f"still_active={len(self.orders)}"
        )
        print(f"Average order time: {avg_total:.1f} virtual min")
        print(
            f"Training rows written: {self.training_rows} | api errors: {self.api_errors}"
        )


async def _load_world(client: FoodFlowClient, seed: int) -> World:
    restaurants = await client.list_restaurants()
    customers = await client.list_customers()
    riders = await client.list_riders()
    if not restaurants or not customers or not riders:
        raise SystemExit("API has no seeded city; run `python -m app.seed --force` first")

    menus_by_restaurant: dict[str, list[dict]] = {}
    for restaurant in restaurants:
        menus_by_restaurant[restaurant["id"]] = await client.get_menu(restaurant["id"])

    customer_records = [
        {
            "id": customer["id"],
            "name": customer["name"],
            "lat": customer["home_lat"],
            "lng": customer["home_lng"],
        }
        for customer in customers
    ]
    return World.from_records(
        restaurants, menus_by_restaurant, customer_records, riders, seed=seed
    )


async def run(args: argparse.Namespace) -> None:
    scenario = get_scenario(args.scenario)

    conn: asyncpg.Connection | None = None
    if not args.no_training:
        try:
            conn = await asyncpg.connect(normalize_dsn(args.database_url))
        except Exception as exc:  # noqa: BLE001 - live logging is optional
            print(f"warning: live training rows disabled ({exc})")

    async with FoodFlowClient(args.api_url) as client:
        world = await _load_world(client, args.seed)
        simulator = LiveSimulator(
            client,
            world,
            scenario,
            seed=args.seed,
            speed=args.speed,
            tick=args.tick,
            duration_min=args.duration,
            start_hour=args.start_hour,
            max_active=args.max_active,
            gps_every=args.gps_every,
            drain_minutes=args.drain_minutes,
            conn=conn,
            no_training=args.no_training,
            verbose=args.verbose,
        )
        try:
            await simulator.run()
        finally:
            if conn is not None:
                await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a live FoodFlow dinner service.")
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help="API base URL (API_URL env also works)",
    )
    parser.add_argument(
        "--database-url",
        default=DEFAULT_DATABASE_URL,
        help="Postgres URL used for live training rows",
    )
    parser.add_argument("--scenario", default="normal", help="normal|rainy|rush_hour|kitchen_outage")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--duration", type=float, default=120.0, help="virtual minutes to simulate"
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=60.0,
        help="virtual seconds per real second (60 = one virtual minute per second)",
    )
    parser.add_argument("--tick", type=float, default=1.0, help="real seconds per loop")
    parser.add_argument("--start-hour", type=int, default=19)
    parser.add_argument("--max-active", type=int, default=30)
    parser.add_argument(
        "--drain-minutes",
        type=float,
        default=90.0,
        help="extra virtual minutes allowed for in-flight orders after the window",
    )
    parser.add_argument(
        "--gps-every",
        type=int,
        default=2,
        help="ticks between rider GPS pings (0 disables)",
    )
    parser.add_argument("--no-training", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not 0 <= args.start_hour <= 23:
        parser.error("--start-hour must be between 0 and 23")
    if args.speed <= 0 or args.tick <= 0:
        parser.error("--speed and --tick must be positive")

    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\ninterrupted")


if __name__ == "__main__":
    main()
