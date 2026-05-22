.PHONY: db collect collect-full init-db down logs

db:
	docker compose up -d db

collect:
	docker compose run --rm collector collect --missions missions.yml --pr-limit 50

collect-full:
	docker compose run --rm collector collect --missions missions.yml --pr-limit 50 --full-refresh

init-db:
	docker compose run --rm collector init-db

down:
	docker compose down

logs:
	docker compose logs -f db
