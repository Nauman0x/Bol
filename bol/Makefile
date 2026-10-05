.PHONY: dev worker migrate revision seed test lint up down

dev:
	cd backend && . .venv/bin/activate && uvicorn app.main:app --reload

# Calls (test calls included) need this running alongside `make dev` — the API
# only creates the LiveKit room and dispatch; a worker process must be up to
# actually join it and run the voice pipeline.
worker:
	cd backend && . .venv/bin/activate && python -m worker.agent dev

migrate:
	cd backend && . .venv/bin/activate && alembic upgrade head

revision:
	cd backend && . .venv/bin/activate && alembic revision --autogenerate -m "$(m)"

seed:
	cd backend && . .venv/bin/activate && python -m scripts.seed

test:
	cd backend && . .venv/bin/activate && pytest

lint:
	cd backend && . .venv/bin/activate && ruff check .

up:
	docker compose up --build

down:
	docker compose down
