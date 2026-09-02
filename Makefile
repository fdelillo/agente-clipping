# El CLI de docker no está en el PATH de las shells no-login en esta Mac
# (vive en ~/.docker/bin). Exportamos el PATH en cada target para no
# depender de que la shell interactiva ya lo tenga configurado.
DOCKER_PATH := export PATH="$$HOME/.docker/bin:$$PATH";

.PHONY: help up down logs ps test reset sh-api

help: ## Muestra esta ayuda
	@echo "Targets disponibles:"
	@echo "  make up       - levanta los 4 servicios (build + detached)"
	@echo "  make down     - baja los servicios (conserva los volúmenes)"
	@echo "  make logs     - sigue los logs de todos los servicios"
	@echo "  make ps       - estado de los servicios"
	@echo "  make test     - corre la suite de pytest dentro del contenedor api"
	@echo "  make reset    - baja TODO y borra los volúmenes (pierde los datos)"
	@echo "  make sh-api   - abre una shell dentro del contenedor api"

up: ## Levanta los 4 servicios (build + detached)
	$(DOCKER_PATH) docker compose up -d --build

down: ## Baja los servicios, conserva los volúmenes (datos de postgres/n8n)
	$(DOCKER_PATH) docker compose down

logs: ## Sigue los logs de todos los servicios
	$(DOCKER_PATH) docker compose logs -f

ps: ## Estado de los servicios (incluye el resultado de los healthchecks)
	$(DOCKER_PATH) docker compose ps

test: ## Corre la suite de pytest dentro del contenedor api
	$(DOCKER_PATH) docker compose exec api uv run pytest -q

reset: ## Baja TODO y borra los volúmenes: postgres y n8n vuelven a cero
	@echo "ATENCIÓN: esto borra los datos de postgres y el estado de n8n (down -v)."
	$(DOCKER_PATH) docker compose down -v

sh-api: ## Abre una shell dentro del contenedor api
	$(DOCKER_PATH) docker compose exec api bash
