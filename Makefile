# ── ETAA Makefile ────────────────────────────────────────────────────────────
.PHONY: help install migrate run worker beat bridge test lint docker-up docker-down

help:
	@echo ""
	@echo "ETAA – Available Commands"
	@echo "─────────────────────────────────────────────────"
	@echo "  make install      Install all dependencies"
	@echo "  make migrate      Run Django migrations"
	@echo "  make run          Start Django dev server (port 8000)"
	@echo "  make worker       Start Celery worker"
	@echo "  make beat         Start Celery beat scheduler"
	@echo "  make bridge       Start WhatsApp bridge (Node.js)"
	@echo "  make test         Run full test suite"
	@echo "  make lint         Run flake8 linter"
	@echo "  make superuser    Create Django admin superuser"
	@echo "  make docker-up    Start all services via Docker Compose"
	@echo "  make docker-down  Stop all Docker services"
	@echo ""

install:
	pip install -r requirements.txt
	cd bridge && npm install

migrate:
	python manage.py migrate

superuser:
	python manage.py createsuperuser

run:
	python manage.py runserver 0.0.0.0:8000

worker:
	celery -A etaa_core worker --loglevel=info --concurrency=4

beat:
	celery -A etaa_core beat --loglevel=info \
		--scheduler django_celery_beat.schedulers:DatabaseScheduler

bridge:
	cd bridge && node server.js

test:
	pytest tests/ -v --tb=short

coverage:
	coverage run -m pytest tests/ && coverage report -m && coverage html

lint:
	flake8 apps/ etaa_core/ tests/ --max-line-length=110 --exclude=migrations

docker-up:
	docker-compose up -d
	@echo "Services started. Check logs with: docker-compose logs -f"

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f --tail=100

shell:
	python manage.py shell

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete
	rm -rf .pytest_cache htmlcov .coverage
