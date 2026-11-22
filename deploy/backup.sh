#!/usr/bin/env bash
# Copia de seguridad diaria cifrada (SPEC-11 §6.6, D-09, D-13). Corre en `tareas`.
#
# 1. pg_dump (formato custom) cifrado con age para BACKUP_CLAVE_PUBLICA. La clave
#    privada NO está en la máquina (AC-P21): la custodia el equipo de operación.
# 2. Guarda las últimas 7 en /backups y sube cada una a BACKUP_DESTINO con rclone
#    (diarias/ 30 días; mensuales/ el día 1, 365 días).
# 3. Falla (código ≠ 0) si algo sale mal o si el disco supera el 85 %, así el latido
#    no llega y el monitoreo avisa.
#
# Variables: PGHOST, PGUSER, PGPASSWORD, PGDATABASE (las fija compose.prod.yaml),
# BACKUP_CLAVE_PUBLICA, BACKUP_DESTINO (remoto de rclone, p. ej. r2:prestamedios-copias,
# o una ruta local para probar) y la configuración de rclone por variables RCLONE_CONFIG_*.
set -euo pipefail

: "${BACKUP_CLAVE_PUBLICA:?Falta BACKUP_CLAVE_PUBLICA}"
: "${BACKUP_DESTINO:?Falta BACKUP_DESTINO}"

# La configuración de rclone llega por variables RCLONE_CONFIG_*: sin archivo.
export RCLONE_CONFIG="${RCLONE_CONFIG:-/dev/null}"

DIR="${BACKUP_DIR_LOCAL:-/backups}"
RETENCION_LOCAL=7
UMBRAL_DISCO=85
nombre="prestamedios-$(date +%Y-%m-%d_%H%M).dump.age"
archivo="${DIR}/${nombre}"

echo "backup: volcando ${PGDATABASE} → ${nombre}"
pg_dump --format=custom --no-owner --no-privileges | age -r "$BACKUP_CLAVE_PUBLICA" > "${archivo}.parcial"
mv "${archivo}.parcial" "$archivo"
echo "backup: $(du -h "$archivo" | cut -f1) cifrado"

# Retención local: las últimas 7.
ls -1t "$DIR"/prestamedios-*.dump.age | tail -n +$((RETENCION_LOCAL + 1)) | xargs -r rm -f

# Copia externa.
rclone copyto "$archivo" "${BACKUP_DESTINO}/diarias/${nombre}"
if [[ "$(date +%d)" == "01" ]]; then
    rclone copyto "$archivo" "${BACKUP_DESTINO}/mensuales/${nombre}"
fi
# Retención externa. Un fallo acá no invalida la copia de hoy: se reintenta mañana.
# (mensuales/ no existe hasta el primer día 1: se ignora ese error.)
rclone delete --min-age 30d "${BACKUP_DESTINO}/diarias" \
    || echo "backup: aviso, no se pudo aplicar la retención de diarias/" >&2
rclone lsf --max-depth 1 "${BACKUP_DESTINO}" 2>/dev/null | grep -qx "mensuales/" \
    && { rclone delete --min-age 365d "${BACKUP_DESTINO}/mensuales" \
        || echo "backup: aviso, no se pudo aplicar la retención de mensuales/" >&2; }
echo "backup: subido a ${BACKUP_DESTINO}"

# Espacio en disco (EC-P06).
uso="$(df -P "$DIR" | awk 'NR==2 { sub("%", "", $5); print $5 }')"
if (( uso > UMBRAL_DISCO )); then
    echo "backup: ERROR, el disco está al ${uso} % (umbral ${UMBRAL_DISCO} %)." >&2
    exit 1
fi
echo "backup: listo (disco al ${uso} %)"
