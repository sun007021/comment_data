.PHONY: db api collect collect-full embed init-db down logs prod-up prod-down prod-logs prod-build

db:
	docker compose up -d db

api:
	docker compose up --build api

collect:
	docker compose run --rm collector collect --missions missions.yml --pr-limit 50

collect-full:
	docker compose run --rm collector collect --missions missions.yml --pr-limit 50 --full-refresh

embed:
	docker compose run --rm collector embed-documents

init-db:
	docker compose run --rm collector init-db

down:
	docker compose down

logs:
	docker compose logs -f db

# --- 배포(nginx) ---
prod-build:
	docker compose -f docker-compose.prod.yml build

prod-up:
	docker compose -f docker-compose.prod.yml up -d --build

prod-down:
	docker compose -f docker-compose.prod.yml down

prod-logs:
	docker compose -f docker-compose.prod.yml logs -f nginx api
