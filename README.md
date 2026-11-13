# FoodFlow AI

FoodFlow is a simulated food-delivery marketplace and operations lab. Customers browse
kitchens, build a cart and track an order; restaurants work a live pass; riders accept
dispatch offers and complete deliveries; operators watch the city in motion.

Rider location uses browser GPS when permission is granted, with a clearly labelled
simulated fallback. ETAs, recommendation reasons, traffic, payments and model metrics
remain simulated. The event log, order state machine, dispatch rules and fallbacks are
real.

## Stack

- FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2
- PostgreSQL 16, Redis 7
- React 19, TypeScript, Vite 6, Tailwind CSS 4
- Docker Compose for the full stack

## Quick start

Create a `.env` file from `.env.example` and set `AUTH_SECRET` to a new random value.
Docker Compose intentionally refuses to start without it.

```sh
docker compose up --build -d
docker compose exec api python -m app.seed --force
```

- Web: http://localhost:5173
- API: http://localhost:8000
- API docs: http://localhost:8000/docs
- API health: http://localhost:8000/healthz

The API container runs `alembic upgrade head` on boot. `--force` reseeds the demo city
and deletes existing local data, so use it on development databases only.

### Demo accounts

All demo accounts use password `demo1234`.

| Role | Email | Lands on |
| --- | --- | --- |
| Customer | `customer@foodflow.demo` | `/#/customer` |
| Rider | `rider@foodflow.demo` | `/#/rider` |
| Restaurant manager | `restaurant@foodflow.demo` | `/#/restaurant` |
| Operator | `admin@foodflow.demo` | `/#/ops` |

The seed adds 30 restaurants, 113 menu items, 60 customers, 20 riders, addresses,
two delivered orders, ETA predictions, earnings and an admin account.

## Demo flow

1. Sign in as the customer, open a kitchen, add two dishes and apply `WELCOME50`.
2. Check out with UPI demo or cash on delivery. The order opens live tracking.
3. Sign in as the restaurant manager and move the ticket through Accept, Start preparing
   and Mark ready.
4. Sign in as the rider, allow browser location access, open Offers, accept the pickup
   and run the delivery steps. Customer tracking and the restaurant pass update over
   WebSocket as GPS arrives.
5. Sign back in as the customer to watch tracking, then rate the order.
6. Sign in as the operator to inspect the live board, dispatch, delay monitor, learning
   loop and recommendation affinity.

Use separate browser profiles or sign out between roles. The marketplace stores one
session at a time in browser storage.

Coupons: `WELCOME50` (flat ₹50 over ₹299), `FEAST10` (10% off, capped) and `FREEDEL`
(free delivery over ₹149). The cart accepts one kitchen at a time.

## Roles and routes

| Route | Purpose |
| --- | --- |
| `/#/login` | Sign in, register a customer, or pick a demo role |
| `/#/customer` | Discovery, restaurant menu, cart, checkout, orders, profile |
| `/#/customer/restaurants/:id` | Restaurant detail and menu |
| `/#/customer/orders/:id` | Live tracking, cancellation, review and reorder |
| `/#/rider` | Shift, offers, live delivery, earnings and history |
| `/#/restaurant` | Live pass, menu availability/prices, insights |
| `/#/ops` | Existing operations console (admin only) |

Hash routing keeps the app usable without a server-side history fallback.

## API surface

All marketplace endpoints live under `/api/v1`:

- `/auth` login, register, session
- `/restaurants` browse, detail, menu, recommendations
- `/me`, `/me/addresses`, `/cart`, `/checkout`, `/coupons`
- `/orders` customer list/detail/cancel/review/reorder/tracking
- `/rider` profile, availability, GPS location updates, offers, assignment actions,
  earnings, history
- `/restaurant` live orders and actions, menu, analytics, insights
- `/notifications`

Realtime:

- `GET`/WS `/ws/notifications?token=...` authenticated notification stream
- WS `/ws/v1/orders/{order_id}?token=...` authenticated customer order stream
- WS `/ws/v1/restaurant/orders?token=...` authenticated restaurant stream for order
  transitions and assigned-rider locations
- WS `/ws/orders/{order_id}?token=...` authenticated, admin-only legacy operations stream

Authenticated rider updates post to `/api/v1/rider/location` with `source: "gps"` or
`"simulated"` and optional `accuracy_m`. The server appends a tracking point for every
active assignment and publishes `rider_location` to each order channel, so the customer
map, rider dashboard and operations board update in parallel.

Use the interactive docs at `/docs` for schemas and request bodies.

## Tests

```sh
docker compose run --rm api python -m pytest -q
docker compose run --rm --no-deps api ruff check app tests
docker compose run --rm --no-deps web npm run lint
docker compose --profile simulator run --rm simulator python -m pytest simulator/tests -q
```

Production frontend build:

```sh
cd frontend
npm run build
```

The backend suite covers ordering, routing, ETA, realtime fanout, assignment, monitoring,
learning, recommendations, marketplace auth/order flows and cancellation cleanup. The
simulator suite covers city generation and training-row output.

## Simulator, ETA and learning

```sh
# Generate synthetic history, train or inspect the model through the ops console
docker compose --profile simulator run --rm simulator python -m simulator.generate_history --orders 30000 --seed 42 --replace
docker compose run --rm api python /ml/train_eta.py

# Run a simulated rush hour against the API
docker compose --profile simulator run --rm simulator python -m simulator.run --duration 120 --speed 60 --scenario rush_hour
```

ETA calls fall back to the deterministic estimator in `backend/app/eta/fallback.py` if a
model cannot load or inference fails. Marketplace dispatch limits offers to fresh riders
within 5 km, ranks the nearest candidates by route ETA, and advances an expired 20-second
offer to the next eligible rider. No rider available produces an operator notification
instead of blocking the order.

## Notes and limitations

- Customer, rider and restaurant screens use a MapLibre map. The route endpoint uses OSRM
  when configured and otherwise returns a clearly labelled haversine estimate; prepare an
  `osrm-data/region.osrm` extract to enable road geometry and road-time dispatch.
- Redis pub/sub is used for WebSocket fanout. If Redis is down, in-process delivery keeps
  working without failing writes.
- Rider movement uses live browser GPS when granted; denied or unavailable GPS falls back
  to simulated movement. UPI payments, traffic, ETAs and recommendations are simulated,
  and every prediction surface is labelled in the UI.
- Docker Desktop must be running for the commands above. On Windows PowerShell, use the
  `docker compose` commands directly; `make` is optional.
