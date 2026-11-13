COMPOSE ?= docker compose

.PHONY: up down logs build test lint ps seed seed-reset migrate revision osrm-up sim sim-history sim-test train-eta

up:
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

build:
	$(COMPOSE) build

test:
	$(COMPOSE) build api
	$(COMPOSE) run --rm api python -m pytest -q
	$(COMPOSE) run --rm --no-deps web npm run lint

lint:
	$(COMPOSE) run --rm --no-deps api ruff check app tests
	$(COMPOSE) run --rm --no-deps web npm run lint

seed:
	$(COMPOSE) exec api python -m app.seed

seed-reset:
	$(COMPOSE) exec api python -m app.seed --force

migrate:
	$(COMPOSE) exec api alembic upgrade head

revision:
	$(COMPOSE) exec api alembic revision --autogenerate -m "$(m)"

osrm-up:
	$(COMPOSE) --profile osrm up -d osrm

SIM_ARGS ?= --duration 120 --speed 60 --scenario normal

sim:
	$(COMPOSE) --profile simulator run --rm simulator python -m simulator.run $(SIM_ARGS)

sim-history:
	$(COMPOSE) --profile simulator run --rm simulator python -m simulator.generate_history --orders 30000 --seed 42 --replace

sim-test:
	$(COMPOSE) --profile simulator run --rm simulator python -m pytest simulator/tests -q

train-eta:
	$(COMPOSE) run --rm api python /ml/train_eta.py

ps:
	$(COMPOSE) ps
