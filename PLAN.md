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
- Cliente de Groq con el modelo configurado en `GROQ_MODEL` (hoy `openai/gpt-oss-120b`; el
  `llama-3.3-70b-versatile` del plan original fue dado de baja por Groq).
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
| LLM | Groq, modelo por `GROQ_MODEL` | Free tier amplio y muy rápido; suficiente para clasificar copies. El catálogo cambia seguido, por eso el modelo es una variable de entorno |
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

### ✅ Etapa 1 — completa (commit `eddd4d3`)
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

### ✅ Etapa 2 — completa (commit `a258e89`)
Análisis con LLM. 39 tests en verde. **No probada en vivo todavía: falta `GROQ_API_KEY`.**

Archivos: `api/app/llm/{models,prompts,client,service}.py`, `api/app/routers/analyze.py`,
settings nuevos en `api/app/config.py`, y los tests `api/tests/test_llm_{client,service,prompts}.py`
y `test_analyze_router.py`.

Decisiones de la etapa:

- **`POST /analyze` no toca Postgres.** Recibe `[{external_id, copy_text}]` y devuelve
  `[{external_id, analyzed, sentiment, ...}]`. Es n8n quien hace el **merge** entre la mención
  capturada y su análisis antes del INSERT. Los nombres de campo de `Analysis` coinciden 1 a 1
  con las columnas de `mentions`, para que el nodo Postgres mapee directo sin un Set intermedio.
- **Batching** de `llm_batch_size` (20) copies por llamada: el rate limit de Groq es por minuto.
- **La re-asociación va por índice explícito, nunca por orden de la lista.** Es el punto más
  delicado de la etapa: si el modelo alucina o se saltea un índice y uno confía en el orden, el
  análisis se pega a la mención equivocada sin que nada falle visiblemente. Se descartan los
  índices fuera de rango y los repetidos.
- **La validación es item por item, no por lote.** Un `sentiment_score` alucinado descarta ese
  item y los demás pasan. Solo se reintenta si no validó ninguno. (Corregido en revisión: la
  primera versión validaba el lote entero y un item malo tiraba 19 buenos.)
- **Reintentos solo ante lo que un reintento arregla:** red, 5xx, 429 y respuesta inservible.
  Un 401 o un 400 no se reintentan. El backoff no duerme después del último intento.
- **El prompt serializa los copies con `json.dumps`**, no como líneas `"{i}: {texto}"`: los copies
  son texto de terceros multilínea y el formato de líneas permitía inyectar entradas falsas.
  El system prompt además advierte al modelo que los copies son contenido a analizar, no órdenes.
- **Degradación explícita:** un item que falla vuelve con `analyzed=False`, `error` con el motivo
  y `analyzed_at` en `None` — que es lo que después deja la fila con `analyzed_at IS NULL` en
  Postgres, elegible para un barrido posterior vía `idx_mentions_analyzed_at`.
- **503 vs 200 parcial:** falta de `GROQ_API_KEY` es 503 (problema de configuración); un lote que
  falla es 200 con `failed_count > 0` (información, no error del request).

Contrato que queda publicado para n8n:

```
POST /analyze
  body -> {items: [{external_id, copy_text}]}   (1 a 100 items)
  200  -> {count, analyzed_count, failed_count, results: [Analysis]}
  422  -> items vacío o fuera del rango [1, 100]
  503  -> GROQ_API_KEY no configurada
```

### 🔑 Groq: key cargada y modelo cambiado (2026-09-05)

La `GROQ_API_KEY` ya está en `.env` y el análisis fue **probado en vivo**: captura del mock →
`POST /analyze` → sentimiento, score, temas y justificación correctos. Dos cosas que costaron
un rato y no queremos volver a pagar:

- **`docker compose restart` NO relee el `.env`.** Reinicia el proceso dentro del contenedor
  existente, que tiene su entorno fijado desde que se creó. Hay que **recrear** el contenedor:
  `docker compose up -d api`. El síntoma es traicionero: la variable está en `.env`, el
  contenedor se reinició sin errores, y la app sigue diciendo que no está configurada. Se
  diagnostica con `docker compose exec api printenv GROQ_API_KEY`. (La instrucción anterior de
  este documento, que decía que alcanzaba con `restart`, era incorrecta.)
- **Groq dio de baja `llama-3.3-70b-versatile`.** Su catálogo ya no expone *ningún* Llama de
  chat. El default pasó a `openai/gpt-oss-120b`, y ahora el modelo se pasa por entorno
  (`GROQ_MODEL` en el compose y en `.env.example`) para que un cambio de catálogo no obligue a
  tocar código — que era justamente lo que el comentario del setting había anticipado. Si vuelve
  a aparecer un 404 `model_not_found`, la lista viva sale de
  `GET https://api.groq.com/openai/v1/models` con la key.

Detalle para depurar dentro del contenedor: `docker compose exec api python` levanta el Python
del sistema, **sin** las dependencias del proyecto. El intérprete con `httpx` y compañía es
`/app/.venv/bin/python`. Un script de diagnóstico que use `urllib` contra Groq además choca con
Cloudflare (`error code: 1010`, bloqueo por User-Agent), así que conviene usar `httpx` del venv.

### ✅ Etapa 3 — completa (2026-09-06)

El workflow de n8n, probado en producción. Se eligió el **modo híbrido** de construcción: el
usuario arma a mano los nodos que enseñan la UI y las credenciales, y recibe hecho el mapeo
tedioso.

**Estado final:** los dos workflows están **activos**, versionados en `n8n/workflows/`, y el
pipeline corre solo cada 15 minutos. Verificado punta a punta: 40 menciones capturadas,
analizadas e insertadas; corridas siguientes sin duplicar nada; y una caída provocada de la API
que disparó el error workflow y quedó registrada en `./compartido/errores/`.

**Hecho:**
- Cuenta de owner de n8n creada y workflow `Captura y analisis de menciones` (id `TdpP1g8HWOVgExny`).
- Credencial de Postgres cargada una sola vez y reusada por los dos nodos Postgres.
  Host `postgres` (el nombre del servicio de Compose), no `localhost`.
- Primera mitad armada a mano y **verificada en vivo**: Schedule Trigger (cada 15 min) →
  Code `Tags a monitorear` (2 providers × 2 tags = 4 items) → HTTP Request `Capturar menciones`
  → Split Out `mentions` → Postgres `¿Ya existe?` → Merge por posición. Da **40 items**, cada
  uno con los campos de la mención más `ya_existe: false`.
- Segunda mitad generada como JSON e importada: Filter `Solo las nuevas`, Code
  `Armar lote para /analyze`, HTTP Request `Analizar con LLM`, Split Out `resultados`,
  `Merge análisis` y el mapeo del INSERT.

**Diseño de la segunda mitad, para no tener que reconstruir el razonamiento:**

```
Merge ──> Solo las nuevas ──┬──> Armar lote ──> Analizar con LLM ──> Split Out resultados ──┐
         (Filter)           │      (Code)         (POST /analyze)                            │
                            │                                                                ▼
                            └───────────────────────────────────────────────> Merge análisis ──> INSERT
                                                                              (por external_id)
```

- **El Filter bifurca a dos destinos.** `/analyze` devuelve solo `{external_id, sentiment, ...}`,
  no el `copy_text` ni el `permalink`: esos siguen vivos únicamente en la rama directa, y el
  Merge final los vuelve a juntar. Sin esa bifurcación se pierde la mitad de la fila.
- **El primer Merge combina por posición; el segundo, por `external_id`.** El primero puede
  hacerlo porque `SELECT EXISTS` devuelve siempre exactamente una fila por mención, en orden. El
  segundo no: ni los lotes de 100 ni la respuesta del LLM garantizan orden. Es el mismo riesgo
  que la Etapa 2 ya había atacado del lado de Python ("la re-asociación va por índice explícito,
  nunca por orden de la lista"), pagado con la misma moneda del lado de n8n.
- **No hace falta un IF para cortar cuando no hay menciones nuevas:** n8n no ejecuta un nodo cuyo
  input llegó vacío. En la segunda corrida el Filter deja 0 items y ni `/analyze` ni el INSERT se
  ejecutan. Esa es la demostración de idempotencia que el mock determinista venía preparando
  desde la Etapa 1.
- **La dedup usa `SELECT EXISTS(...)` por mención, no un `WHERE id = ANY(...)` masivo.** Son N
  queries en vez de una, pero EXISTS devuelve siempre una fila: con un SELECT común, las
  menciones sin match no emitirían item y el Merge por posición se desalinearía en silencio.
  Con `limit=10` la ineficiencia no importa. Anotado como deuda más abajo.
- **El INSERT va con `Skip on Conflict`.** La deduplicación real la hace el Filter; el
  `UNIQUE (provider, external_id)` es la última línea de defensa si dos ejecuciones se solapan.
- Las queries usan **parámetros `$1`/`$2`** (campo *Query Parameters* del nodo), nunca
  interpolación de texto: el `external_id` viene de una fuente externa.

**Verificado:**
1. **Ejecución punta a punta:** 40 filas en `mentions`, las 40 con `analyzed_at`. Los tipos que
   preocupaban entraron bien: `metrics` como `jsonb` real (gracias al `JSON.stringify` en el
   mapeo) y `topics` como `text[]` real (lo resolvió el driver solo). No hizo falta el plan B de
   pasar el INSERT a *Execute Query*.
2. **Idempotencia:** la segunda corrida deja 0 items en `Solo las nuevas` y los nodos siguientes
   ni se ejecutan. Cuatro ejecuciones de producción seguidas dejaron la tabla en 40 filas.
3. **Error workflow probado de verdad**, apagando la API con `docker compose stop api` mientras
   el workflow corría activo. La secuencia quedó registrada en `execution_entity`: la ejecución
   del principal en `error`, la del workflow de errores en `success`, y al volver la API el
   pipeline se recuperó solo sin intervención.
4. **Ambos workflows activos**, el principal cada 15 minutos.

Para desactivarlos: el toggle de la UI, o
`docker compose exec n8n n8n update:workflow --id=<id> --active=false` seguido de
`docker compose restart n8n`.

**Diseño del error workflow (`Errores del pipeline`, id `DYj6RDBA6ohgakFB`, 4 nodos):**
`Error Trigger → Resumir el error (Code) → Convert to File → Read/Write Files from Disk`, que
deja un JSON por falla en `/data/errores/` (o sea `./compartido/errores/` en la Mac). El archivo
guarda `nodo_que_fallo`, `mensaje` y `ejecucion_url`, que es lo que permite ir directo a la
ejecución concreta en la UI sin buscarla a mano.

Ahí aparece un concepto de n8n que no habíamos tocado: **los datos binarios**. Un item tiene dos
mitades, `json` y `binary`. El nodo Code solo produce `json`, y para escribir un archivo hace
falta un adjunto binario: eso es lo que hace `Convert to File`, que mueve el JSON a la mitad
binaria bajo la clave `data` — la misma que después se nombra en *Input Binary Field*. Es el
mecanismo que va a reusar el informe de la Etapa 4.

**Aprendizajes de n8n de esta sesión:**
- **El workflow de errores también tiene que estar activo.** Si no, la falla se pierde con un
  `Workflow "<id>" is not active and cannot be executed` que solo aparece en
  `docker compose logs n8n`. Es exactamente el modo de fallo que un error workflow debería
  prevenir, y no avisa de ninguna forma visible.
- **n8n bloquea el filesystem por defecto** en los nodos de archivos: fallan con
  `Access to the file is not allowed`, que no es un permiso de Unix. Se resuelve con
  `N8N_RESTRICT_FILE_ACCESS_TO=/data` en el compose — declarando solo el volumen compartido, no
  abriendo todo.
- **Activar un workflow por CLI exige `docker compose restart n8n`**, porque el scheduler se arma
  al arrancar. Desde la UI no hace falta. Y `update:workflow` ya está marcado como deprecado, así
  que en algún momento habrá que pasar a la API REST de n8n.
- **La UI esconde controles mientras hay cambios sin guardar:** el toggle `Active` y el
  desplegable *Error Workflow* aparecen en gris o directamente no están. Regla práctica: guardar
  antes de buscar cualquier control de estado del workflow.
- **El error workflow puede fallar en silencio.** Estuvo cuatro ciclos terminando en `error` sin
  que nada avisara, porque no hay un error workflow del error workflow. Cuando esto crezca, el
  aviso no debería depender de escribir un archivo local sino de algo que uno mire (mail,
  Telegram, o una fila en Postgres que el informe levante).
- **Cómo diagnosticar n8n sin la UI**, que es lo que terminó resolviendo el problema:
  ```
  docker compose logs n8n --since=5m
  docker compose cp n8n:/home/node/.n8n/database.sqlite ./tmp.sqlite   # + -wal y -shm
  # execution_entity: id, workflowId, status, mode  -> qué corrió y si falló
  # execution_data:   el detalle, en el formato "flatted" de n8n
  ```
  **Hay que copiar también `database.sqlite-wal` y `-shm`.** SQLite corre en modo WAL: copiando
  solo el `.sqlite` se obtiene una foto vieja, sin las ejecuciones recientes. Nos hizo perder un
  rato creyendo que el workflow no había corrido.
- Al armar el esqueleto siguiendo una lista numerada es fácil confundir *el orden de los nodos*
  con *el orden de las conexiones*: el INSERT quedó colgando en paralelo al SELECT, o sea
  insertando cada mención apenas capturada, sin deduplicar ni analizar.
- Un valor que va al **nombre del nodo** en vez de al campo del parámetro da un error confuso
  (`The 'mentions' node has issues: Parameter "Fields To Split Out" is required`).
- En el export JSON, las expresiones se reconocen por el **`=` que n8n antepone** al valor
  (`"url": "=http://api:8000/..."`). Si falta ese `=`, el campo quedó en modo texto literal y
  las llaves `{{ }}` no se evalúan. Es la forma más rápida de auditar un workflow entero.
- `docker compose exec n8n n8n export:workflow --all --output=/tmp/wf.json` vuelca el workflow
  para inspeccionarlo desde afuera, pero **solo exporta lo guardado**: si la UI tiene cambios sin
  guardar, no aparecen.

### Deuda anotada (no bloquea, pero no la perdamos)
- En Instagram `metrics.views` es `None` cuando el post no es video; en X siempre trae número.
  El ranking por engagement de la Etapa 4 tiene que contemplar ese `None`.
- El mock siempre devuelve exactamente `limit` elementos. Una fuente real devuelve *hasta*
  `limit`, y a veces cero.
- La dedup del workflow hace una query por mención (`SELECT EXISTS`). Correcto y simple, pero si
  algún día se sube mucho el `limit`, conviene pasar a una sola query con `= ANY($1::text[])` y
  resolver la correlación con un Merge por campo en vez de por posición.

### Cómo retomar

**Estado del repo:** todo commiteado y pusheado a `https://github.com/fdelillo/agente-clipping`.
`main` trackea `origin/main`, working tree limpio, 39 tests en verde. La autenticación con
GitHub es vía `gh` CLI (ya instalado y logueado como `fdelillo`), protocolo HTTPS.

**Estado de n8n:** los dos workflows están **activos** y versionados en `n8n/workflows/`. El
principal corre cada 15 minutos por su cuenta mientras Docker esté levantado. Como el mock es
determinista, esas corridas no insertan nada nuevo ni gastan LLM: el Filter deja 0 items y el
pipeline se corta ahí.

**Pasos:**
1. Abrir Docker Desktop y levantar el stack: `make up`.
2. Verificar: `make ps` (postgres y api en `healthy`) y `curl localhost:8000/health`.
3. Probar la captura: `curl "localhost:8000/sources/mock_x/search?tag=milei&limit=3"`.
   Los `external_id` tienen que ser `599518440855865178`, `227823812536014777`,
   `720079261720601226` — son deterministas, si cambiaron algo se rompió.
4. Decirle a Claude: *"seguimos con la Etapa 4"* (el informe).

**Si los workflows de n8n se perdieron** (un `make reset` borra el volumen `n8n_data`):

```
for f in captura-y-analisis-de-menciones errores-del-pipeline; do
  docker compose cp n8n/workflows/$f.json n8n:/tmp/$f.json
  docker compose exec n8n n8n import:workflow --input=/tmp/$f.json
done
docker compose restart n8n
```

Como los JSON conservan el `id` del workflow, importar **actualiza** el existente en vez de
duplicarlo, y el `settings.errorWorkflow` del principal sigue apuntando al de errores. Lo que el
import **no** trae son las credenciales: hay que volver a cargar la de Postgres a mano (Host
`postgres`, base `social_listening`, usuario y password del `.env`). Después de importar,
refrescar la pestaña del navegador — si la UI tenía el workflow abierto con cambios sin guardar,
al guardar pisa lo importado.

**Qué es la `GROQ_API_KEY`** (quedó explicado en la sesión, se resume acá para no perderlo):
Groq es un proveedor que corre modelos open source en su hardware y los expone por HTTP. La API
key es la credencial que identifica la cuenta en cada llamada — el mismo concepto que la
contraseña de Postgres que ya está en el `.env`. Se saca gratis y sin tarjeta en
console.groq.com → *API Keys* → *Create API Key*; se muestra una sola vez, así que hay que
copiarla en el momento (si se pierde, se genera otra). Va en el `.env`, en la línea
`GROQ_API_KEY=`, y después hay que **recrear** el contenedor con `docker compose up -d api` (ver
más arriba: `restart` no alcanza). No hace falta rebuild, porque solo cambia el `.env`. El free
tier limita *requests por minuto*, no volumen total, y por eso la Etapa 2 manda 20 copies juntos
en una sola llamada y reintenta con espera ante un 429.

**Recordatorio para cuando toquemos el esquema:** `db/init/001_schema.sql` solo se ejecuta con
el volumen de Postgres vacío. Si cambia el esquema, hace falta `make reset` (borra los datos) o
pasar a migraciones de verdad.

**Recordatorio de Docker:** cambiar código Python no requiere rebuild (`./api` está montado como
volumen y uvicorn corre con `--reload`), pero cambiar `pyproject.toml` sí — las dependencias se
instalan en la imagen durante el build. El síntoma de olvidarlo es un `ModuleNotFoundError` de
una librería que jurás haber instalado.
