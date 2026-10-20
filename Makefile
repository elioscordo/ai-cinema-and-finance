.PHONY: help install migrate migrations run worker shell superuser clean \
        install-postgres install-redis redis-start redis-stop db-shell db-create \
        save_db_argo save_db_guillermo load_db_argo load_db_guillermo \
        db_new_argo db_new_guillermo ib-recreate refresh

SHELL := /bin/bash

# Allow passing positional arguments without make treating them as missing targets
KNOWN_TARGETS := help install migrate migrations run worker shell superuser clean \
                 install-postgres install-redis redis-start redis-stop db-shell db-create \
                 save_db_argo save_db_guillermo load_db_argo load_db_guillermo \
                 db_new_argo db_new_guillermo ib-recreate refresh ib
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