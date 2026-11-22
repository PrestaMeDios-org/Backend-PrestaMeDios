#!/usr/bin/env bash
# Actualiza producción a un tag de main (SPEC-11 §6.5, RN-P09, AC-P15). Corre en el host.
#
# Uso: deploy/actualizar.sh vAAAA.MM.N
# El mismo tag tiene que existir en Backend y Frontend. Si la migración falla, vuelve
# los repos al tag anterior y no reinicia nada: la versión en servicio sigue andando.
set -euo pipefail

TAG="${1:?Uso: actualizar.sh vAAAA.MM.N}"
cd "$(dirname "$0")/.."
BACKEND="$(pwd)"
FRONTEND="$(realpath "${FRONTEND_DIR:-../Frontend-PrestaMeDios}")"
COMPOSE=(docker compose -f compose.prod.yaml ${COMPOSE_EXTRA:-})

anterior_back="$(git describe --tags --always)"
anterior_front="$(git -C "$FRONTEND" describe --tags --always)"

volver() {
    echo "actualizar: ERROR en «$1». Vuelvo los repos a ${anterior_back} / ${anterior_front}." >&2
    git -C "$BACKEND" checkout -q "$anterior_back"
    git -C "$FRONTEND" checkout -q "$anterior_front"
    echo "actualizar: la versión en servicio no se tocó. Si la migración dejó cambios, restaurar la copia previa (deploy/restaurar.sh)." >&2
    exit 1
}

echo "actualizar: ${anterior_back} → ${TAG}"

echo "== 1. Copia de seguridad previa"
"${COMPOSE[@]}" exec -T tareas /app/deploy/backup.sh || volver "copia previa"

echo "== 2. Código del tag ${TAG}"
for repo in "$BACKEND" "$FRONTEND"; do
    git -C "$repo" fetch -q --tags origin || volver "git fetch en $(basename "$repo")"
    git -C "$repo" checkout -q "refs/tags/${TAG}" || volver "el tag no existe en $(basename "$repo")"
done
"${COMPOSE[@]}" build || volver "build de las imágenes"

echo "== 3. Migraciones"
"${COMPOSE[@]}" run --rm --no-deps api alembic upgrade head || volver "alembic upgrade head"

echo "== 4. Reinicio"
"${COMPOSE[@]}" up -d --remove-orphans

echo "== 5. Verificación"
for _ in $(seq 1 30); do
    if "${COMPOSE[@]}" exec -T web wget -qO- http://127.0.0.1/health/db 2>/dev/null | grep -q '"ok"'; then
        echo "actualizar: ${TAG} en servicio; /health/db responde."
        echo "Verificar también desde afuera: https://<dominio>/health/db"
        exit 0
    fi
    sleep 2
done
echo "actualizar: ERROR, /health/db no responde después de reiniciar. Revisar: ${COMPOSE[*]} logs api" >&2
exit 1
