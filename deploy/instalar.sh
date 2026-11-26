#!/usr/bin/env bash
# Prepara una Ubuntu Server 24.04 limpia para PrestaMeDios (SPEC-11 §6.2, §6.5, plan §6.2).
#
# Uso (como root, en la máquina del laboratorio):
#   curl -fsSLO https://raw.githubusercontent.com/PrestaMeDios-org/Backend-PrestaMeDios/<tag>/deploy/instalar.sh
#   less instalar.sh          # leerlo antes de correrlo
#   sudo bash instalar.sh vAAAA.MM.N
#
# Hace lo automatizable. Lo manual (BIOS, cifrado del disco, Tailscale, Cloudflare,
# cuentas externas) se lista al final y se detalla en docs/instalacion.md de Docs.
set -euo pipefail

TAG="${1:?Uso: instalar.sh vAAAA.MM.N}"
USUARIO=prestamedios
RAIZ=/opt/prestamedios
ORG=https://github.com/PrestaMeDios-org

[[ $EUID -eq 0 ]] || { echo "Correr como root (sudo)." >&2; exit 1; }
. /etc/os-release
[[ "$ID" == "ubuntu" ]] || echo "Aviso: probado en Ubuntu Server 24.04; esto es ${PRETTY_NAME}."

echo "== Paquetes del sistema y actualizaciones automáticas"
apt-get update
apt-get install -y ca-certificates curl git unattended-upgrades
dpkg-reconfigure -f noninteractive unattended-upgrades
cat > /etc/apt/apt.conf.d/52prestamedios-reinicio <<'EOF'
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "04:30";
EOF

echo "== Docker Engine y Compose (repositorio oficial de Docker)"
if ! command -v docker >/dev/null; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker

echo "== Usuario ${USUARIO} y carpeta ${RAIZ}"
id "$USUARIO" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$USUARIO"
usermod -aG docker "$USUARIO"
install -d -o "$USUARIO" -g "$USUARIO" "$RAIZ"

echo "== Código en el tag ${TAG}"
for repo in Backend-PrestaMeDios Frontend-PrestaMeDios; do
    if [[ ! -d "$RAIZ/$repo/.git" ]]; then
        sudo -u "$USUARIO" git clone -q "$ORG/$repo.git" "$RAIZ/$repo"
    fi
    sudo -u "$USUARIO" git -C "$RAIZ/$repo" fetch -q --tags
    sudo -u "$USUARIO" git -C "$RAIZ/$repo" checkout -q "refs/tags/${TAG}"
done

ENV="$RAIZ/Backend-PrestaMeDios/.env"
if [[ ! -f "$ENV" ]]; then
    install -m 600 -o "$USUARIO" -g "$USUARIO" "$RAIZ/Backend-PrestaMeDios/deploy/.env.prod.example" "$ENV"
    echo "Creado $ENV desde la plantilla: completarlo antes de levantar."
fi

cat <<EOF

== Listo lo automático. Falta (docs/instalacion.md):
  1. BIOS: encender al volver la energía. Disco cifrado (LUKS) si se instaló así.
  2. Tailscale para el acceso del equipo; SSH sólo con clave (PasswordAuthentication no,
     PermitRootLogin no) y una clave por operador (§6.10).
  3. Completar $ENV (secretos del gestor de contraseñas; permisos 600).
  4. Como ${USUARIO}:  cd $RAIZ/Backend-PrestaMeDios
       docker compose -f compose.prod.yaml build
       docker compose -f compose.prod.yaml up -d db
       docker compose -f compose.prod.yaml run --rm api alembic upgrade head
       docker compose -f compose.prod.yaml up -d
       docker compose -f compose.prod.yaml exec api python -m app.modules.users.cli crear-superadmin --email … --nombre … --apellido … --dni … --telefono …
  5. Cloudflare: hostname público del túnel → http://web:80. Monitoreo de /health/db y latidos.
EOF
