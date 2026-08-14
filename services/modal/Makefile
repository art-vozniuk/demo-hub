# Thin wrappers around the per-app deploy/preload scripts and the modal CLI.
# These are run BY A HUMAN — production `main` deploys normally go through
# .github/workflows/deploy-modal.yml; this is the manual escape hatch and the
# dev (laptop) workflow. `modal` reads MODAL_ENVIRONMENT from the environment,
# so each target sets it per-invocation and prod/dev never cross-contaminate.
#
# Works from anywhere: `make -C services/modal <target>`.

# Absolute path to this directory (recipes must run from here so `modal serve`
# can resolve `from common...`; deploy.py chdirs itself, but stay consistent).
MODAL_DIR := $(patsubst %/,%,$(dir $(realpath $(lastword $(MAKEFILE_LIST)))))
REPO_ROOT := $(realpath $(MODAL_DIR)/../..)

# Prod model apps. All of them are endpoint-less (invoked by name through the
# gateway), so they cost nothing against the 8-web-function workspace cap —
# only the gateway's own submit+poll pair does. See docs/DEPLOY.md.
PROD_APPS := flux sharp trellis flux_t2i transcriber

.PHONY: help deploy-prod deploy-prod-flux-opt deploy-prod-gateway \
        setup-dev-env preload-dev deploy-dev serve-gateway-dev

help:
	@echo "Modal deploy wrappers (run by a human; never automated for dev):"
	@echo ""
	@echo "  Production (env=main) — usually CI (.github/workflows/deploy-modal.yml):"
	@echo "    make deploy-prod           deploy $(PROD_APPS) into main"
	@echo "    make deploy-prod-flux-opt  deploy flux_opt into main (0 web fns, experimental)"
	@echo "    make deploy-prod-gateway   deploy the gateway into main (the only web fns)"
	@echo ""
	@echo "  Dev (env=dev) — laptop against docker-compose.local.yml:"
	@echo "    make setup-dev-env         create the dev environment + dev secrets (interactive)"
	@echo "    make preload-dev           download flux weights into the dev volume"
	@echo "    make deploy-dev            deploy flux_opt into dev (gateway resolves it by name)"
	@echo "    make serve-gateway-dev     modal serve the gateway in dev (ephemeral, hot-reload)"
	@echo ""
	@echo "  Full runbook: docs/DEPLOY.md"

# ---- production (env=main) -------------------------------------------------

deploy-prod:
	@cd "$(MODAL_DIR)" && for app in $(PROD_APPS); do \
		echo "==> deploy $$app -> main"; \
		MODAL_ENVIRONMENT=main python "$$app/deploy.py" || exit $$?; \
	done

deploy-prod-flux-opt:
	cd "$(MODAL_DIR)" && MODAL_ENVIRONMENT=main python flux_opt/deploy.py

# Every model app is endpoint-less now, so the gateway's submit+poll pair is
# the workspace's entire web-function spend (2 of 8) and this is deployable.
# Deploy it AFTER the model apps: its ROUTES resolve them by name.
deploy-prod-gateway:
	cd "$(MODAL_DIR)" && MODAL_ENVIRONMENT=main python gateway/deploy.py

# ---- dev (env=dev) ---------------------------------------------------------

setup-dev-env:
	bash "$(REPO_ROOT)/scripts/setup-modal-dev.sh"

preload-dev:
	cd "$(MODAL_DIR)" && MODAL_ENVIRONMENT=dev python flux_opt/preload.py

deploy-dev:
	cd "$(MODAL_DIR)" && MODAL_ENVIRONMENT=dev python flux_opt/deploy.py

# `modal serve` endpoints are per-session and ephemeral, so they do NOT count
# against the 8-web-function cap — the gateway runs fine in dev. Prints the
# submit/poll URLs to paste into services/dispatch/.env.docker.
serve-gateway-dev:
	cd "$(MODAL_DIR)" && MODAL_ENVIRONMENT=dev modal serve gateway/app.py
