.PHONY: help install migrate migrations run worker shell superuser clean \
        install-postgres install-redis redis-start redis-stop db-shell db-create \
        save_db_argo save_db_guillermo load_db_argo load_db_guillermo \
        db_new_argo db_new_guillermo ib-recreate refresh ib \
        local_push local_push_media local_push_historical local_push_dbs

SHELL := /bin/bash

# Load remote synchronization variables from root .env if present
-include .env
export

REMOTE_PORT ?= 22
REMOTE_PROJECT_DIR ?= /home/elio/projects/guillermo
REMOTE_MEDIA_DIR ?= /home/elio/media/guillermo

# Allow passing positional arguments without make treating them as missing targets
KNOWN_TARGETS := help install migrate migrations run worker shell superuser clean \
                 install-postgres install-redis redis-start redis-stop db-shell db-create \
                 save_db_argo save_db_guillermo load_db_argo load_db_guillermo \
                 db_new_argo db_new_guillermo ib-recreate refresh ib \
                 local_push local_push_media local_push_historical local_push_dbs
EXTRA_ARGS := $(filter-out $(KNOWN_TARGETS),$(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS)))
$(if $(EXTRA_ARGS),$(eval $(EXTRA_ARGS):;@:))
ARG := $(word 2,$(MAKECMDGOALS))

help:
	@echo "Available commands:"
	@echo "  run                   - Start Django dev server"
	@echo "  worker                - Start Celery worker"
	@echo "  migrate               - Apply Django migrations"
	@echo "  migrations            - Create Django migrations"
	@echo "  shell                 - Open Django shell"
	@echo "  superuser             - Create Django superuser"
	@echo "  install-postgres      - Install PostgreSQL and dev headers"
	@echo "  install-redis         - Install Redis server"
	@echo "  redis-start           - Start Redis server"
	@echo "  redis-stop            - Stop Redis server"
	@echo "  db-shell              - Open PostgreSQL psql shell"
	@echo "  db-create             - Create 'guillermo' database"
	@echo "  db_new_guillermo [n]  - Create PostgreSQL database (default: guillermo)"
	@echo "  db_new_argo [n]       - Create PostgreSQL database (default: argo)"
	@echo "  save_db_guillermo     - Dump 'guillermo' to project_guillermo/dbs/<YYYY_MM_DD>.sql"
	@echo "  save_db_argo          - Dump 'argo' to project_argo/dbs/<YYYY_MM_DD>.sql"
	@echo "  load_db_guillermo <f> - Load SQL dump from project_guillermo/dbs/<f> (e.g. make load_db_guillermo 2026_10_20.sql)"
	@echo "  load_db_argo <f>      - Load SQL dump from project_argo/dbs/<f> (e.g. make load_db_argo 2026_10_20.sql)"
	@echo "  local_push [target]   - Sync local data to remote server: media, historical, dbs, or all (default: all)"
	@echo "  clean                 - Remove python compiled files"
	@echo "  refresh               - Pull git, collectstatic, migrate, and restart services"
	@echo "  ib-recreate           - Force recreate stuck IB Gateway docker container"

install:
	pip install -r requirements.txt

migrate:
	python manage.py migrate

migrations:
	python manage.py makemigrations

run:
	python manage.py runserver

worker:
	celery -A project worker --loglevel=info

shell:
	python manage.py shell

superuser:
	python manage.py createsuperuser

install-postgres:
	sudo apt-get update && sudo apt-get install -y postgresql postgresql-contrib libpq-dev

install-redis:
	sudo apt-get update && sudo apt-get install -y redis-server

redis-start:
	sudo systemctl start redis-server

redis-stop:
	sudo systemctl stop redis-server

# Database operations
db-shell:
	sudo -u postgres psql

db-create:
	sudo -u postgres createdb guillermo

db_new_guillermo:
	sudo -u postgres createdb $(or $(ARG),guillermo)

db_new_argo:
	sudo -u postgres createdb $(or $(ARG),argo)

save_db_guillermo:
	@mkdir -p project_guillermo/dbs
	sudo -u postgres pg_dump guillermo > project_guillermo/dbs/$$(date +'%Y_%m_%d').sql

save_db_argo:
	@mkdir -p project_argo/dbs
	sudo -u postgres pg_dump argo > project_argo/dbs/$$(date +'%Y_%m_%d').sql

load_db_guillermo:
	@if [ -z "$(ARG)" ]; then \
		echo "Error: file name required. Usage: make load_db_guillermo <filename.sql> [dbname]"; \
		echo "Looking in project_guillermo/dbs/"; \
		exit 1; \
	fi
	@FILE_PATH="project_guillermo/dbs/$(ARG)"; \
	if [ ! -f "$$FILE_PATH" ]; then \
		echo "Error: file $$FILE_PATH not found."; \
		exit 1; \
	fi; \
	DB_TARGET="$(or $(word 3,$(MAKECMDGOALS)),guillermo)"; \
	echo "Loading $$FILE_PATH into database '$$DB_TARGET'..."; \
	sudo -u postgres createdb "$$DB_TARGET" 2>/dev/null || true; \
	sudo -u postgres psql -d "$$DB_TARGET" < "$$FILE_PATH"

load_db_argo:
	@if [ -z "$(ARG)" ]; then \
		echo "Error: file name required. Usage: make load_db_argo <filename.sql> [dbname]"; \
		echo "Looking in project_argo/dbs/"; \
		exit 1; \
	fi
	@FILE_PATH="project_argo/dbs/$(ARG)"; \
	if [ ! -f "$$FILE_PATH" ]; then \
		echo "Error: file $$FILE_PATH not found."; \
		exit 1; \
	fi; \
	DB_TARGET="$(or $(word 3,$(MAKECMDGOALS)),argo)"; \
	echo "Loading $$FILE_PATH into database '$$DB_TARGET'..."; \
	sudo -u postgres createdb "$$DB_TARGET" 2>/dev/null || true; \
	sudo -u postgres psql -d "$$DB_TARGET" < "$$FILE_PATH"

# -----------------------------------------------------------------------------
# Remote Synchronization (Local -> Remote)
# -----------------------------------------------------------------------------
check_remote_env:
	@if [ -z "$(REMOTE_HOST)" ] || [ -z "$(REMOTE_USER)" ]; then \
		echo "Error: REMOTE_HOST and REMOTE_USER must be set in .env"; \
		exit 1; \
	fi

local_push_media: check_remote_env
	@echo "==> Syncing media to $(REMOTE_USER)@$(REMOTE_HOST):$(REMOTE_MEDIA_DIR)..."
	ssh -p $(REMOTE_PORT) $(REMOTE_USER)@$(REMOTE_HOST) "mkdir -p $(REMOTE_MEDIA_DIR)"
	rsync -avz --progress -e "ssh -p $(REMOTE_PORT)" media/ $(REMOTE_USER)@$(REMOTE_HOST):$(REMOTE_MEDIA_DIR)/

local_push_historical: check_remote_env
	@echo "==> Syncing historical_data to $(REMOTE_USER)@$(REMOTE_HOST):$(REMOTE_PROJECT_DIR)/historical_data/..."
	ssh -p $(REMOTE_PORT) $(REMOTE_USER)@$(REMOTE_HOST) "mkdir -p $(REMOTE_PROJECT_DIR)/historical_data"
	rsync -avz --progress -e "ssh -p $(REMOTE_PORT)" historical_data/ $(REMOTE_USER)@$(REMOTE_HOST):$(REMOTE_PROJECT_DIR)/historical_data/

local_push_dbs: check_remote_env
	@echo "==> Syncing project_argo/dbs to $(REMOTE_USER)@$(REMOTE_HOST):$(REMOTE_PROJECT_DIR)/project_argo/dbs/..."
	ssh -p $(REMOTE_PORT) $(REMOTE_USER)@$(REMOTE_HOST) "mkdir -p $(REMOTE_PROJECT_DIR)/project_argo/dbs"
	rsync -avz --progress -e "ssh -p $(REMOTE_PORT)" project_argo/dbs/ $(REMOTE_USER)@$(REMOTE_HOST):$(REMOTE_PROJECT_DIR)/project_argo/dbs/

local_push: check_remote_env
	@TARGET="$(ARG)"; \
	case "$$TARGET" in \
		media) \
			$(MAKE) local_push_media ;; \
		historical|historical_data) \
			$(MAKE) local_push_historical ;; \
		dbs|argo_dbs) \
			$(MAKE) local_push_dbs ;; \
		""|all|project) \
			$(MAKE) local_push_media && \
			$(MAKE) local_push_historical && \
			$(MAKE) local_push_dbs ;; \
		*) \
			echo "Unknown target '$$TARGET'."; \
			echo "Usage: make local_push [media | historical | dbs | all]"; \
			exit 1 ;; \
	esac

clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	rm -rf staticfiles

refresh:
	git pull
	source venv/bin/activate && \
	python manage.py collectstatic --noinput && \
	python manage.py migrate && \
	sudo systemctl restart celery.service && \
	sudo systemctl restart celery-beat.service && \
	sudo systemctl restart nginx.service && \
	sudo systemctl restart gunicorn

ib:
	@$(MAKE) -C argo recreate