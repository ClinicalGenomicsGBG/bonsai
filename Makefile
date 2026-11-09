# Which NGP stack to run: dev or prod, e.g. `make up_detached NGP_ENV=prod`
NGP_ENV ?= dev
ENV_FILE ?= compose.ngp.$(NGP_ENV).env
COMPOSE_FILE ?= compose.ngp.$(NGP_ENV).yml

#
# TARGETS := help build debug_compose_up_wait_conditions down log_all_follow ps rebuild restart start up up_detached up_force_recreate up_force_recreate_detached
TARGETS := help build debug_compose_up_wait_conditions down log_all_follow ps rebuild restart restart_dr_jan_itor start up up_detached up_force_recreate up_force_recreate_detached

.PHONY: $(TARGETS)

PODMAN_COMPOSE := podman-compose

PODMAN_COMPOSE_OPTIONS := \
	--in-pod=false \
	--env-file $(ENV_FILE) \
	-f $(COMPOSE_FILE)


help: ## Show this help
	@echo "Usage: make <target> [NGP_ENV=dev|prod]"
	@echo "    NGP_ENV picks the stack (default: dev), e.g. \`make ps NGP_ENV=prod\`."
	@echo "    ENV_FILE and COMPOSE_FILE can also be set directly."
	@echo "    Now: $(COMPOSE_FILE) with $(ENV_FILE)"
	@echo
	@echo "Targets:"
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-34s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: podc
podc: ## Print the podman-compose command the targets use
	@echo "$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS)"


.PHONY: compose-services
compose-services: ## List the services in the compose file
	@$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) config --services

build: ## Build the images
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) build

debug_compose_up_wait_conditions: ## Show running `podman wait` processes (to debug depends_on conditions)
	pgrep -af "podman wait"

down: ## Stop and remove the containers
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) down

log_all_follow: ## Follow the logs of all containers
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) logs -lf

ps: ## List the containers
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) ps

rebuild: ## Rebuild everything: down, build, up -d
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) down
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) build
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) up -d

restart: ## Stop and start all containers
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) stop
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) start

restart_dr_jan_itor: ## Restart the cache cleanup container (dr_jan_itor)
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) restart dr_jan_itor

start: ## Start the existing containers
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) start

up: ## Create and start the containers, in the foreground
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) up

up_detached: ## Create and start the containers, in the background
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) up -d

up_force_recreate: ## Recreate and start all containers, in the foreground
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) up --force-recreate

up_force_recreate_detached: ## Recreate and start all containers, in the background
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) up --force-recreate -d


# # Catch-all target:
# %:
# 	@:
