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
