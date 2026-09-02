# Social Listening — Fase 1

Captura menciones por tag/keyword en X e Instagram, las analiza con un LLM
(sentimiento, tema, justificación) y arma un informe. Ver `PLAN.md` para el
plan completo y `proyecto_social_listening_agente.md` para la visión de
producto.

Este repo es también un vehículo para aprender **Docker** y **n8n**: el
reparto de trabajo entre n8n (orquestación) y la API en Python (dominio) es
deliberado, no el camino más corto.

**Estado actual: Etapa 0 (andamiaje).** El único endpoint funcional es
`GET /health`. Los adapters de fuentes, el análisis con LLM y los informes
llegan en las etapas siguientes.

## Requisitos

- Docker y Docker Compose (ya instalados en esta máquina; el CLI vive en
  `~/.docker/bin`, ver "Gotchas" abajo).
- Nada de Python en el host: todo corre dentro del contenedor `api`.

## Cómo levantar

```bash
cp .env.example .env   # si todavía no existe; completar GROQ_API_KEY más adelante
make up
make ps                # confirmar que postgres y api estén "healthy"
```

## Servicios

| Servicio  | URL                    | Notas |
| :-------- | :--------------------- | :---- |
| API       | http://localhost:8000  | `/health`, `/` |
| n8n       | http://localhost:5678  | orquestación de workflows |
| Adminer   | http://localhost:8080  | cliente web para Postgres |
| Postgres  | localhost:5432         | también accesible desde un cliente GUI del host |

### Credenciales de Adminer

- **Sistema**: PostgreSQL
- **Servidor**: `postgres` (el nombre del servicio, no `localhost`)
- **Usuario / Contraseña / Base de datos**: los valores de `POSTGRES_USER` /
  `POSTGRES_PASSWORD` / `POSTGRES_DB` en tu `.env` (por defecto:
  `clipping` / `clipping_dev` / `social_listening`)

## Tests

```bash
make test
```

Corre `pytest` dentro del contenedor `api` (no hace falta Python en el host
ni una base de datos real: los tests de `/health` mockean `check_db`).

## Otros comandos

```bash
make logs     # logs en vivo de los 4 servicios
make down     # baja los servicios, conserva los datos
make reset    # baja TODO y borra los volúmenes (postgres y n8n a cero)
make sh-api   # shell dentro del contenedor api
```

## Gotchas

- **`http://api:8000`, no `http://localhost:8000`, desde n8n.** Dentro de la
  red que crea Compose, cada servicio se resuelve por su nombre. Si un nodo
  HTTP Request de n8n apunta a `localhost:8000`, va a intentar conectarse al
  propio contenedor de n8n (que no escucha ese puerto) y va a fallar. Este
  es el error más común al empezar con Docker Compose.

- **`db/init/` solo corre una vez.** Postgres ejecuta los `.sql` de esa
  carpeta únicamente la primera vez que arranca con el volumen de datos
  vacío. Si editás `db/init/001_schema.sql` después de la primera corrida,
  el cambio **no** se aplica solo: hay que hacer `make reset` (borra el
  volumen de Postgres) y `make up` de nuevo.

- **El CLI de Docker no está en el PATH por defecto.** En esta Mac vive en
  `~/.docker/bin/docker`, no en una ubicación estándar de shells no-login.
  El `Makefile` ya exporta el PATH en cada target; si corrés `docker`
  directo a mano, hacé primero:
  ```bash
  export PATH="$HOME/.docker/bin:$PATH"
  ```
