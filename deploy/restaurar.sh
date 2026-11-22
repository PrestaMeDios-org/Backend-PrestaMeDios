#!/usr/bin/env bash
# Restaura una copia cifrada en una base NUEVA (SPEC-11 §6.6, AC-P13). Corre en el host.
#
# Uso: deploy/restaurar.sh <copia> <clave-privada-age>
#   <copia>  nombre del archivo (prestamedios-AAAA-MM-DD_HHMM.dump.age): se busca en
#            /backups del contenedor y, si no está, en BACKUP_DESTINO (diarias/ y mensuales/).
#   <clave>  archivo con la identidad privada de age. La trae el operador en el momento
#            y no queda en la máquina (AC-P21): borrarla al terminar.
#
# No toca la base en uso: crea prestamedios_restaurada_<fecha> y explica cómo pasar la
# app a esa base. Probar una vez por mes en la máquina de un integrante (RN-P10).
set -euo pipefail

copia="${1:?Uso: restaurar.sh <copia> <clave-privada-age>}"
clave="$(realpath "${2:?Falta la clave privada de age}")"
cd "$(dirname "$0")/.."
COMPOSE=(docker compose -f compose.prod.yaml ${COMPOSE_EXTRA:-})
nueva="prestamedios_restaurada_$(date +%Y%m%d%H%M)"

echo "restaurar: ${copia} → base ${nueva}"
"${COMPOSE[@]}" run --rm --no-deps -u root -v "${clave}:/run/clave-age:ro" \
    -e COPIA="$copia" -e NUEVA="$nueva" tareas bash -euo pipefail -c '
        export RCLONE_CONFIG="${RCLONE_CONFIG:-/dev/null}"
        trabajo="$(mktemp -d)"
        trap "rm -rf \"$trabajo\"" EXIT
        if [[ -f "/backups/$COPIA" ]]; then
            cp "/backups/$COPIA" "$trabajo/copia.age"
        elif ! rclone copyto "$BACKUP_DESTINO/diarias/$COPIA" "$trabajo/copia.age" 2>/dev/null; then
            rclone copyto "$BACKUP_DESTINO/mensuales/$COPIA" "$trabajo/copia.age"
        fi
        age -d -i /run/clave-age "$trabajo/copia.age" > "$trabajo/copia.dump"
        createdb "$NUEVA"
        pg_restore --no-owner --no-privileges --exit-on-error -d "$NUEVA" "$trabajo/copia.dump"
        psql -d "$NUEVA" -Atc "SELECT '"'"'usuarios: '"'"' || count(*) FROM usuarios"
    '

cat <<EOF

restaurar: listo. La base en uso no cambió.
Para pasar la app a la copia restaurada:
  1. En .env, POSTGRES_DB=${nueva}
  2. ${COMPOSE[*]} up -d api tareas
  3. Verificar /health/db y entrar a la app.
Para volver atrás: restaurar el POSTGRES_DB anterior y repetir el paso 2.
Borrar la clave privada de esta máquina: shred -u "${clave}"
EOF
