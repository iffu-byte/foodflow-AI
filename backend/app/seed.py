import argparse
import asyncio
import math
import random
import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select

from app.auth.security import hash_password
from app.config import settings
from app.db import get_sessionmaker
from app.domain.models import (
    AiUsage,
    Cart,
    CartItem,
    Customer,
    CustomerAddress,
    DeliveryAssignment,
    DeliveryEarning,
    EtaPrediction,
    KitchenPhoto,
    MenuItem,
    Notification,
    Order,
    OrderEvent,
    OrderItem,
    OrderNumberCounter,
    OrderStatus,
    PrepLog,
    RescueListing,
    Restaurant,
    RestaurantStaff,
    Review,
    Rider,
    RiderStatus,
    Role,
    TrackingPoint,
    TrainingRow,
    User,
)
from app.images import service as images_service

DEMO_NOW = datetime.now(UTC)
DEMO_PASSWORD_HASH = hash_password(settings.demo_password)

CITY_CENTER = (17.4401, 78.3489)
NAMESPACE = uuid.UUID("6f1e9b7a-3c2d-4e5f-8a9b-0c1d2e3f4a5b")


def sid(name: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"foodflow:{name}")


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", ".", value.lower()).strip(".")


def email_for(name: str, kind: str | None = None) -> str:
    base = slug(name)
    return f"{base}@{kind}.foodflow.demo" if kind else f"{base}@foodflow.demo"


def phone_for(index: int) -> str:
    return f"+9190000{index:05d}"


DEMO_EMAILS = {
    "admin": "admin@foodflow.demo",
    "customer": "customer@foodflow.demo",
    "rider": "rider@foodflow.demo",
    "restaurant": "restaurant@foodflow.demo",
}


CURATED_CUSTOMERS = [
    {
        "name": "Asha Rao",
        "lat": 17.4410,
        "lng": 78.3490,
        "budget": "medium",
        "diet": "veg",
    },
    {
        "name": "Ravi Kumar",
        "lat": 17.4361,
        "lng": 78.3512,
        "budget": "low",
        "diet": None,
    },
    {
        "name": "Meera Shah",
        "lat": 17.4455,
        "lng": 78.3450,
        "budget": "high",
        "diet": "veg",
    },
]

CURATED_RIDERS = [
    {"name": "Arjun", "lat": 17.4425, "lng": 78.3470, "vehicle": "bike", "capacity": 2},
    {"name": "Priya", "lat": 17.4380, "lng": 78.3520, "vehicle": "scooter", "capacity": 2},
    {"name": "Kiran", "lat": 17.4448, "lng": 78.3510, "vehicle": "bike", "capacity": 2},
    {"name": "Sneha", "lat": 17.4370, "lng": 78.3460, "vehicle": "cycle", "capacity": 1},
]

RESTAURANTS = [
    {
        "name": "Spice Route",
        "lat": 17.4460,
        "lng": 78.3540,
        "cuisine": ["north_indian", "biryani"],
        "avg_prep_min": 18,
        "capacity_per_hr": 40,
        "rating": "4.5",
        "menu": [
            ("Butter Chicken", "289.00", "mains", False, 3, ["curry", "chicken"]),
            ("Paneer Butter Masala", "249.00", "mains", True, 2, ["curry", "paneer"]),
            ("Chicken Biryani", "319.00", "rice", False, 3, ["biryani", "chicken"]),
            ("Garlic Naan", "69.00", "breads", True, 1, ["bread"]),
        ],
    },
    {
        "name": "Dosa Junction",
        "lat": 17.4352,
        "lng": 78.3448,
        "cuisine": ["south_indian", "breakfast"],
        "avg_prep_min": 12,
        "capacity_per_hr": 60,
        "rating": "4.3",
        "menu": [
            ("Masala Dosa", "129.00", "breakfast", True, 1, ["dosa", "veg"]),
            ("Idli Sambar", "99.00", "breakfast", True, 1, ["idli", "veg"]),
            ("Ghee Podi Dosa", "149.00", "breakfast", True, 2, ["dosa", "ghee"]),
        ],
    },
    {
        "name": "Pasta La Vista",
        "lat": 17.4425,
        "lng": 78.3402,
        "cuisine": ["italian", "continental"],
        "avg_prep_min": 20,
        "capacity_per_hr": 30,
        "rating": "4.1",
        "menu": [
            ("Penne Alfredo", "279.00", "pasta", True, 2, ["pasta", "creamy"]),
            ("Chicken Lasagna", "349.00", "baked", False, 3, ["pasta", "chicken"]),
            ("Margherita Pizza", "259.00", "pizza", True, 2, ["pizza", "cheese"]),
        ],
    },
    {
        "name": "Wok This Way",
        "lat": 17.4498,
        "lng": 78.3441,
        "cuisine": ["chinese", "asian"],
        "avg_prep_min": 16,
        "capacity_per_hr": 45,
        "rating": "4.0",
        "menu": [
            ("Veg Hakka Noodles", "199.00", "noodles", True, 2, ["noodles", "veg"]),
            ("Chilli Chicken", "269.00", "starters", False, 2, ["chicken", "spicy"]),
            ("Veg Fried Rice", "189.00", "rice", True, 1, ["rice", "veg"]),
        ],
    },
    {
        "name": "The Burger Lab",
        "lat": 17.4335,
        "lng": 78.3562,
        "cuisine": ["american", "fast_food"],
        "avg_prep_min": 10,
        "capacity_per_hr": 70,
        "rating": "3.9",
        "menu": [
            ("Classic Veg Burger", "179.00", "burgers", True, 1, ["burger", "veg"]),
            ("Crispy Chicken Burger", "229.00", "burgers", False, 2, ["burger", "chicken"]),
            ("Loaded Fries", "149.00", "sides", True, 1, ["fries", "cheese"]),
        ],
    },
    {
        "name": "Curry & Co",
        "lat": 17.4471,
        "lng": 78.3590,
        "cuisine": ["north_indian", "curry"],
        "avg_prep_min": 22,
        "capacity_per_hr": 35,
        "rating": "4.2",
        "menu": [
            ("Dal Makhani", "219.00", "mains", True, 2, ["dal", "veg"]),
            ("Rogan Josh", "329.00", "mains", False, 3, ["mutton", "curry"]),
            ("Jeera Rice", "159.00", "rice", True, 1, ["rice", "veg"]),
        ],
    },
    {
        "name": "Sushi Bay",
        "lat": 17.4388,
        "lng": 78.3615,
        "cuisine": ["japanese"],
        "avg_prep_min": 25,
        "capacity_per_hr": 25,
        "rating": "4.4",
        "menu": [
            ("Avocado Maki", "299.00", "sushi", True, 2, ["sushi", "veg"]),
            ("Salmon Nigiri", "379.00", "sushi", False, 2, ["sushi", "fish"]),
            ("Miso Soup", "129.00", "soups", True, 1, ["soup", "veg"]),
        ],
    },
    {
        "name": "Cafe Mocha",
        "lat": 17.4420,
        "lng": 78.3525,
        "cuisine": ["cafe", "desserts"],
        "avg_prep_min": 8,
        "capacity_per_hr": 50,
        "rating": "4.6",
        "menu": [
            ("Cold Coffee", "149.00", "drinks", True, 1, ["coffee", "cold"]),
            ("Chocolate Brownie", "169.00", "desserts", True, 1, ["brownie", "chocolate"]),
            ("Cheese Toastie", "139.00", "snacks", True, 1, ["sandwich", "cheese"]),
        ],
    },
]

CUISINE_MENUS: dict[str, list[tuple[str, str, str, bool, int, list[str]]]] = {
    "north_indian": [
        ("Paneer Tikka Masala", "269.00", "mains", True, 2, ["paneer", "curry"]),
        ("Chicken Korma", "309.00", "mains", False, 3, ["chicken", "curry"]),
        ("Tandoori Roti", "39.00", "breads", True, 1, ["bread"]),
        ("Veg Pulao", "179.00", "rice", True, 1, ["rice", "veg"]),
    ],
    "south_indian": [
        ("Rava Dosa", "139.00", "breakfast", True, 2, ["dosa"]),
        ("Ven Pongal", "119.00", "breakfast", True, 1, ["rice", "ghee"]),
        ("Curd Rice", "99.00", "rice", True, 1, ["rice", "curd"]),
        ("Medu Vada", "89.00", "snacks", True, 1, ["vada"]),
    ],
    "biryani": [
        ("Hyderabadi Chicken Biryani", "329.00", "rice", False, 3, ["biryani", "chicken"]),
        ("Veg Dum Biryani", "259.00", "rice", True, 2, ["biryani", "veg"]),
        ("Mutton Biryani", "389.00", "rice", False, 3, ["biryani", "mutton"]),
        ("Mirchi Ka Salan", "89.00", "sides", True, 1, ["curry"]),
    ],
    "chinese": [
        ("Chicken Manchurian", "249.00", "starters", False, 2, ["chicken", "indo_chinese"]),
        ("Veg Schezwan Rice", "209.00", "rice", True, 2, ["rice", "spicy"]),
        ("Chicken Noodles", "229.00", "noodles", False, 2, ["noodles", "chicken"]),
        ("Spring Rolls", "149.00", "starters", True, 1, ["fried"]),
    ],
    "italian": [
        ("Spaghetti Arrabbiata", "259.00", "pasta", True, 2, ["pasta", "spicy"]),
        ("Chicken Alfredo Pasta", "329.00", "pasta", False, 2, ["pasta", "creamy"]),
        ("Farmhouse Pizza", "299.00", "pizza", True, 2, ["pizza", "veg"]),
        ("Garlic Breadsticks", "119.00", "sides", True, 1, ["bread"]),
    ],
    "fast_food": [
        ("Veg Cheese Burger", "189.00", "burgers", True, 1, ["burger", "veg"]),
        ("Chicken Zinger Burger", "239.00", "burgers", False, 2, ["burger", "chicken"]),
        ("Peri Peri Fries", "129.00", "sides", True, 1, ["fries", "spicy"]),
        ("Cold Coffee Shake", "119.00", "drinks", True, 1, ["coffee"]),
    ],
    "desserts": [
        ("Belgian Chocolate Waffle", "199.00", "desserts", True, 2, ["waffle", "chocolate"]),
        ("New York Cheesecake", "229.00", "desserts", True, 2, ["cake"]),
        ("Brownie Sundae", "179.00", "desserts", True, 1, ["brownie", "ice_cream"]),
        ("Filter Coffee", "79.00", "drinks", True, 1, ["coffee"]),
    ],
}

GENERATED_RESTAURANTS: list[tuple[str, list[str], str, int, int, str]] = [
    ("Biryani Bhavan", ["biryani", "north_indian"], "biryani", 20, 38, "4.2"),
    ("Tandoori Junction", ["north_indian", "biryani"], "north_indian", 19, 40, "4.0"),
    ("Andhra Mess", ["south_indian", "andhra"], "south_indian", 14, 55, "4.3"),
    ("Madras Tiffin Room", ["south_indian", "breakfast"], "south_indian", 11, 65, "4.4"),
    ("Dragon Wok", ["chinese", "asian"], "chinese", 15, 45, "3.9"),
    ("Sichuan Street", ["chinese", "noodles"], "chinese", 17, 42, "4.1"),
    ("Bella Napoli", ["italian", "pizza"], "italian", 21, 30, "4.5"),
    ("Pizza Piazza", ["italian", "fast_food"], "italian", 16, 50, "4.0"),
    ("Grill & Griddle", ["american", "fast_food"], "fast_food", 13, 60, "4.2"),
    ("Burger Barn", ["fast_food", "burgers"], "fast_food", 9, 75, "3.8"),
    ("Sweet Cravings", ["desserts", "cafe"], "desserts", 8, 55, "4.6"),
    ("Melting Pot Cafe", ["cafe", "desserts"], "desserts", 10, 48, "4.3"),
    ("Paradise Point", ["biryani", "north_indian"], "biryani", 23, 35, "4.4"),
    ("Chutneys & Co", ["south_indian", "snacks"], "south_indian", 13, 60, "4.1"),
    ("Golden Dragon Express", ["chinese", "fast_food"], "chinese", 14, 55, "3.7"),
    ("Trattoria Roma", ["italian", "continental"], "italian", 24, 28, "4.5"),
    ("The Wrap Shack", ["fast_food", "rolls"], "fast_food", 8, 80, "3.9"),
    ("Sugar & Spice", ["desserts", "bakery"], "desserts", 9, 50, "4.7"),
    ("Nawabi Kitchen", ["north_indian", "mughlai"], "north_indian", 25, 32, "4.3"),
    ("Coastal Curry House", ["south_indian", "seafood"], "south_indian", 18, 45, "4.2"),
    ("Noodle Theory", ["chinese", "asian"], "chinese", 16, 48, "4.0"),
    ("Cafe Velvet", ["cafe", "desserts"], "desserts", 7, 60, "4.5"),
]

FIRST_NAMES = [
    "Aditya",
    "Ananya",
    "Bhavya",
    "Chetan",
    "Divya",
    "Farhan",
    "Gaurav",
    "Harini",
    "Imran",
    "Jahnavi",
    "Karthik",
    "Lakshmi",
    "Manish",
    "Nandini",
    "Omkar",
    "Pooja",
    "Rohit",
    "Sanya",
    "Tarun",
]
LAST_NAMES = ["Reddy", "Naidu", "Verma"]

EXTRA_RIDER_NAMES = [
    "Vikram",
    "Anjali",
    "Suresh",
    "Deepa",
    "Farooq",
    "Nisha",
    "Ramesh",
    "Kavya",
    "Imtiaz",
    "Latha",
    "Manoj",
    "Pallavi",
    "Srinivas",
    "Tejaswi",
    "Yash",
    "Zoya",
]


def _scatter(rng: random.Random, km: float = 4.2, min_km: float = 0.4) -> tuple[float, float]:
    distance = rng.uniform(min_km, km)
    bearing = rng.uniform(0, 2 * math.pi)
    lat_delta = (distance / 111.0) * math.cos(bearing)
    lng_delta = (distance / (111.0 * math.cos(math.radians(CITY_CENTER[0])))) * math.sin(bearing)
    return round(CITY_CENTER[0] + lat_delta, 6), round(CITY_CENTER[1] + lng_delta, 6)


def _build_restaurants() -> list[dict]:
    rng = random.Random(2024)
    entries = [dict(restaurant) for restaurant in RESTAURANTS]
    for name, cuisine, menu_key, prep, capacity, rating in GENERATED_RESTAURANTS:
        lat, lng = _scatter(rng)
        entries.append(
            {
                "name": name,
                "lat": lat,
                "lng": lng,
                "cuisine": cuisine,
                "avg_prep_min": prep,
                "capacity_per_hr": capacity,
                "rating": rating,
                "menu": CUISINE_MENUS[menu_key],
            }
        )
    return entries


def _build_customers() -> list[dict]:
    rng = random.Random(2025)
    entries = [dict(customer) for customer in CURATED_CUSTOMERS]
    budgets = ["low", "medium", "high"]
    diets = [None, "veg", None, "eggetarian"]
    for first in FIRST_NAMES:
        for last in LAST_NAMES:
            lat, lng = _scatter(rng)
            index = len(entries)
            entries.append(
                {
                    "name": f"{first} {last}",
                    "lat": lat,
                    "lng": lng,
                    "budget": budgets[index % len(budgets)],
                    "diet": diets[index % len(diets)],
                }
            )
    return entries


def _build_riders() -> list[dict]:
    rng = random.Random(2026)
    entries = [dict(rider) for rider in CURATED_RIDERS]
    vehicles = ["bike", "scooter", "bike", "scooter", "cycle"]
    for index, name in enumerate(EXTRA_RIDER_NAMES):
        lat, lng = _scatter(rng, km=3.5, min_km=0.2)
        vehicle = vehicles[index % len(vehicles)]
        entries.append(
            {
                "name": name,
                "lat": lat,
                "lng": lng,
                "vehicle": vehicle,
                "capacity": 1 if vehicle == "cycle" else 2,
            }
        )
    return entries


ALL_RESTAURANTS = _build_restaurants()

# Two brands cooked in one cloud kitchen (5 m apart), so the shared-kitchen
# check has a real case to find. The Wrap Shack discloses it; Burger Barn does not.
SHARED_KITCHEN = ("The Wrap Shack", "Burger Barn")
DISCLOSED_CLOUD_KITCHENS = {"The Wrap Shack"}
_wrap = next(r for r in ALL_RESTAURANTS if r["name"] == SHARED_KITCHEN[0])
_burger = next(r for r in ALL_RESTAURANTS if r["name"] == SHARED_KITCHEN[1])
_burger["lat"], _burger["lng"] = _wrap["lat"] + 0.00004, _wrap["lng"] + 0.00002

# Leave these dishes unmeasured so Portion Studio has live work in the demo.
UNMEASURED_DEMO_DISHES = {("Spice Route", "Chicken Biryani"), ("Spice Route", "Garlic Naan")}


def _fssai_for(index: int) -> tuple[str | None, object]:
    """Synthetic, well-formed FSSAI numbers; a few are missing or expired on purpose."""
    today = DEMO_NOW.date()
    if index % 9 == 4:
        return None, None
    number = f"1{36:02d}{19 + index % 6:02d}{(index * 7) % 1000:03d}{100000 + index * 1337:06d}"
    if index % 11 == 7:
        return number, today - timedelta(days=30)
    return number, today + timedelta(days=200 + index * 9)


def _declared_portion(name: str, index: int) -> tuple[int | None, int | None, int | None]:
    """Declared grams/serves/pieces for a share of kitchens, from the dish table."""
    from app.nutrition.service import match_dish

    if index % 3 == 1:
        return None, None, None
    dish, _ = match_dish(name)
    if dish is None:
        return None, None, None
    serves = max(1, round(dish.portion_g / 350))
    return dish.portion_g, serves, dish.pieces
CUSTOMERS = _build_customers()
RIDERS = _build_riders()


async def seed(force: bool = False) -> None:
    factory = get_sessionmaker()
    async with factory() as session:
        existing = await session.scalar(select(func.count()).select_from(Restaurant))
        if existing:
            if not force:
                print("Seed data already present; use --force to reset.")
                return
            for model in (
                AiUsage,
                KitchenPhoto,
                PrepLog,
                Notification,
                Review,
                DeliveryEarning,
                TrackingPoint,
                EtaPrediction,
                DeliveryAssignment,
                CartItem,
                RescueListing,
                Cart,
                CustomerAddress,
                RestaurantStaff,
                OrderEvent,
                OrderItem,
                Order,
                OrderNumberCounter,
                TrainingRow,
                MenuItem,
                Restaurant,
                Rider,
                Customer,
                User,
            ):
                await session.execute(delete(model))
            await session.commit()

        session.add(
            User(
                id=sid("user:admin"),
                name="Ops Admin",
                role=Role.ADMIN,
                email=DEMO_EMAILS["admin"],
                phone=phone_for(9000),
                password_hash=DEMO_PASSWORD_HASH,
                is_active=True,
            )
        )

        customer_emails: dict[str, str] = {}
        for index, customer in enumerate(CUSTOMERS):
            email = (
                DEMO_EMAILS["customer"]
                if customer["name"] == CURATED_CUSTOMERS[0]["name"]
                else email_for(customer["name"], "customer")
            )
            customer_emails[customer["name"]] = email
            session.add(
                User(
                    id=sid(f"user:customer:{customer['name']}"),
                    name=customer["name"],
                    role=Role.CUSTOMER,
                    email=email,
                    phone=phone_for(index),
                    password_hash=DEMO_PASSWORD_HASH,
                    is_active=True,
                )
            )

        rider_emails: dict[str, str] = {}
        for index, rider in enumerate(RIDERS):
            email = (
                DEMO_EMAILS["rider"]
                if rider["name"] == CURATED_RIDERS[0]["name"]
                else email_for(rider["name"], "rider")
            )
            rider_emails[rider["name"]] = email
            session.add(
                User(
                    id=sid(f"user:rider:{rider['name']}"),
                    name=rider["name"],
                    role=Role.RIDER,
                    email=email,
                    phone=phone_for(1000 + index),
                    password_hash=DEMO_PASSWORD_HASH,
                    is_active=True,
                )
            )

        restaurant_emails: dict[str, str] = {}
        for index, restaurant in enumerate(ALL_RESTAURANTS):
            email = (
                DEMO_EMAILS["restaurant"]
                if restaurant["name"] == RESTAURANTS[0]["name"]
                else f"manager.{slug(restaurant['name'])}@foodflow.demo"
            )
            restaurant_emails[restaurant["name"]] = email
            session.add(
                User(
                    id=sid(f"user:manager:{restaurant['name']}"),
                    name=f"{restaurant['name']} Manager",
                    role=Role.RESTAURANT,
                    email=email,
                    phone=phone_for(2000 + index),
                    password_hash=DEMO_PASSWORD_HASH,
                    is_active=True,
                )
            )

        await session.flush()

        for index, customer in enumerate(CUSTOMERS):
            session.add(
                Customer(
                    user_id=sid(f"user:customer:{customer['name']}"),
                    home_lat=customer["lat"],
                    home_lng=customer["lng"],
                    budget_pref=customer["budget"],
                    diet_pref=customer["diet"],
                    daily_kcal_goal=1800 if index == 0 else None,
                )
            )
            session.add(
                CustomerAddress(
                    id=sid(f"address:{customer['name']}:home"),
                    customer_id=sid(f"user:customer:{customer['name']}"),
                    label="Home",
                    line1=f"{index + 1}-{index + 7}-{index + 12}, {customer['name']} Residency",
                    line2="Near City Centre Mall",
                    city="Hyderabad",
                    lat=customer["lat"],
                    lng=customer["lng"],
                    phone=phone_for(index),
                    is_default=True,
                )
            )

        for rider in RIDERS:
            demo_rider = rider["name"] == CURATED_RIDERS[0]["name"]
            session.add(
                Rider(
                    id=sid(f"rider:{rider['name']}"),
                    user_id=sid(f"user:rider:{rider['name']}"),
                    name=rider["name"],
                    lat=rider["lat"],
                    lng=rider["lng"],
                    status=RiderStatus.IDLE,
                    vehicle=rider["vehicle"],
                    capacity=rider["capacity"],
                    vehicle_registration=f"TS09AB{1000 + len(rider['name'])}",
                    verification_status="APPROVED",
                    average_rating=round(4.4 + (len(rider["name"]) % 6) / 10, 1),
                    last_seen_at=DEMO_NOW if demo_rider else None,
                )
            )

        for index, restaurant in enumerate(ALL_RESTAURANTS):
            session.add(
                Restaurant(
                    id=sid(f"restaurant:{restaurant['name']}"),
                    name=restaurant["name"],
                    lat=restaurant["lat"],
                    lng=restaurant["lng"],
                    cuisine=restaurant["cuisine"],
                    avg_prep_min=restaurant["avg_prep_min"],
                    capacity_per_hr=restaurant["capacity_per_hr"],
                    rating=Decimal(restaurant["rating"]),
                    rating_count=120 + index * 17,
                    address=f"{index + 3}, {restaurant['name']} Street, Hyderabad",
                    description=(
                        ", ".join(
                            cuisine.replace("_", " ").title()
                            for cuisine in restaurant["cuisine"]
                        )
                        + " favourites, freshly prepared in Hyderabad."
                    ),
                    min_order_value=Decimal("99.00" if index % 2 == 0 else "149.00"),
                    delivery_fee=Decimal(str(19 + (index % 3) * 10)),
                    is_active=True,
                    fssai_license=_fssai_for(index)[0],
                    fssai_valid_until=_fssai_for(index)[1],
                    kitchen_type=(
                        "cloud_kitchen"
                        if restaurant["name"] in DISCLOSED_CLOUD_KITCHENS
                        else "dine_in"
                    ),
                )
            )

        await session.flush()

        for restaurant in ALL_RESTAURANTS:
            session.add(
                RestaurantStaff(
                    id=sid(f"staff:{restaurant['name']}"),
                    restaurant_id=sid(f"restaurant:{restaurant['name']}"),
                    user_id=sid(f"user:manager:{restaurant['name']}"),
                )
            )

        for r_index, restaurant in enumerate(ALL_RESTAURANTS):
            restaurant_id = sid(f"restaurant:{restaurant['name']}")
            for name, price, category, veg, complexity, tags in restaurant["menu"]:
                grams, serves, pieces = (
                    (None, None, None)
                    if (restaurant["name"], name) in UNMEASURED_DEMO_DISHES
                    else _declared_portion(name, r_index)
                )
                session.add(
                    MenuItem(
                        id=sid(f"menu:{restaurant['name']}:{name}"),
                        restaurant_id=restaurant_id,
                        name=name,
                        price=Decimal(price),
                        category=category,
                        veg=veg,
                        prep_complexity=complexity,
                        tags=tags,
                        description=f"{name}, made fresh with {', '.join(tags)}.",
                        available=True,
                        portion_grams=grams,
                        portion_serves=serves,
                        portion_pieces=pieces,
                        portion_method="declared" if grams else "unknown",
                    )
                )

        await session.flush()
        await _seed_demo_orders(session)
        await session.commit()

    # Real, credited dish photos from Wikimedia Commons. Optional: the demo still
    # works offline, and `python -m app.images.service` can fetch them later.
    try:
        async with factory() as session:
            photos = await images_service.backfill(session)
        print(f"Real dish photos: {photos}")
    except Exception as exc:  # noqa: BLE001
        print(f"Skipped dish photos ({exc}); run python -m app.images.service later.")

    menu_count = sum(len(restaurant["menu"]) for restaurant in ALL_RESTAURANTS)
    print(
        f"Seeded {len(ALL_RESTAURANTS)} restaurants ({menu_count} menu items) with managers, "
        f"{len(CUSTOMERS)} customers, {len(RIDERS)} riders, 2 delivered demo orders and 1 admin."
    )


async def _seed_demo_orders(session) -> None:
    rider_id = sid(f"rider:{CURATED_RIDERS[0]['name']}")
    customer_id = sid(f"user:customer:{CURATED_CUSTOMERS[0]['name']}")
    demos = [
        {
            "key": "1",
            "restaurant": RESTAURANTS[0]["name"],
            "items": [("Butter Chicken", 1), ("Garlic Naan", 2)],
            "hours_ago": 49,
            "review": True,
            "distance": 3.2,
        },
        {
            "key": "2",
            "restaurant": RESTAURANTS[1]["name"],
            "items": [("Masala Dosa", 2), ("Idli Sambar", 1)],
            "hours_ago": 23,
            "review": False,
            "distance": 2.1,
        },
    ]
    menus = {
        (restaurant["name"], name): (Decimal(price), name)
        for restaurant in ALL_RESTAURANTS
        for name, price, *_ in restaurant["menu"]
    }
    latest_number_by_year: dict[int, int] = {}
    for demo in demos:
        placed_at = DEMO_NOW - timedelta(hours=demo["hours_ago"])
        delivered_at = placed_at + timedelta(minutes=38)
        subtotal = sum(
            menus[(demo["restaurant"], name)][0] * qty for name, qty in demo["items"]
        )
        delivery_fee = Decimal("29.00")
        tax = (subtotal * Decimal("0.05")).quantize(Decimal("0.01"))
        total = subtotal + delivery_fee + tax
        order_id = sid(f"order:demo:{demo['key']}")
        order = Order(
            id=order_id,
            order_number=f"FF-{placed_at.year}-{int(demo['key']):06d}",
            customer_id=customer_id,
            restaurant_id=sid(f"restaurant:{demo['restaurant']}"),
            rider_id=rider_id,
            status=OrderStatus.DELIVERED,
            placed_at=placed_at,
            promised_eta_at=placed_at + timedelta(minutes=36),
            actual_delivery_at=delivered_at,
            drop_lat=CURATED_CUSTOMERS[0]["lat"],
            drop_lng=CURATED_CUSTOMERS[0]["lng"],
            delivery_address="Asha Rao Residency, Near City Centre Mall, Hyderabad",
            customer_phone=phone_for(0),
            delivery_instructions="Leave at the door",
            subtotal=subtotal,
            delivery_fee=delivery_fee,
            discount=Decimal("0.00"),
            tax=tax,
            total_price=total,
            payment_method="COD",
            payment_status="PAID",
            estimated_prep_min=18,
            delivery_distance_km=demo["distance"],
        )
        latest_number_by_year[placed_at.year] = max(
            latest_number_by_year.get(placed_at.year, 0), int(demo["key"])
        )
        session.add(order)
        await session.flush()
        for name, qty in demo["items"]:
            price, item_name = menus[(demo["restaurant"], name)]
            session.add(
                OrderItem(
                    order_id=order_id,
                    menu_item_id=sid(f"menu:{demo['restaurant']}:{name}"),
                    name=item_name,
                    qty=qty,
                    unit_price=price,
                )
            )
        session.add_all(
            [
                OrderEvent(
                    order_id=order_id,
                    type="order_placed",
                    payload={"order_number": order.order_number, "total_price": str(total)},
                    created_at=placed_at,
                ),
                OrderEvent(
                    order_id=order_id,
                    type="order_delivered",
                    payload={"rider_name": CURATED_RIDERS[0]["name"]},
                    created_at=delivered_at,
                ),
            ]
        )
        session.add(
            EtaPrediction(
                order_id=order_id,
                predicted_minutes=36.0,
                lower_bound_minutes=31.0,
                upper_bound_minutes=41.0,
                prediction_source="model",
                actual_minutes=38.0,
                created_at=placed_at,
            )
        )
        await session.flush()
        session.add(
            DeliveryAssignment(
                id=sid(f"assignment:demo:{demo['key']}"),
                order_id=order_id,
                rider_id=rider_id,
                status="COMPLETED",
                offered_at=placed_at + timedelta(minutes=12),
                accepted_at=placed_at + timedelta(minutes=12.5),
                expires_at=placed_at + timedelta(minutes=14),
                arrived_restaurant_at=placed_at + timedelta(minutes=20),
                pickup_at=placed_at + timedelta(minutes=22),
                arrived_customer_at=delivered_at,
                completed_at=delivered_at,
                estimated_pickup_min=8.0,
                estimated_delivery_min=10.0,
            )
        )
        session.add(
            DeliveryEarning(
                order_id=order_id,
                rider_id=rider_id,
                amount=Decimal("45.00" if demo["key"] == "1" else "38.50"),
                distance_km=demo["distance"],
                created_at=delivered_at,
            )
        )
        if demo["review"]:
            session.add(
                Review(
                    order_id=order_id,
                    customer_id=customer_id,
                    restaurant_id=sid(f"restaurant:{demo['restaurant']}"),
                    rider_id=rider_id,
                    restaurant_rating=5,
                    quantity_feedback="as_described",
                    rider_rating=5,
                    comment="Hot, fresh and delivered ahead of the promised ETA.",
                    created_at=delivered_at + timedelta(minutes=5),
                )
            )

    for year, next_value in latest_number_by_year.items():
        session.add(OrderNumberCounter(year=year, next_value=next_value))


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the FoodFlow AI demo city.")
    parser.add_argument("--force", action="store_true", help="delete existing data first")
    args = parser.parse_args()
    asyncio.run(seed(force=args.force))


if __name__ == "__main__":
    main()
