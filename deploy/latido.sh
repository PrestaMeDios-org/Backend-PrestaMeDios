#!/usr/bin/env bash
# Avisa al monitoreo que una tarea terminó bien (SPEC-11 §6.8).
# Uso: latido.sh NOMBRE_DE_VARIABLE   (p. ej. MONITOREO_PING_BACKUP)
# Si la variable no está definida, no hace nada (desarrollo y pruebas locales).
set -euo pipefail

variable="${1:?Falta el nombre de la variable con la URL del latido}"
url="${!variable:-}"

if [[ -z "$url" ]]; then
    echo "latido: ${variable} sin definir; no se avisa al monitoreo."
    exit 0
fi

curl -fsS -m 10 --retry 3 -o /dev/null "$url"
echo "latido: ${variable} enviado."
