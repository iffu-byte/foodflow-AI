import json
import random
from datetime import datetime

import pytest

from simulator import geo
from simulator.scenarios import get_scenario
from simulator.world import (
    CustomerInfo,
    MenuItemInfo,
    RestaurantInfo,
    RiderInfo,
    World,
    simulate_leg,
    simulate_outcome,
)


def make_world(seed: int = 42) -> World:
    restaurant = RestaurantInfo(
        "r1", "Test Kitchen", 17.442, 78.348, 15, 40, ("test",)
    )
    menu = [
        MenuItemInfo(f"m{i}", f"Dish {i}", 199.0, "mains", i % 2 == 0, 1 + i % 3)
        for i in range(4)
    ]
    customers = [
        CustomerInfo("c1", "Cust One", 17.45, 78.36),
        CustomerInfo("c2", "Cust Two", 17.43, 78.34),
    ]
    riders = [
        RiderInfo("d1", "Rider One", 17.441, 78.349, "bike"),
        RiderInfo("d2", "Rider Two", 17.44, 78.35, "cycle"),
    ]
    return World([restaurant], {"r1": menu}, customers, riders, seed=seed)


def test_haversine_matches_known_distance() -> None:
    distance = geo.haversine_km(17.44, 78.35, 17.45, 78.36)
    assert 1.4 < distance < 1.7


def test_demand_profile_peaks() -> None:
    assert geo.demand_rate_per_min(12) > geo.demand_rate_per_min(15)
    assert geo.demand_rate_per_min(20) > geo.demand_rate_per_min(15)
    assert geo.demand_rate_per_min(3) < geo.demand_rate_per_min(8)


def test_traffic_profile_peaks_at_rush() -> None:
    assert geo.traffic_multiplier(18) > geo.traffic_multiplier(13)
    assert geo.traffic_multiplier(18) > geo.traffic_multiplier(3)


def test_poisson_sample_is_zero_for_zero_rate() -> None:
    rng = random.Random(1)
    assert geo.poisson_sample(rng, 0.0) == 0
    samples = [geo.poisson_sample(rng, 2.0) for _ in range(400)]
    mean = sum(samples) / len(samples)
    assert 1.6 < mean < 2.4


def test_world_requires_core_entities() -> None:
    with pytest.raises(ValueError):
        World([], {}, [], [], seed=1)


def test_random_order_is_deterministic_for_seed() -> None:
    now = datetime(2026, 1, 5, 20, 15)
    scenario = get_scenario("normal")
    first = make_world(seed=7).random_order(
        now, scenario, kitchen_load=0.4, rng=random.Random(11)
    )
    second = make_world(seed=7).random_order(
        now, scenario, kitchen_load=0.4, rng=random.Random(11)
    )
    assert first.features() == second.features()
    assert json.loads(json.dumps(first.features()))


def test_random_order_features_are_sane() -> None:
    world = make_world()
    draft = world.random_order(
        datetime(2026, 1, 5, 12, 0),
        get_scenario("rainy"),
        kitchen_load=0.5,
        rng=random.Random(3),
    )
    features = draft.features()
    assert features["hour_of_day"] == 12
    assert features["rain_intensity"] == 0.7
    assert features["kitchen_load"] == 0.5
    assert features["item_count"] >= 1
    assert features["distance_km"] > 0
    assert features["free_flow_drive_min"] > 0
    assert 1.0 <= features["traffic_multiplier"] <= 2.0


def test_rain_and_traffic_slow_deliveries() -> None:
    now = datetime(2026, 1, 5, 20, 0)
    world = make_world()
    normal = get_scenario("normal")
    rainy = get_scenario("rainy")

    normal_draft = world.random_order(now, normal, kitchen_load=0.5, rng=random.Random(5))
    rainy_draft = world.random_order(now, rainy, kitchen_load=0.5, rng=random.Random(5))

    normal_outcome = simulate_outcome(normal_draft, normal, random.Random(9))
    rainy_outcome = simulate_outcome(rainy_draft, rainy, random.Random(9))

    assert rainy_outcome.drive_min > normal_outcome.drive_min
    assert rainy_outcome.total_min > 0


def test_simulate_leg_scales_with_vehicle_and_distance() -> None:
    rng_bike = random.Random(2)
    rng_cycle = random.Random(2)
    _, routed_short, minutes_short = simulate_leg(
        17.44,
        78.35,
        17.442,
        78.352,
        hour=13,
        rain_intensity=0.0,
        vehicle="bike",
        rider_id="d1",
        rng=rng_bike,
    )
    _, routed_long, minutes_long = simulate_leg(
        17.44,
        78.35,
        17.47,
        78.39,
        hour=13,
        rain_intensity=0.0,
        vehicle="bike",
        rider_id="d1",
        rng=random.Random(2),
    )
    _, _, minutes_cycle = simulate_leg(
        17.44,
        78.35,
        17.442,
        78.352,
        hour=13,
        rain_intensity=0.0,
        vehicle="cycle",
        rider_id="d1",
        rng=rng_cycle,
    )
    assert 0 < routed_short < routed_long
    assert minutes_long > minutes_short
    assert minutes_cycle > minutes_short


def test_unknown_scenario_is_rejected() -> None:
    with pytest.raises(ValueError):
        get_scenario("snowstorm")
