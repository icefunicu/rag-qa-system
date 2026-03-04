.PHONY: test build up down fmt

test:
	cd go-api && go test ./...
	cd py-rag-service && python -m pytest -q
	cd py-worker && python -m pytest -q

build:
	docker compose build

up:
	docker compose up -d --build

down:
	docker compose down

fmt:
	cd go-api && go fmt ./...

