# Plan de desarrollo — Social Listening (Fase 1: captura y análisis de menciones)

> Documento de trabajo. Complementa a `proyecto_social_listening_agente.md`, que describe la
> visión completa del producto (incluido el clipping de video). Este plan cubre **solo la
> primera etapa**: capturar menciones por tag en X e Instagram, analizarlas con un LLM y
> emitir un informe.

## 1. Alcance acordado

**Entra en Fase 1:**
- Captura de menciones por tag/keyword en **X** e **Instagram**.
- Fuente **mock** primero; la fuente real (Apify o API oficial) se enchufa después sin tocar el resto.
- **Análisis con LLM** (Groq + Llama 3.3) del *copy* de cada posteo: sentimiento, tema y justificación.
- **Informe** con el listado de menciones y su sentimiento.

**Queda diferido (no se construye ahora):**
- Descarga de video, Whisper y clipping con FFmpeg.
- Dashboard en Streamlit.
- Microservicios en Go y colas (RabbitMQ/Kafka) — Fases 2 y 3 del documento original.

La arquitectura deja el hueco para el pipeline de video, pero no se implementa.

### Nota de alcance
Vos elegiste "análisis con LLM" e "informe", sin marcar "guardar y deduplicar". Igual incluyo
**persistencia en Postgres** porque sin ella el informe no tiene de dónde salir: cada corrida
volvería a analizar los mismos posteos, pagando llamadas al LLM de nuevo y sin poder mostrar
evolución en el tiempo. Es una decisión mía, explícita, y podés bajarla si preferís algo
stateless de una sola corrida.

## 2. Objetivo de aprendizaje

Este proyecto también es un vehículo para aprender **Docker** y **n8n**. Eso condiciona el
diseño: el reparto de trabajo es deliberadamente *balanceado*, no el más corto en líneas de código.

- **n8n** se lleva la orquestación real: schedule, llamadas HTTP, consulta y escritura en
  Postgres con nodos nativos, ramas condicionales, manejo de errores y credenciales.
- **Python (FastAPI)** se lleva el dominio: adapters de fuentes, normalización, contrato de datos,
  cliente del LLM, generación del informe y tests.
- La frontera entre ambos es un **contrato HTTP + JSON**, que es justamente lo que después
  permite reemplazar la llamada directa por una cola de mensajes.

## 3. Arquitectura de Fase 1

```
        ┌──────────────────────── docker compose ────────────────────────┐
        │                                                                │
        │   ┌─────────┐   HTTP    ┌──────────────┐                       │
        │   │   n8n   │──────────▶│  api (Python)│                       │
        │   │  :5678  │◀──────────│  FastAPI     │                       │
        │   └────┬────┘           │  :8000       │                       │
        │        │                └───────┬──────┘                       │
        │        │ nodo Postgres          │ SQL                          │
        │        ▼                        ▼                              │
        │   ┌──────────────────────────────────┐    ┌─────────────┐      │
        │   │          postgres :5432          │◀───│  adminer    │      │
        │   └──────────────────────────────────┘    │   :8080     │      │
        │                                           └─────────────┘      │
        │   volumen ./compartido  ──▶  informes generados                │
        └────────────────────────────────────────────────────────────────┘
```

**Punto importante de Docker:** dentro de la red de Compose los servicios se llaman por su
nombre. Desde n8n la API es `http://api:8000`, **no** `http://localhost:8000` — `localhost`
dentro del contenedor de n8n es el propio n8n. Ese es uno de los errores más comunes al empezar.

### Flujo del workflow

1. **Schedule Trigger** (n8n) — cada N minutos, por cada tag configurado.
2. **HTTP Request** → `GET /sources/{provider}/search?tag=X&limit=N`. Python consulta la fuente
   (mock hoy, Apify mañana) y devuelve menciones **ya normalizadas** al esquema común.
3. **Postgres** (n8n) — busca cuáles `external_id` ya existen.
4. **IF / Filter** (n8n) — se queda solo con las menciones nuevas. Si no hay ninguna, corta.
5. **HTTP Request** → `POST /analyze` con los copies nuevos. Python llama a Groq y devuelve
   sentimiento, score, temas y justificación.
6. **Postgres** (n8n) — inserta las menciones enriquecidas.
7. **HTTP Request** → `POST /reports/generate`. Python arma el informe HTML en `./compartido`.
8. **Notificación** (n8n) — avisa que el informe está listo.

n8n toca cinco tipos de nodo distintos y Python resuelve tres problemas reales. Los dos lados
tienen sustancia.

## 4. Modelo de datos

Tabla `mentions`, esquema común para X e Instagram:

| Campo | Tipo | Notas |
| :--- | :--- | :--- |
| `id` | `bigserial` PK | clave subrogada |
| `provider` | `text` | `x`, `instagram`, `mock_x`, `mock_instagram` |
| `external_id` | `text` | id del post en la red de origen |
| `tag` | `text` | keyword que disparó la captura |
| `author_handle` | `text` | |
| `copy_text` | `text` | el texto del posteo: la materia prima del análisis |
| `permalink` | `text` | |
| `published_at` | `timestamptz` | |
| `metrics` | `jsonb` | likes, comentarios, shares, vistas — cada red trae campos distintos |
| `captured_at` | `timestamptz` | |
| `sentiment` | `text` | `positive` / `neutral` / `negative` |
| `sentiment_score` | `numeric` | −1.0 a 1.0 |
| `topics` | `text[]` | |
| `llm_rationale` | `text` | por qué el modelo decidió eso; sirve para depurar el prompt |
| `analyzed_at` | `timestamptz` | nulo si todavía no pasó por el LLM |

Restricción clave: `UNIQUE (provider, external_id)`. Es lo que hace idempotente al pipeline —
si el workflow corre dos veces, no duplica.

`metrics` va en `jsonb` a propósito: X e Instagram exponen métricas distintas y no quiero migrar
el esquema cada vez que cambia una fuente.

## 5. Etapas de implementación

### Etapa 0 — Andamiaje y Docker
- `git init` + `.gitignore` (nada de secretos ni de `compartido/` versionado).
- `docker-compose.yml` con `postgres`, `api`, `n8n` y `adminer`.
- `Dockerfile` de la API sobre `python:3.12-slim`.
- `.env.example` versionado; `.env` real ignorado.
- Volumen `./compartido` compartido entre `api` y `n8n`, como ya preveía el documento original.
- Script o `Makefile` con `up` / `down` / `logs` / `test`.

**Verificación:** `docker compose up -d` deja n8n en `:5678`, API respondiendo en `/health`,
Adminer en `:8080` mostrando la tabla `mentions` vacía.

*Correcciones al compose del documento original:* la clave `version:` está obsoleta en Compose v2+
y genera warning; y `restart: always` conviene bajarlo a `unless-stopped` en desarrollo, para que
los contenedores no se levanten solos cada vez que arrancás la Mac.

### Etapa 1 — Modelo de datos y adapters (Python)
- Modelos Pydantic: `RawXPost`, `RawInstagramPost`, `Mention`.
- Adapter por proveedor detrás de una interfaz común `search(tag, limit) -> list[Mention]`.
- Proveedor `mock` que genera payloads con **la forma cruda real** de X e IG (no pre-normalizados),
  para que la normalización sea trabajo honesto y el cambio a Apify no sorprenda.
- Migración SQL inicial (`db/init/001_schema.sql`).
- `GET /sources/{provider}/search`, `GET /health`.
- Tests con pytest sobre normalización y contrato.

### Etapa 2 — Análisis con LLM (Python + Groq)
- Cliente de Groq con `llama-3.3-70b-versatile`.
- Prompt de análisis sobre el copy: sentimiento, score, temas, justificación breve.
- **Salida estructurada en JSON validada con Pydantic** — nunca parsear texto libre del modelo.
- Batching de varios copies por llamada, con reintentos y respeto del rate limit.
- `POST /analyze`.
- Tests con la respuesta del LLM mockeada, para no quemar cuota en cada corrida de la suite.

### Etapa 3 — Workflow de n8n
- Construcción del workflow descrito en §3.
- Credenciales cargadas en n8n (no hardcodeadas en los nodos).
- Un **error workflow** que avise cuando algo falla.
- **Exportar el workflow a `n8n/workflows/*.json` y versionarlo.** Si vive solo dentro del
  volumen de n8n, un `docker compose down -v` te lo borra.

### Etapa 4 — Informe
- `POST /reports/generate` con rango de fechas y tag.
- Plantilla Jinja2 → HTML autocontenido en `./compartido/informes/`.
- Contenido: resumen ejecutivo, distribución de sentimiento, comparación X vs IG, listado de
  menciones con autor, red, copy, link y sentimiento, y top por engagement.

### Etapa 5 — Fuente real
- Adapters `apify_x` y `apify_instagram` implementando la misma interfaz que el mock.
- En n8n solo cambia el nombre del provider en la URL. Nada más se toca.
- Es el momento de decidir Apify (rápido, pago por uso) vs API oficial (X Basic ~$200/mes;
  IG Graph API gratis pero con cuenta Business, Meta App, App Review y tope de 30 hashtags
  cada 7 días).

## 6. Decisiones tomadas

| Tema | Decisión | Motivo |
| :--- | :--- | :--- |
| Fuente de datos | Mock primero | Construir el pipeline completo sin gastar ni pelear con anti-bot |
| LLM | Groq + Llama 3.3 | Free tier amplio y muy rápido; suficiente para clasificar copies |
| Transcripción | Groq Whisper API | Definido para cuando llegue el clipping; evita CPU Intel lenta |
| Reparto | Balanceado n8n / Python | Único que enseña las dos herramientas de verdad |
| Persistencia | Postgres | Idempotencia, evolución temporal y base del informe |
| Estado de n8n | SQLite en volumen | Menos piezas móviles al arrancar; migrable a Postgres después |
| Modelos de IA para el desarrollo | Opus planifica, Sonnet ejecuta | Ver §7 |

## 7. Modo de trabajo con Claude Code

**Opus** para pensar, **Sonnet** para ejecutar.

- Con **Opus** (sesión principal): diseño, planificación, decisiones de arquitectura, análisis de
  trade-offs, diagnóstico de problemas difíciles y revisión de lo que produce Sonnet.
- Con **Sonnet** (subagente): escritura del código de una etapa ya especificada, andamiaje,
  refactors mecánicos, tests y tareas repetitivas.

El motivo es de costo: Opus se justifica en el diseño, no en teclear una etapa ya definida.

La consecuencia práctica es que cada etapa de §5 tiene que quedar escrita con suficiente
concreción —archivos a crear, contratos, criterio de verificación— antes de delegarla, porque el
subagente arranca sin el contexto de la conversación. Al volver, el resultado se revisa con Opus
en vez de aceptarse a ciegas.


## 8. Riesgos y puntos de atención

- **Costo y fragilidad de la captura real.** Es el punto más caro del proyecto y por eso está
  aislado detrás de la interfaz de adapters. La decisión se puede postergar sin bloquear nada.
- **Inyección de comandos.** El prototipo del documento original usa
  `subprocess.run(f"yt-dlp ... {url}", shell=True)` con una URL que llega desde un webhook. Cuando
  lleguemos al clipping: lista de argumentos, sin `shell=True`, y validación de la URL.
- **MoviePy.** `from moviepy.editor` no existe en MoviePy 2.x, y además re-encodea el video
  entero. Para cortar conviene `ffmpeg -ss/-to` con copia de streams.
- **Alucinación del LLM.** Mitigado con salida JSON estructurada y validación Pydantic; si no
  valida, se reintenta y si no, se marca la mención como no analizada en vez de guardar basura.
- **Datos personales.** Estamos guardando posteos públicos con handles de autor. Si esto sale de
  tu máquina, hay que revisar retención y ToS de cada red.

## 9. Estado actual

**Última actualización: 2026-09-03.**

### ✅ Etapa 0 — completa (commit `03985a2`)
Los cuatro servicios levantan con `make up`. `/health` responde `{"status":"ok","db":"ok"}`,
la tabla `mentions` existe con el esquema de §4, los tests pasan y desde el contenedor de n8n
se alcanza `http://api:8000`.

Dos ajustes sobre la spec original de la etapa, ya aplicados:
- No se setea `N8N_RUNNERS_ENABLED`: en n8n 2.37.7 los runners ya vienen activados y setear
  esa variable es justamente lo que dispara un warning de deprecación.
- Se agregó `api/.dockerignore` y el `uv.lock` se copia junto al `pyproject.toml` con
  `uv sync --frozen`, para que el build sea reproducible y no hornee el `.venv` del host.

### ✅ Etapa 1 — completa (sin commitear todavía)
Modelos, adapters mock y endpoint de captura. 21 tests en verde.

Archivos: `api/app/models.py`, `api/app/sources/{base,__init__,_fake,mock_x,mock_instagram}.py`,
`api/app/routers/sources.py`, y los tests `api/tests/test_{mock_x,mock_instagram,sources_router}.py`.

Decisiones tomadas durante la etapa, que no estaban en la spec original:

- **`Mention` no incluye los campos del LLM.** Representa "lo que devuelve una fuente" en el
  momento de la captura. El análisis de la Etapa 2 es un objeto aparte y **es n8n quien hace el
  merge** entre la mención y su análisis antes de insertar. Alternativa descartada: que la API
  devolviera la mención ya analizada, lo que dejaría a n8n como un cron tonto.
- **El mock es determinista por `(provider, tag)`**, sembrado con `sha256` y no con `hash()`,
  que está aleatorizado por proceso vía `PYTHONHASHSEED`. Es lo que hace *demostrable* la
  idempotencia: la segunda corrida del workflow tiene que terminar en cero menciones nuevas.
  Subir `limit` conserva el prefijo de la lista anterior.
- **`_fetch_raw` y `_normalize` están separados** en cada adapter. En la Etapa 5 se reemplaza
  solo el primero por la llamada a Apify.
- **Las claves de `metrics` están unificadas entre redes** donde el concepto coincide (`likes`
  en ambas), para que el informe de la Etapa 4 pueda comparar X vs IG sin traducir campos.
- **La respuesta va envuelta en `SearchResponse`**, no en una lista pelada: deja lugar para
  paginación y obliga a usar el nodo *Split Out* de n8n, que es el patrón correcto.
- `published_at` se ancla a la medianoche UTC del día, no al instante de la llamada, para que
  dos llamadas seguidas no difieran por microsegundos.

Contrato que queda publicado para n8n:

```
GET /sources                            -> ["mock_x", "mock_instagram"]
GET /sources/{provider}/search?tag=&limit=
    200 -> {provider, tag, count, mentions: [Mention]}
    404 -> provider inexistente (el detail lista los válidos)
    422 -> tag ausente/vacío, limit fuera de [1, 100]
```

### ⏭️ Etapa 2 — siguiente
Análisis con LLM (ver §5): cliente de Groq con `llama-3.3-70b-versatile`, prompt de análisis
sobre el copy, salida JSON estructurada validada con Pydantic, batching con reintentos,
`POST /analyze` y tests con la respuesta del LLM mockeada.

**Requisito para arrancar:** `GROQ_API_KEY` cargada en `.env` (la key se saca gratis en
console.groq.com). Los tests no la necesitan, porque mockean la respuesta del modelo.

### Deuda anotada (no bloquea, pero no la perdamos)
- En Instagram `metrics.views` es `None` cuando el post no es video; en X siempre trae número.
  El ranking por engagement de la Etapa 4 tiene que contemplar ese `None`.
- El mock siempre devuelve exactamente `limit` elementos. Una fuente real devuelve *hasta*
  `limit`, y a veces cero.

### Cómo retomar
1. Abrir Docker Desktop y levantar el stack: `make up`.
2. Verificar: `make ps` (postgres y api en `healthy`) y `curl localhost:8000/health`.
3. Probar la captura: `curl "localhost:8000/sources/mock_x/search?tag=milei&limit=3"`.
4. Decirle a Claude: *"seguimos con la Etapa 2"*.

**Recordatorio para cuando toquemos el esquema:** `db/init/001_schema.sql` solo se ejecuta con
el volumen de Postgres vacío. Si cambia el esquema, hace falta `make reset` (borra los datos) o
pasar a migraciones de verdad.

**Recordatorio de Docker:** cambiar código Python no requiere rebuild (`./api` está montado como
volumen y uvicorn corre con `--reload`), pero cambiar `pyproject.toml` sí — las dependencias se
instalan en la imagen durante el build. El síntoma de olvidarlo es un `ModuleNotFoundError` de
una librería que jurás haber instalado.
