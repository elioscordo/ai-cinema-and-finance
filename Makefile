.PHONY: help install migrate migrations run worker shell superuser clean \
        install-postgres install-redis redis-start redis-stop db-shell db-create \
        save_db_argo save_db_guillermo load_db_argo load_db_guillermo \
        db_new_argo db_new_guillermo ib-recreate refresh

SHELL := /bin/bash

# Allow passing positional arguments (e.g. make load_db_guillermo guill1)
ARG := $(word 2,$(MAKECMDGOALS))
$(if $(ARG),$(eval $(ARG):;@:))

help:
	@echo "Available commands:"
	@echo "  run                 - Start Django dev server"
	@echo "  worker              - Start Celery worker"
	@echo "  migrate             - Apply Django migrations"
	@echo "  migrations          - Create Django migrations"
	@echo "  shell               - Open Django shell"
	@echo "  superuser           - Create Django superuser"
	@echo "  install-postgres    - Install PostgreSQL and dev headers"
	@echo "  install-redis       - Install Redis server"
	@echo "  redis-start         - Start Redis server"
	@echo "  redis-stop          - Stop Redis server"
	@echo "  db-shell            - Open PostgreSQL psql shell"
	@echo "  db-create           - Create 'guillermo' database"
	@echo "  db_new_guillermo [n]- Create PostgreSQL database (default: guillermo)"
	@echo "  db_new_argo [n]     - Create PostgreSQL database (default: argo)"
	@echo "  save_db_guillermo   - Dump 'guillermo' to guillermo.sql"
	@echo "  save_db_argo        - Dump 'argo' to argo.sql"
	@echo "  load_db_guillermo [n]- Load guillermo.sql into database (e.g. make load_db_guillermo guill1)"
	@echo "  load_db_argo [n]    - Load argo.sql into database (e.g. make load_db_argo argo1)"
	@echo "  clean               - Remove python compiled files"
	@echo "  refresh             - Pull git, collectstatic, migrate, and restart services"
	@echo "  ib-recreate         - Force recreate stuck IB Gateway docker container"

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
	sudo -u postgres pg_dump guillermo > guillermo.sql

save_db_argo:
	sudo -u postgres pg_dump argo > argo.sql

load_db_guillermo:
	sudo -u postgres createdb $(or $(ARG),guillermo) 2>/dev/null || true
	sudo -u postgres psql -d $(or $(ARG),guillermo) < guillermo.sql

load_db_argo:
	sudo -u postgres createdb $(or $(ARG),argo) 2>/dev/null || true
	sudo -u postgres psql -d $(or $(ARG),argo) < argo.sql

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