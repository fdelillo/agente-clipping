FROM python:3.12-slim

# Traemos el binario de uv desde su propia imagen oficial en vez de instalarlo
# con pip: es un solo "COPY --from=", no necesita red en el build y es mucho
# más rápido resolviendo/instalando dependencias que pip.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# uv por defecto intenta hardlinkear paquetes desde su caché al venv, que es
# más rápido que copiar. Pero caché y venv terminan en filesystems/capas
# distintas dentro del build de Docker, así que el hardlink no es posible y
# uv avisa con un warning en cada build. Le decimos de entrada que copie,
# para no ver ese warning cada vez.
ENV UV_LINK_MODE=copy

# No corremos como root adentro del contenedor: si alguien logra ejecutar algo
# a través de la app, que no sea con todos los permisos. python:3.12-slim no
# trae un usuario sin privilegios listo para usar, así que lo creamos.
RUN useradd --create-home --shell /bin/bash app \
    && chown app:app /app
USER app

# Copiamos ÚNICAMENTE los archivos de dependencias primero, y recién después
# el resto del código. Docker cachea cada capa por separado: mientras el
# pyproject.toml no cambie, "uv sync" no se vuelve a correr aunque editemos
# app/main.py mil veces, así que los rebuilds del día a día son casi
# instantáneos.
#
# El uv.lock tiene que entrar ACÁ, junto al pyproject y antes del sync. Si lo
# dejáramos entrar recién con el "COPY . ." de abajo, uv resolvería las
# versiones de cero en cada build y el lock no serviría para nada.
# --frozen le exige usar exactamente lo que dice el lock, sin re-resolver:
# eso es lo que hace que la imagen sea reproducible.
COPY --chown=app:app pyproject.toml uv.lock ./
RUN uv sync --frozen

# Recién acá copiamos el código. En desarrollo esto además queda pisado por
# el bind mount "./api:/app" del docker-compose.yml, que es lo que permite
# el hot reload sin reconstruir la imagen.
COPY --chown=app:app . .

EXPOSE 8000

# --reload: entorno de desarrollo, no producción. uv run ejecuta dentro del
# venv que armó "uv sync" sin necesidad de activarlo a mano.
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
