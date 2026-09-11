.PHONY: dev worker migrate test lint seed frontend-dev

# All targets use `python -m` so they work regardless of OS or how the
# venv was activated (no bash-only `source .venv/bin/activate` assumptions).

dev:
	cd backend && python -m uvicorn app.main:app --reload

worker:
	cd backend && python -m worker.agent dev

migrate:
	cd backend && python -m alembic upgrade head

test:
	cd backend && python -m pytest

lint:
	cd backend && python -m ruff check .

seed:
	cd backend && python -m scripts.seed

frontend-dev:
	cd frontend && npm run dev
