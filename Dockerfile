# Imagen de la PrestaMeDios API (SPEC-11 §4.1, plan §4.1).
#
#   docker build --target final -t prestamedios-api .   # producción
#   docker build --target dev   -t prestamedios-api:dev . # desarrollo (compose.yaml)
#
# Sin secretos adentro (RN-P01): todo llega por variables de entorno al correr.

# --- base: Python y usuario sin privilegios -------------------------------
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --no-create-home app

WORKDIR /app

# --- deps: dependencias de la aplicación en un venv -----------------------
FROM base AS deps

RUN python -m venv "$VIRTUAL_ENV"
COPY requirements.txt .
RUN pip install -r requirements.txt

# --- final: imagen de producción ------------------------------------------
FROM base AS final

COPY --from=deps /opt/venv /opt/venv
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

USER app
EXPOSE 8000

# `/health` no consulta la base (vida del proceso); no hace falta curl.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]

# Cantidad de procesos: WEB_CONCURRENCY (uvicorn la lee; 1 si no está).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# --- dev: desarrollo con dependencias de tests y recarga en caliente --------
FROM final AS dev

USER root
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
COPY pytest.ini ./
USER app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# --- tareas: cron sin root, copias y mantenimiento (SPEC-11 §6.4, plan §6.3) --
FROM final AS tareas

USER root

# Cliente de PostgreSQL 16 (el mismo que el servidor) desde el repositorio oficial
# PGDG; age (cifrado de copias), rclone (copia externa), curl (latidos) y tzdata.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg tzdata \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
        https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && . /etc/os-release \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-16 age rclone \
    && apt-get purge -y gnupg && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# supercronic: cron para contenedores, sin root (D-07). Suma publicada en la release.
ENV SUPERCRONIC_URL=https://github.com/aptible/supercronic/releases/download/v0.2.51/supercronic-linux-amd64 \
    SUPERCRONIC_SHA1SUM=1692066e350a88ff4d7d6474fe3c7a6c41ec5e89
RUN curl -fsSL -o /usr/local/bin/supercronic "$SUPERCRONIC_URL" \
    && echo "${SUPERCRONIC_SHA1SUM}  /usr/local/bin/supercronic" | sha1sum -c - \
    && chmod +x /usr/local/bin/supercronic

COPY deploy ./deploy
RUN chmod +x deploy/*.sh \
    && install -d -o app -g app /backups

USER app
HEALTHCHECK NONE
CMD ["supercronic", "-passthrough-logs", "/app/deploy/crontab"]
