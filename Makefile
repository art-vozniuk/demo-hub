include .env

SHELL := /bin/bash

COMPUTE_IMAGE_NAME := compute
CORE_IMAGE_NAME := core
PLATFORM := linux/amd64
REGISTRY := ghcr.io

TAG := $(shell date +"%Y-%m-%d-%H%M%S")
COMPUTE_IMAGE := $(REGISTRY)/$(GITHUB_USER)/$(COMPUTE_IMAGE_NAME):$(TAG)
COMPUTE_IMAGE_LATEST := $(REGISTRY)/$(GITHUB_USER)/$(COMPUTE_IMAGE_NAME):latest
CORE_IMAGE := $(REGISTRY)/$(GITHUB_USER)/$(CORE_IMAGE_NAME):$(TAG)
CORE_IMAGE_LATEST := $(REGISTRY)/$(GITHUB_USER)/$(CORE_IMAGE_NAME):latest
IMAGE_REPO := $(REGISTRY)/$(GITHUB_USER)/$(COMPUTE_IMAGE_NAME)

# Compute service
build-compute:
	docker build --platform $(PLATFORM) -f services/compute/Dockerfile -t $(COMPUTE_IMAGE) --build-arg BUILD_TAG=$(TAG) .

build-compute-debug:
	docker buildx build --no-cache --progress=plain --platform $(PLATFORM) -f services/compute/Dockerfile -t $(COMPUTE_IMAGE) .

build-compute-with-env:
	@if [ ! -f services/compute/.env ]; then echo "Error: services/compute/.env not found"; exit 1; fi
	docker build --platform $(PLATFORM) -f services/compute/Dockerfile -t $(COMPUTE_IMAGE) --build-arg BUILD_TAG=$(TAG) --secret id=env,src=services/compute/.env .

login-ghcr:
	echo "$(GHCR_TOKEN)" | docker login $(REGISTRY) -u "$(GITHUB_USER)" --password-stdin

build-and-push-compute: build-compute login-ghcr
	docker push $(COMPUTE_IMAGE)
	@echo "Successfully pushed: $(COMPUTE_IMAGE)"

run-last-local-compute:
	$(eval LAST_TAG := $(shell docker images --format "{{.Repository}}:{{.Tag}}" | grep "$(IMAGE_REPO)" | head -n 1))
	docker rm -f compute || true
	docker run --name compute --env-file services/compute/.env $(LAST_TAG)

run-latest-compute:
	docker pull --platform linux/amd64 $(COMPUTE_IMAGE_LATEST)
	docker rm -f compute || true
	docker run --name compute --gpus all $(COMPUTE_IMAGE_LATEST)

# Core service
build-core:
	docker build --platform $(PLATFORM) -f services/core/Dockerfile -t $(CORE_IMAGE) --build-arg BUILD_TAG=$(TAG) .

run-core-uvicorn:
	@echo "Starting core service via uvicorn (with .env)..."
	PYTHONPATH="$(PWD)" \
	set -a && source .env && set +a && \
	uvicorn services.core.main:app --host 0.0.0.0 --port 8081 --reload

run-latest-core:
	docker pull $(CORE_IMAGE_LATEST)
	docker rm -f core || true
	docker run --name core --env-file services/core/.env -p 8081:8081 $(CORE_IMAGE_LATEST)

# Database migrations
DB_CMD = PYTHONPATH="$(PWD)" \
	set -a && source services/core/.env && set +a && \
	alembic -c services/common/database/alembic.ini

db-migrate:
	@echo "Running migrations..."
	@$(DB_CMD) upgrade head

db-rollback:
	@echo "Rolling back..."
	@$(DB_CMD) downgrade -1

db-create-migration:
	@if [ -z "$(name)" ]; then echo "Missing migration name. Use: make db-create-migration name='add new table'"; exit 1; fi
	@$(DB_CMD) revision --autogenerate -m "$(name)"

db-history:
	@$(DB_CMD) history

db-current:
	@$(DB_CMD) current

# Tests
test-core:
	@echo "Running core tests..."
	cd services/common && uv pip install -e .
	cd services/core && uv pip install -e ".[dev]"
	cd services/core && PYTHONPATH="$(PWD)" uv run pytest tests/ -v

test-compute:
	@echo "Running compute tests..."
	cd services/common && uv pip install -e .
	cd services/compute && uv pip install -e ".[dev]"
	cd services/compute && PYTHONPATH="$(PWD)" uv run pytest tests/ -v

test: test-core test-compute
	@echo "All tests passed!"

lint:
	@echo "Running ruff checks..."
	ruff check services/core services/compute services/common --exclude services/external
	ruff format --check services/core services/compute services/common --exclude services/external
	@echo "Linting passed!"

lint-fix:
	@echo "Auto-fixing ruff issues..."
	ruff check --fix services/core services/compute services/common --exclude services/external
	ruff format services/core services/compute services/common --exclude services/external
	@echo "Linting fixes applied!"
