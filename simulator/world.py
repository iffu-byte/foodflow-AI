from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from simulator import geo
from simulator.scenarios import Scenario

KITCHEN_MISHAP_PROB = 0.05


@dataclass(frozen=True)
class RestaurantInfo:
    id: str
    name: str
    lat: float
    lng: float
    avg_prep_min: int
    capacity_per_hr: int
    cuisines: tuple[str, ...] = ()


@dataclass(frozen=True)
class MenuItemInfo:
    id: str
    name: str
    price: float
    category: str
    veg: bool
    prep_complexity: int


@dataclass(frozen=True)
class CustomerInfo:
    id: str
    name: str
    lat: float
    lng: float


@dataclass(frozen=True)
class RiderInfo:
    id: str
    name: str
    lat: float
    lng: float
    vehicle: str = "bike"
    capacity: int = 2


@dataclass(frozen=True)
class OrderItemDraft:
    menu_item_id: str
    name: str
    qty: int
    unit_price: float
    prep_complexity: int
    veg: bool


@dataclass(frozen=True)
class OrderDraft:
    restaurant: RestaurantInfo
    customer: CustomerInfo
    items: tuple[OrderItemDraft, ...]
    placed_at: datetime
    drop_lat: float
    drop_lng: float
    hour_of_day: int
    day_of_week: int
    kitchen_load: float
    rain_intensity: float
    traffic_multiplier: float
    zone_factor: float
    routed_distance_km: float
    free_flow_drive_min: float
    scenario_name: str
    rider: RiderInfo | None = None

    @property
    def item_count(self) -> int:
        return sum(item.qty for item in self.items)

    @property
    def distinct_items(self) -> int:
        return len(self.items)

    @property
    def total_price(self) -> float:
        return round(sum(item.qty * item.unit_price for item in self.items), 2)

    @property
    def avg_complexity(self) -> float:
        if not self.items:
            return 1.0
        weighted = sum(item.qty * item.prep_complexity for item in self.items)
        return weighted / self.item_count

    @property
    def max_complexity(self) -> int:
        return max((item.prep_complexity for item in self.items), default=1)

    @property
    def veg_share(self) -> float:
        if not self.items:
            return 0.0
        return sum(item.qty for item in self.items if item.veg) / self.item_count

    def features(self) -> dict:
        return {
            "restaurant_id": self.restaurant.id,
            "customer_id": self.customer.id,
            "rider_id": self.rider.id if self.rider else None,
            "restaurant_name": self.restaurant.name,
            "restaurant_lat": self.restaurant.lat,
            "restaurant_lng": self.restaurant.lng,
            "drop_lat": self.drop_lat,
            "drop_lng": self.drop_lng,
            "distance_km": round(
                geo.haversine_km(
                    self.restaurant.lat,
                    self.restaurant.lng,
                    self.drop_lat,
                    self.drop_lng,
                ),
                3,
            ),
            "routed_distance_km": round(self.routed_distance_km, 3),
            "free_flow_drive_min": round(self.free_flow_drive_min, 3),
            "hour_of_day": self.hour_of_day,
            "day_of_week": self.day_of_week,
            "is_weekend": self.day_of_week >= 5,
            "item_count": self.item_count,
            "distinct_items": self.distinct_items,
            "avg_prep_complexity": round(self.avg_complexity, 3),
            "max_prep_complexity": self.max_complexity,
            "veg_share": round(self.veg_share, 3),
            "total_price": self.total_price,
            "restaurant_avg_prep_min": self.restaurant.avg_prep_min,
            "restaurant_capacity_per_hr": self.restaurant.capacity_per_hr,
            "kitchen_load": round(self.kitchen_load, 3),
            "rain_intensity": round(self.rain_intensity, 3),
            "traffic_multiplier": round(self.traffic_multiplier, 3),
            "zone_factor": round(self.zone_factor, 3),
            "vehicle": self.rider.vehicle if self.rider else "unknown",
            "scenario": self.scenario_name,
        }


@dataclass(frozen=True)
class OrderOutcome:
    prep_min: float
    drive_min: float

    @property
    def total_min(self) -> float:
        return self.prep_min + self.drive_min


def simulate_outcome(order: OrderDraft, scenario: Scenario, rng: random.Random) -> OrderOutcome:
    restaurant_bias = geo.stable_factor(f"restaurant-bias:{order.restaurant.id}", 0.92, 1.12)
    complexity_factor = 1.0 + 0.1 * (order.avg_complexity - 1.0)

    prep = (
        order.restaurant.avg_prep_min
        * complexity_factor
        * (1.0 + 0.5 * order.kitchen_load)
        * restaurant_bias
        * rng.uniform(0.85, 1.2)
        * scenario.prep_multiplier
    )
    if rng.random() < KITCHEN_MISHAP_PROB:
        prep += rng.uniform(10.0, 20.0)
    if rng.random() < scenario.kitchen_outage_prob:
        prep += rng.uniform(*scenario.incident_extra_min)

    skill = 1.0
    vehicle_factor = 1.0
    if order.rider is not None:
        skill = geo.stable_factor(f"rider-skill:{order.rider.id}", 0.88, 1.12)
        vehicle_factor = geo.vehicle_time_factor(order.rider.vehicle)

    rain_factor = 1.0 + 0.35 * order.rain_intensity
    drive = (
        order.free_flow_drive_min
        * order.traffic_multiplier
        * order.zone_factor
        * rain_factor
        * vehicle_factor
        * skill
        * rng.uniform(0.9, 1.15)
    )

    return OrderOutcome(prep_min=round(max(1.0, prep), 3), drive_min=round(max(0.5, drive), 3))


def simulate_leg(
    from_lat: float,
    from_lng: float,
    to_lat: float,
    to_lng: float,
    *,
    hour: int,
    rain_intensity: float,
    vehicle: str,
    rider_id: str,
    rng: random.Random,
) -> tuple[float, float, float]:
    distance = geo.haversine_km(from_lat, from_lng, to_lat, to_lng)
    routed = distance * geo.DETOUR_FACTOR
    free_flow = geo.free_flow_minutes(routed)
    skill = geo.stable_factor(f"rider-skill:{rider_id}", 0.88, 1.12)
    minutes = (
        free_flow
        * geo.traffic_multiplier(hour)
        * geo.zone_factor(to_lat, to_lng)
        * (1.0 + 0.35 * rain_intensity)
        * geo.vehicle_time_factor(vehicle)
        * skill
        * rng.uniform(0.9, 1.15)
    )
    return distance, routed, max(0.3, minutes)


class World:
    def __init__(
        self,
        restaurants: Sequence[RestaurantInfo],
        menus: Mapping[str, Sequence[MenuItemInfo]],
        customers: Sequence[CustomerInfo],
        riders: Sequence[RiderInfo],
        seed: int = 42,
    ) -> None:
        self.menus = {str(key): list(items) for key, items in menus.items() if items}
        self.restaurants = [r for r in restaurants if r.id in self.menus]
        self.customers = list(customers)
        self.riders = list(riders)
        if not self.restaurants:
            raise ValueError("world needs at least one restaurant with a menu")
        if not self.customers:
            raise ValueError("world needs at least one customer")
        if not self.riders:
            raise ValueError("world needs at least one rider")
        self.rng = random.Random(seed)
        self._weights = [
            geo.stable_factor(f"restaurant-popularity:{r.id}", 0.5, 1.5)
            for r in self.restaurants
        ]

    @classmethod
    def from_records(
        cls,
        restaurants: Sequence[Mapping],
        menus_by_restaurant: Mapping[str, Sequence[Mapping]],
        customers: Sequence[Mapping],
        riders: Sequence[Mapping],
        seed: int = 42,
    ) -> "World":
        restaurant_infos = [
            RestaurantInfo(
                id=str(row["id"]),
                name=row["name"],
                lat=float(row["lat"]),
                lng=float(row["lng"]),
                avg_prep_min=int(row["avg_prep_min"]),
                capacity_per_hr=int(row["capacity_per_hr"]),
                cuisines=tuple(row.get("cuisine") or ()),
            )
            for row in restaurants
        ]
        menus = {
            str(restaurant_id): [
                MenuItemInfo(
                    id=str(item["id"]),
                    name=item["name"],
                    price=float(item["price"]),
                    category=item["category"],
                    veg=bool(item["veg"]),
                    prep_complexity=int(item["prep_complexity"]),
                )
                for item in items
            ]
            for restaurant_id, items in menus_by_restaurant.items()
        }
        customer_infos = [
            CustomerInfo(
                id=str(row["id"]),
                name=row["name"],
                lat=float(row["lat"]),
                lng=float(row["lng"]),
            )
            for row in customers
        ]
        rider_infos = [
            RiderInfo(
                id=str(row["id"]),
                name=row["name"],
                lat=float(row["lat"]),
                lng=float(row["lng"]),
                vehicle=row.get("vehicle") or "bike",
                capacity=int(row.get("capacity") or 2),
            )
            for row in riders
        ]
        return cls(restaurant_infos, menus, customer_infos, rider_infos, seed=seed)

    def pick_restaurant(self, rng: random.Random | None = None) -> RestaurantInfo:
        rng = rng or self.rng
        return rng.choices(self.restaurants, weights=self._weights, k=1)[0]

    def estimate_kitchen_load(self, hour: int, rng: random.Random | None = None) -> float:
        rng = rng or self.rng
        base = geo.demand_rate_per_min(hour) / 3.0
        return geo.clamp(base * 0.7 + 0.15 + rng.uniform(-0.08, 0.08), 0.08, 1.0)

    def random_order(
        self,
        now: datetime,
        scenario: Scenario,
        *,
        kitchen_load: float | None = None,
        rng: random.Random | None = None,
    ) -> OrderDraft:
        rng = rng or self.rng
        restaurant = self.pick_restaurant(rng)
        menu = self.menus[restaurant.id]
        customer = rng.choice(self.customers)

        distinct = rng.choices([1, 2, 3], weights=[55, 32, 13], k=1)[0]
        chosen = rng.sample(menu, k=min(distinct, len(menu)))
        items = tuple(
            OrderItemDraft(
                menu_item_id=item.id,
                name=item.name,
                qty=rng.choices([1, 2, 3], weights=[78, 18, 4], k=1)[0],
                unit_price=item.price,
                prep_complexity=item.prep_complexity,
                veg=item.veg,
            )
            for item in chosen
        )

        distance = geo.haversine_km(restaurant.lat, restaurant.lng, customer.lat, customer.lng)
        routed = distance * geo.DETOUR_FACTOR
        hour = now.hour
        return OrderDraft(
            restaurant=restaurant,
            customer=customer,
            items=items,
            placed_at=now,
            drop_lat=customer.lat,
            drop_lng=customer.lng,
            hour_of_day=hour,
            day_of_week=now.weekday(),
            kitchen_load=(
                kitchen_load
                if kitchen_load is not None
                else self.estimate_kitchen_load(hour, rng)
            ),
            rain_intensity=scenario.rain_intensity,
            traffic_multiplier=geo.traffic_multiplier(hour) * scenario.traffic_multiplier,
            zone_factor=geo.zone_factor(customer.lat, customer.lng),
            routed_distance_km=routed,
            free_flow_drive_min=geo.free_flow_minutes(routed),
            scenario_name=scenario.name,
        )
