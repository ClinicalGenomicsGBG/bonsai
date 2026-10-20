ENV_FILE ?= development.env

TARGETS := help build debug_compose_up_wait_conditions down log_all_follow ps rebuild restart start up up_detached up_force_recreate up_force_recreate_detached


.PHONY: $(TARGETS)

PODMAN_COMPOSE := podman-compose

PODMAN_COMPOSE_OPTIONS := \
	--in-pod=false \
	--env-file $(ENV_FILE) \
	-f docker-compose.yml \
	-f compose.yml


help:
	@echo "!!! This command is incomplete !!!"
	@echo "Set the ENV_FILE to use with \`ENV_FILE=</path/to/file>\`,"
	@echo "    e.g. \`make ps ENV_FILE=production.env\`"
	@echo
	@echo "Usage: make <target>>"
	@echo "Targets: $(TARGETS)"
	@echo "    rebuild:"
	@echo "        podman-compose down"
	@echo "        podman-compose build"
	@echo "        podman-compose up -d"


.PHONY: podc
podc:
	@echo "$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS)"


.PHONY: compose-services
compose-services:
	@$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) config --services

build:
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) build

debug_compose_up_wait_conditions:
	pgrep -af "podman wait"

down:
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) down

log_all_follow:
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) logs -lf

ps:
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) ps

rebuild:
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) down
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) build
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) up -d

restart:
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) stop
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) start

restart_dr_jan_itor:
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) restart dr_jan_itor

start:
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) start

up:
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) up

up_detached:
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) up -d

up_force_recreate:
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) up --force-recreate

up_force_recreate_detached:
	$(PODMAN_COMPOSE) $(PODMAN_COMPOSE_OPTIONS) up --force-recreate -d


# # Catch-all target:
# %:
# 	@:
