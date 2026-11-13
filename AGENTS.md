# FoodFlow AI: agent rules

- Stack: FastAPI (async), SQLAlchemy 2, Alembic, Pydantic v2, Postgres, Redis; React+Vite+TS+Tailwind.
- Product: delivery marketplace (customer, rider, restaurant) plus the original operations
  console. Rider location uses browser GPS when granted, with a labelled simulated
  fallback. All predictions and fallback movement are simulated and labelled in the UI.
- Modular monolith. Never import across modules except through each module's service.py.
- All order state changes go through domain/state_machine.transition(). Never update status directly.
- Every external dependency (routing, weather, redis) sits behind an interface with a fallback.
- ETA must never fail: wrap model calls, fall back to eta/fallback.py.
- Write tests with each feature. Run `make test` before declaring done.
- Small commits, one phase at a time. Do not start the next phase until acceptance checks pass.
- Pin dependency versions in requirements.txt / package-lock.
- All UI predictions show a 'simulated data' label.

## Build order

Follow the blueprint phase plan: skeleton, domain/ordering, routing, simulator, ETA,
realtime tracking, assignment, delay monitor, learning loop, recommendations, ops dashboard.
Do not pull work forward from a later phase.

## Commands

- `make up` / `docker compose up --build -d` - full stack (api, db, redis, web)
- `make down` - stop the stack
- `make test` - backend pytest and frontend typecheck inside containers
- `make lint` - ruff + tsc
- `make sim-history` - generate 30k synthetic training rows from the seeded city
- `make sim SIM_ARGS="--duration 120 --speed 60 --scenario rush_hour"` - live simulator
- `make sim-test` - simulator unit tests
- `make train-eta` - train the ETA model bundle from training_rows
- Backend locally (installed deps): `cd backend; python -m pytest -q`
- Frontend locally: `cd frontend; npm install; npm run dev`
- Docker equivalents (no `make` needed):
  - `docker compose run --rm api python -m pytest -q`
  - `docker compose run --rm --no-deps api ruff check app tests`
  - `docker compose run --rm --no-deps web npm run lint`
  - `docker compose exec api python -m app.seed --force` - reset the demo city
  - `docker compose up -d --build web` - rebuild after frontend source changes
  - `docker compose restart api` - reload backend source (the API has no autoreload)

## Marketplace and auth

- Roles: lowercase `customer`, `rider`, `restaurant`, `admin`. Bearer tokens are HMAC
  signed; passwords are PBKDF2-HMAC-SHA256.
- Demo accounts (password `demo1234`): `customer@foodflow.demo` (Asha),
  `rider@foodflow.demo` (Arjun), `restaurant@foodflow.demo` (Spice Route manager),
  `admin@foodflow.demo`.
- Frontend routes: `/#/login`, `/#/customer`, `/#/rider`, `/#/restaurant`, `/#/ops`.
  `/ops` is admin-only; customers, riders and restaurant staff cannot cross role routes.
- The session lives in `localStorage` (`foodflow.token`, `foodflow.user`). `useSession`
  listens for `foodflow.session` and `storage` events, so automated browser tests that
  write storage directly must dispatch `new Event("foodflow.session")` and set the hash.
- Marketplace APIs live under `/api/v1`: `auth`, `restaurants`, `me`, `addresses`,
  `cart`, `checkout`, `coupons`, `orders`, `rider`, `restaurant`, `notifications`.
- Auth WebSockets: `/ws/notifications?token=...` and
  `/ws/v1/orders/{order_id}?token=...`.
- Rider location: `POST /api/v1/rider/location` with `source: "gps" | "simulated"` and
  optional `accuracy_m`. The rider UI uses `navigator.geolocation.watchPosition` and
  throttles updates; denied/unavailable GPS falls back to simulation.
- Order rules: one kitchen per cart; tax 5%; default delivery fee ₹29; free delivery over
  ₹499; `WELCOME50`, `FEAST10`, `FREEDEL`; orders start `PLACED`; any transition goes
  through the domain state machine; cancellation is blocked after pickup.
- Customer cancellation expires open offers and cancels accepted assignments; do not
  change assignment status directly outside the existing cleanup path.
- Demo seed: 30 restaurants, 113 menu items, 60 customers, 20 riders, 2 delivered orders
  and one admin. Use `python -m app.seed --force` for a clean demo.

## Realtime

- `WS /ws/orders/{order_id}` streams `order_snapshot` first, then `order_event`,
  `rider_location` and periodic `heartbeat` messages.
- `rider_location` includes `location_source` and `location_accuracy_m`; fanout goes to
  every active assignment for the rider, so customer, rider and ops views stay aligned.
- Auth marketplace sockets are intended for the customer, rider and restaurant UIs.
- Fanout runs over Redis pub/sub (`REDIS_URL`); if Redis is down it degrades to
  in-process delivery without failing order writes.

## Ops console

- Web UI at http://localhost:5173: live board, dispatch, delay monitor, model registry,
  recommendations. Sign in as `admin@foodflow.demo`; the console is at `/#/ops`.
  `docker compose up -d web` starts it on its own.
- `GET /orders` supports `status` and `limit`; the live board also subscribes to the
  order WebSocket and follows every transition without polling.
- `GET /orders/{id}/candidates` / `POST /orders/{id}/assign` drive dispatch; `POST /monitor/scan`
  appends delay flags and events; `GET /learning/models` and `POST /learning/retrain`
  compare validation MAE and promote only improvements (force available).
- Recommendations: `GET /recommendations/restaurants/{customer_id}` and
  `GET /recommendations/menu/{customer_id}/{restaurant_id}` with reason strings.
- Every ETA/model/recommendation surface is labelled as simulated data.

## Verified environment

- Docker 29.x with Compose v5.x
- Local Python is 3.14; the supported backend runtime is Python 3.12 (Docker image).
  Run tests via `make test` or Docker unless you create a 3.12 virtualenv.
- Node 24 locally, Node 22 in the frontend image.

## Conventions

- Backend packages: `app/api`, `app/domain`, `app/eta`, `app/assignment`, `app/monitor`,
  `app/learning`, `app/routing`, `app/recs`, `app/realtime`.
- Every state change, ETA update, assignment, delay, and notification is an append-only
  `order_events` row.
- Timezone-aware UTC datetimes everywhere.
- No secrets in the repo; config through environment variables (see `.env.example`).
- All predictions trained on simulator data must be labelled as simulated in the UI.
