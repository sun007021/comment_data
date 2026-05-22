.PHONY: db api collect collect-full embed init-db down logs

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
