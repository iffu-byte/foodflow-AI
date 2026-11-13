from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    demand_multiplier: float = 1.0
    rain_intensity: float = 0.0
    traffic_multiplier: float = 1.0
    prep_multiplier: float = 1.0
    kitchen_outage_prob: float = 0.0
    incident_extra_min: tuple[float, float] = (10.0, 20.0)


SCENARIOS: dict[str, Scenario] = {
    "normal": Scenario(
        name="normal",
        description="Clear evening with typical demand and traffic",
    ),
    "rainy": Scenario(
        name="rainy",
        description="Monsoon showers slow riders and nudge kitchens",
        demand_multiplier=1.15,
        rain_intensity=0.7,
        traffic_multiplier=1.2,
        prep_multiplier=1.05,
    ),
    "rush_hour": Scenario(
        name="rush_hour",
        description="Dinner rush strains kitchens and roads",
        demand_multiplier=1.8,
        traffic_multiplier=1.3,
        prep_multiplier=1.1,
    ),
    "kitchen_outage": Scenario(
        name="kitchen_outage",
        description="Equipment failures randomly stall some kitchens",
        prep_multiplier=1.2,
        kitchen_outage_prob=0.15,
        incident_extra_min=(15.0, 30.0),
    ),
}


def get_scenario(name: str) -> Scenario:
    try:
        return SCENARIOS[name]
    except KeyError:
        known = ", ".join(sorted(SCENARIOS))
        raise ValueError(f"unknown scenario {name!r}; choose one of: {known}") from None
