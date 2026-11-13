# FoodFlow trust layer

Features added on top of the existing marketplace. All data is dynamic (Postgres, real orders, live map lookups). Nothing is copied from Swiggy or Zomato.

## Run

```sh
docker compose up --build -d          # this machine: DB published on 5433 via docker-compose.override.yml
docker compose exec api python -m app.seed --force
cd frontend && npm install && npm run dev   # http://localhost:5173
```

Optional keys in `.env`: `GEMINI_API_KEY` (portion photo cross-check, nutrition for unknown dishes) and `GOOGLE_MAPS_API_KEY` (Google photos/reviews of the kitchen). Without them, local methods and OpenStreetMap are used.

## Features

| Feature | Where | How it works |
| --- | --- | --- |
| Geofenced delivery OTP | Rider "Hand over with code", customer order page | 4-digit code is shown only to the customer. "Arrived" is allowed within 400 m of the pin and "Delivered" within 150 m plus the code. Five wrong codes lock the order. Proof is stored for "I didn't receive it" disputes. |
| Portion Studio | Restaurant > Portion Studio | Photo with a reference (₹10 coin, card, plate), container fill, kitchen scale or piece count gives grams with a range and confidence. Gemini cross-checks photos when a key is set. Published grams show on the menu with a "verified" badge. |
| Kitchen reality check | Restaurant page panel, Restaurant > Trust | Google Places (photos, reviews, hours) or OpenStreetMap (what is mapped at the pin). Results are cached for 7 days. Also checks the FSSAI number format, flags brands within 30 m (shared kitchen), and shows dated kitchen photos. |
| Trust score 0-100 | Cards, restaurant page | Licence 15, location 20, kitchen photos 10, portion transparency 20, customer quantity ratings 25, kitchen disclosure 10. Each part is explained. Ranking is never paid. |
| Calories by quantity | Menu chips, cart, Profile | Local dish table (per 100 g) scaled to the declared or measured grams, with allergens, filters, a daily goal and today's intake. AI is used at most once per unknown dish. |
| Rescue a Meal | Restaurant > Rescue, customer home strip | Kitchen logs portions cooked. The forecast is cooked minus sold minus pace × min(3 h, time to close). Prices fall linearly to a floor, and the price is locked under a row lock at checkout. |
| Shared ride (consent batching) | Checkout, rider offers | Only orders where the customer chose "shared" (up to ₹15 off delivery) are batched, from the same kitchen with drops ≤ 2.5 km apart and ≤ 12 min extra for the second drop. One pickup collects both bags, and drops follow the planned sequence. |
| Honest status and fair blame | Customer order page | Live stage ("no rider yet, 3 asked"), a live ETA, and a free-cancel offer when stuck. At delivery, lateness is split between kitchen, platform and rider. Platform or rider delays are credited automatically. |
| AI cost meter | Ops > AI cost meter | Every paid call and cache hit is logged with an estimated cost. A daily budget (`AI_DAILY_BUDGET_USD`) stops paid calls, and features fall back to local methods. |

Tests: `docker compose run --rm api python -m pytest -q` (156 passing). New tests are in `backend/tests/test_trust_layer.py`.
