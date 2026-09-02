-- Esquema inicial de la Fase 1 del proyecto de social listening.
--
-- Este archivo vive en ./db/init y Postgres lo ejecuta UNA sola vez, la
-- primera vez que arranca con el volumen de datos vacío (ver comentario en
-- docker-compose.yml). Si necesitás cambiar el esquema durante el
-- desarrollo, la forma de que esto se vuelva a aplicar es "make reset"
-- (que hace "docker compose down -v" y vuelve a levantar todo de cero).

-- Tabla única para menciones de cualquier red (X, Instagram, y sus
-- variantes mock). Compartir una sola tabla entre proveedores simplifica
-- las consultas del informe ("todas las menciones del tag X, sin importar
-- la red") a costa de tener algunas columnas que no todas las redes usan.
create table if not exists mentions (
    id              bigserial primary key,

    -- De dónde viene la mención. Usamos "mock_x" / "mock_instagram" para
    -- los datos de prueba de la Etapa 1, y "x" / "instagram" cuando se
    -- conecte la fuente real en la Etapa 5, sin cambiar el esquema.
    provider        text not null,

    -- Id del posteo en la red de origen. Junto con "provider" forma la
    -- clave natural que evita duplicados (ver el UNIQUE más abajo).
    external_id     text not null,

    -- Keyword/tag que disparó la búsqueda que encontró este posteo.
    tag             text not null,

    author_handle   text,
    copy_text       text,
    permalink       text,
    published_at    timestamptz,

    -- jsonb en vez de columnas fijas (likes, comments, shares...) porque
    -- cada red expone métricas distintas (X: retweets/replies/likes/views;
    -- Instagram: likes/comments, a veces sin conteo público) y no queremos
    -- una migración de esquema cada vez que cambia una fuente o se agrega
    -- una red nueva. jsonb además permite indexar/consultar campos puntuales
    -- si hiciera falta más adelante (con un índice GIN), a diferencia de un
    -- json plano.
    metrics         jsonb not null default '{}'::jsonb,

    -- Cuándo lo capturamos nosotros (no cuándo se publicó: eso es
    -- published_at). Sirve para auditar corridas del pipeline.
    captured_at     timestamptz not null default now(),

    -- Resultado del análisis con LLM (Etapa 2). Quedan NULL hasta que el
    -- posteo pasa por /analyze; el índice sobre analyzed_at de abajo existe
    -- justamente para encontrar rápido lo que todavía está pendiente.
    sentiment       text,
    sentiment_score numeric(3,2),
    topics          text[],
    llm_rationale   text,
    analyzed_at     timestamptz,

    -- Idempotencia: si el workflow de n8n corre de nuevo y vuelve a traer
    -- el mismo posteo, este UNIQUE es lo que impide insertarlo dos veces.
    constraint mentions_provider_external_id_key unique (provider, external_id),

    -- Sentiment solo puede ser uno de estos tres valores, o NULL (todavía
    -- no analizado). Preferimos este CHECK a un tipo ENUM de Postgres
    -- porque un ENUM es más incómodo de alterar más adelante si se agrega
    -- una categoría nueva.
    constraint mentions_sentiment_check
        check (sentiment is null or sentiment in ('positive', 'neutral', 'negative'))
);

-- Consulta más común del informe: "menciones de este tag, más recientes
-- primero". El DESC en published_at hace que el índice sirva tal cual para
-- ese ORDER BY sin tener que reordenar en memoria.
create index if not exists idx_mentions_tag_published_at
    on mentions (tag, published_at desc);

-- Para el paso de n8n/API que busca "qué falta analizar todavía"
-- (analyzed_at is null). Un índice parcial sería más chico, pero uno
-- normal alcanza para el volumen de esta fase y es más simple de razonar.
create index if not exists idx_mentions_analyzed_at
    on mentions (analyzed_at);
