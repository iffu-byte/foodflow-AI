"""Approximate nutrition per 100 g for common Indian and delivery dishes.

Values are typical restaurant-style figures compiled for this project from
standard food-composition references (IFCT 2017 and USDA FoodData Central
style values) and rounded. Restaurant recipes vary, so the app always labels
them as estimates. Each entry: match phrases, kcal, protein, carbs, fat, fibre
(g per 100 g), typical delivery portion in grams, pieces (if counted), allergens.
"""

from typing import NamedTuple


class Dish(NamedTuple):
    keys: tuple[str, ...]
    kcal: float
    protein: float
    carbs: float
    fat: float
    fibre: float
    portion_g: int
    pieces: int | None
    allergens: tuple[str, ...]


D = Dish

DISHES: list[Dish] = [
    # Rice and biryani
    D(("chicken biryani", "chicken dum biryani"), 170, 9.0, 20.0, 6.0, 0.8, 400, None, ("dairy",)),
    D(("mutton biryani", "gosht biryani"), 185, 9.5, 19.0, 7.8, 0.8, 400, None, ("dairy",)),
    D(("egg biryani",), 165, 6.5, 21.0, 6.0, 0.9, 380, None, ("egg", "dairy")),
    D(("prawn biryani", "fish biryani"), 160, 8.5, 21.0, 4.8, 0.8, 380, None, ("shellfish",)),
    D(("veg biryani", "veg dum biryani", "vegetable biryani"), 150, 3.5, 24.0, 4.5, 1.8, 380, None,
      ("dairy",)),
    D(("biryani",), 165, 7.0, 21.0, 5.8, 1.0, 400, None, ("dairy",)),
    D(("mandi",), 175, 10.0, 21.0, 5.5, 0.6, 450, None, ()),
    D(("veg pulao", "pulao", "pulav"), 140, 3.0, 24.0, 3.8, 1.5, 300, None, ()),
    D(("jeera rice",), 150, 2.8, 28.0, 3.0, 0.6, 250, None, ("dairy",)),
    D(("curd rice", "dahi chawal"), 120, 3.5, 18.0, 3.8, 0.4, 300, None, ("dairy",)),
    D(("lemon rice",), 160, 2.8, 27.0, 4.5, 1.0, 280, None, ("peanuts",)),
    D(("schezwan rice", "szechuan rice"), 175, 3.8, 27.5, 5.6, 1.3, 320, None, ("soy", "gluten")),
    D(("chicken fried rice",), 180, 8.0, 24.0, 5.8, 1.0, 330, None, ("soy", "egg")),
    D(("fried rice",), 165, 3.8, 27.0, 4.8, 1.2, 320, None, ("soy",)),
    D(("khichdi",), 120, 4.5, 19.0, 2.8, 2.5, 300, None, ("dairy",)),
    D(("plain rice", "steamed rice"), 130, 2.7, 28.0, 0.3, 0.4, 250, None, ()),
    # Curries and mains
    D(("butter chicken", "murgh makhani"), 155, 12.5, 5.5, 9.5, 0.8, 250, None, ("dairy", "nuts")),
    D(("chicken korma",), 165, 12.0, 6.0, 10.5, 1.0, 250, None, ("dairy", "nuts")),
    D(("chicken tikka masala",), 150, 12.5, 6.0, 8.5, 1.0, 250, None, ("dairy",)),
    D(("chicken curry", "chicken masala", "kadai chicken", "kadhai chicken"), 145, 13.0, 4.5, 8.5,
      1.2, 250, None, ()),
    D(("rogan josh", "mutton curry", "mutton masala"), 160, 13.5, 4.5, 10.0, 1.0, 250, None,
      ("dairy",)),
    D(("egg curry",), 130, 7.5, 5.5, 8.8, 1.2, 250, None, ("egg",)),
    D(("fish curry",), 120, 12.0, 4.0, 6.2, 0.8, 250, None, ("fish",)),
    D(("prawn curry", "prawn masala"), 130, 12.5, 4.5, 7.0, 0.8, 250, None, ("shellfish",)),
    D(("paneer butter masala", "shahi paneer"), 205, 8.5, 8.0, 15.5, 1.2, 250, None,
      ("dairy", "nuts")),
    D(("paneer tikka masala", "kadai paneer", "kadhai paneer"), 195, 9.5, 7.5, 14.0, 1.4, 250, None,
      ("dairy",)),
    D(("palak paneer",), 150, 7.5, 6.0, 11.0, 2.2, 250, None, ("dairy",)),
    D(("paneer tikka",), 260, 15.0, 6.5, 19.5, 1.0, 200, 6, ("dairy",)),
    D(("dal makhani",), 130, 5.5, 13.5, 6.2, 3.8, 250, None, ("dairy",)),
    D(("dal tadka", "dal fry", "yellow dal"), 110, 5.8, 14.0, 3.6, 3.5, 250, None, ("dairy",)),
    D(("chole", "chana masala"), 150, 6.5, 19.0, 5.5, 5.5, 250, None, ()),
    D(("rajma",), 125, 6.0, 16.5, 4.0, 5.0, 250, None, ()),
    D(("mirchi ka salan",), 140, 3.0, 9.0, 10.5, 2.5, 150, None, ("peanuts", "sesame")),
    D(("haleem",), 140, 10.0, 11.0, 6.0, 2.0, 300, None, ("gluten", "dairy")),
    D(("sambar",), 65, 3.0, 9.5, 1.8, 2.5, 250, None, ()),
    # Breads
    D(("butter naan", "garlic naan", "naan"), 300, 8.5, 48.0, 8.0, 2.0, 90, 1, ("gluten", "dairy")),
    D(("tandoori roti", "roti", "chapati", "phulka"), 265, 8.5, 52.0, 2.5, 6.5, 40, 1, ("gluten",)),
    D(("aloo paratha", "paratha"), 270, 6.0, 38.0, 10.5, 4.0, 120, 1, ("gluten", "dairy")),
    D(("bhatura", "chole bhature"), 290, 7.5, 40.0, 11.5, 3.5, 350, None, ("gluten",)),
    D(("pav bhaji",), 180, 4.5, 24.0, 7.5, 3.0, 350, None, ("gluten", "dairy")),
    # South Indian
    D(("ghee podi dosa", "podi dosa"), 210, 4.5, 27.0, 9.5, 2.2, 160, 1, ("dairy", "sesame")),
    D(("rava dosa",), 190, 3.5, 27.0, 7.5, 1.2, 150, 1, ("gluten",)),
    D(("masala dosa",), 175, 3.8, 26.0, 6.5, 2.0, 220, 1, ()),
    D(("dosa", "uttapam"), 165, 3.9, 27.0, 4.5, 1.5, 160, 1, ()),
    D(("idli sambar", "idli"), 95, 3.5, 17.0, 1.2, 2.0, 300, 3, ()),
    D(("medu vada", "vada"), 300, 8.5, 31.0, 15.5, 4.0, 100, 2, ()),
    D(("ven pongal", "pongal"), 145, 4.0, 20.0, 5.5, 1.5, 250, None, ("dairy", "nuts")),
    D(("upma",), 150, 3.5, 23.0, 5.0, 1.5, 250, None, ("gluten",)),
    D(("poha",), 160, 3.0, 28.0, 4.2, 1.5, 250, None, ("peanuts",)),
    D(("filter coffee",), 70, 2.5, 9.0, 2.6, 0.0, 150, None, ("dairy",)),
    # Starters and Indo-Chinese
    D(("chilli chicken", "chicken 65", "dragon chicken"), 220, 17.0, 10.0, 12.5, 0.8, 220, None,
      ("gluten", "soy")),
    D(("chicken manchurian",), 210, 14.5, 12.0, 11.5, 0.9, 250, None, ("gluten", "soy")),
    D(("veg manchurian", "gobi manchurian"), 190, 4.0, 20.0, 10.5, 2.5, 250, None,
      ("gluten", "soy")),
    D(("chicken tikka", "tandoori chicken", "kebab", "kabab"), 165, 24.0, 3.0, 6.5, 0.5, 250, 6,
      ("dairy",)),
    D(("spring roll",), 250, 4.5, 30.0, 12.5, 2.2, 150, 4, ("gluten", "soy")),
    D(("samosa",), 290, 5.0, 32.0, 16.0, 3.0, 120, 2, ("gluten",)),
    D(("veg momo", "veg momos"), 170, 5.0, 28.0, 4.0, 2.0, 180, 6, ("gluten", "soy")),
    D(("chicken momo", "chicken momos", "momo"), 185, 10.0, 22.0, 6.0, 1.2, 180, 6,
      ("gluten", "soy")),
    D(("chicken noodles", "egg noodles"), 175, 8.0, 23.0, 5.8, 1.4, 320, None,
      ("gluten", "soy", "egg")),
    D(("hakka noodles", "noodles", "chowmein", "chow mein"), 165, 4.0, 26.0, 5.0, 1.8, 300, None,
      ("gluten", "soy")),
    # Italian
    D(("margherita pizza", "cheese pizza"), 250, 11.0, 30.0, 9.5, 2.0, 300, 6, ("gluten", "dairy")),
    D(("farmhouse pizza", "veggie pizza", "veg pizza"), 235, 10.0, 29.5, 8.5, 2.3, 350, 6,
      ("gluten", "dairy")),
    D(("chicken pizza", "pepperoni pizza"), 260, 12.5, 28.0, 10.5, 1.8, 350, 6,
      ("gluten", "dairy")),
    D(("pizza",), 245, 10.5, 29.5, 9.5, 2.0, 320, 6, ("gluten", "dairy")),
    D(("garlic bread", "garlic breadstick", "breadstick"), 320, 8.5, 42.0, 13.0, 2.0, 120, 4,
      ("gluten", "dairy")),
    D(("chicken alfredo",), 190, 10.5, 19.0, 8.0, 1.0, 340, None, ("gluten", "dairy")),
    D(("alfredo", "white sauce pasta"), 185, 6.0, 22.0, 8.5, 1.2, 320, None, ("gluten", "dairy")),
    D(("arrabbiata", "red sauce pasta", "marinara"), 150, 5.0, 26.0, 3.2, 2.2, 320, None,
      ("gluten",)),
    D(("lasagna", "lasagne"), 165, 9.5, 14.5, 7.8, 1.2, 350, None, ("gluten", "dairy", "egg")),
    D(("pasta", "penne", "spaghetti"), 165, 5.5, 25.0, 5.0, 1.8, 320, None, ("gluten",)),
    # Burgers, sandwiches, sides
    D(("zinger burger", "crispy chicken burger", "chicken burger"), 258, 12.3, 24.5, 12.2, 1.5, 225,
      1, ("gluten", "egg")),
    D(("veg cheese burger", "cheese burger"), 255, 8.5, 29.0, 11.5, 2.2, 200, 1,
      ("gluten", "dairy")),
    D(("veg burger", "burger"), 230, 6.0, 31.0, 9.0, 2.5, 180, 1, ("gluten", "dairy")),
    D(("shawarma",), 215, 12.0, 20.0, 9.5, 1.6, 250, 1, ("gluten", "dairy", "sesame")),
    D(("wrap", "kathi roll", "roll"), 220, 9.0, 25.0, 9.0, 2.0, 220, 1, ("gluten",)),
    D(("cheese toastie", "grilled sandwich", "sandwich"), 300, 12.0, 30.0, 14.5, 1.8, 160, 1,
      ("gluten", "dairy")),
    D(("loaded fries",), 300, 6.0, 33.0, 16.0, 3.0, 220, None, ("dairy",)),
    D(("peri peri fries", "french fries", "fries"), 310, 3.5, 40.0, 15.0, 3.6, 180, None, ()),
    # Desserts and drinks
    D(("brownie sundae",), 300, 4.5, 38.0, 15.0, 1.2, 200, None,
      ("gluten", "dairy", "egg", "nuts")),
    D(("chocolate brownie", "brownie"), 430, 5.5, 55.0, 21.0, 2.4, 100, 1,
      ("gluten", "dairy", "egg", "nuts")),
    D(("waffle",), 330, 6.0, 42.0, 15.5, 1.5, 180, 1, ("gluten", "dairy", "egg")),
    D(("cheesecake",), 320, 5.5, 25.5, 22.5, 0.4, 120, 1, ("gluten", "dairy", "egg")),
    D(("gulab jamun",), 320, 4.5, 50.0, 12.0, 0.5, 100, 2, ("gluten", "dairy")),
    D(("kheer", "payasam"), 145, 4.0, 21.0, 5.0, 0.3, 150, None, ("dairy", "nuts")),
    D(("ice cream",), 210, 3.5, 24.0, 11.0, 0.5, 120, None, ("dairy",)),
    D(("cake", "pastry"), 360, 5.0, 50.0, 16.0, 1.0, 100, 1, ("gluten", "dairy", "egg")),
    D(("cold coffee", "coffee shake"), 95, 3.0, 13.5, 3.2, 0.2, 300, None, ("dairy",)),
    D(("mango shake", "milkshake", "shake"), 110, 3.0, 17.0, 3.2, 0.5, 300, None, ("dairy",)),
    D(("lassi",), 100, 3.2, 14.5, 3.0, 0.0, 300, None, ("dairy",)),
    # Japanese and soups
    D(("avocado maki", "veg maki", "maki"), 140, 3.0, 25.0, 3.5, 2.0, 180, 6, ("soy", "sesame")),
    D(("salmon nigiri", "nigiri", "sushi"), 165, 8.5, 24.0, 3.8, 0.3, 160, 4, ("fish", "soy")),
    D(("miso soup",), 40, 3.0, 4.0, 1.4, 0.6, 250, None, ("soy",)),
    D(("tomato soup", "soup"), 55, 1.5, 7.5, 2.2, 1.0, 250, None, ("dairy",)),
    D(("caesar salad", "salad"), 120, 5.0, 7.0, 8.5, 2.2, 220, None, ("dairy", "egg")),
]

CATEGORY_DEFAULTS: dict[str, tuple[float, float, float, float, float, int]] = {
    "mains": (150, 9.0, 8.0, 9.5, 1.5, 250),
    "rice": (160, 4.5, 24.0, 5.0, 1.0, 320),
    "starters": (220, 12.0, 12.0, 13.0, 1.5, 220),
    "breads": (290, 8.0, 48.0, 7.0, 3.0, 80),
    "breakfast": (170, 4.0, 26.0, 5.5, 2.0, 220),
    "snacks": (280, 6.0, 30.0, 15.0, 2.5, 150),
    "sides": (200, 3.0, 20.0, 12.0, 2.5, 150),
    "pizza": (245, 10.5, 29.5, 9.5, 2.0, 320),
    "burgers": (245, 9.0, 27.0, 11.0, 2.0, 200),
    "pasta": (175, 6.0, 24.0, 6.0, 1.8, 320),
    "noodles": (165, 4.5, 26.0, 5.0, 1.8, 300),
    "desserts": (330, 5.0, 42.0, 16.0, 1.0, 120),
    "drinks": (85, 2.5, 13.0, 2.5, 0.2, 300),
    "soups": (50, 2.0, 6.0, 2.0, 0.8, 250),
    "sushi": (150, 6.0, 25.0, 3.5, 1.0, 170),
    "baked": (240, 9.0, 25.0, 11.0, 1.5, 250),
}
GENERIC_DEFAULT = (180, 6.0, 22.0, 7.5, 1.5, 250)

ALLERGEN_WORDS: dict[str, tuple[str, ...]] = {
    "dairy": ("paneer", "cheese", "cream", "butter", "ghee", "curd", "dahi", "milk", "lassi",
              "malai", "alfredo", "makhani", "raita", "shake", "kheer"),
    "gluten": ("naan", "roti", "bread", "pizza", "pasta", "burger", "noodle", "maida", "wheat",
               "paratha", "kulcha", "bhatura", "samosa", "roll", "wrap", "sandwich", "toast",
               "cake", "brownie", "waffle", "momo", "manchurian", "rava", "upma"),
    "egg": ("egg", "omelette", "mayo", "mayonnaise"),
    "nuts": ("cashew", "kaju", "almond", "badam", "pista", "walnut", "korma", "nut"),
    "peanuts": ("peanut", "groundnut", "salan"),
    "shellfish": ("prawn", "shrimp", "crab", "lobster"),
    "fish": ("fish", "salmon", "tuna", "pomfret", "surmai", "nigiri"),
    "soy": ("soy", "tofu", "miso", "schezwan", "manchurian", "hakka"),
    "sesame": ("sesame", "til", "podi", "tahini"),
}
