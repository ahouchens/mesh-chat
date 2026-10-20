#!/usr/bin/env bash
set -euo pipefail

# Least-friction Mesh Chat TURN relay installer.
# Tested target: Ubuntu 22.04/24.04 or Debian 12 with a public IPv4 address.
# It intentionally uses TURN over TCP 443 (no domain/TLS certificate).

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo ./deploy/relay/install.sh" >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${INSTALL_DIR:-/opt/mesh-chat-relay}"
TURN_ALT_PORT="${TURN_ALT_PORT:-443}"
RELAY_PORT_MIN="${RELAY_PORT_MIN:-49160}"
RELAY_PORT_MAX="${RELAY_PORT_MAX:-49300}"
TURN_USER="${TURN_USER:-meshchat}"
REALM="${REALM:-mesh-chat-relay}"

if ! command -v curl >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y curl
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker..."
  curl -fsSL https://get.docker.com | sh
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is required." >&2
  exit 1
fi

PUBLIC_IP="${PUBLIC_IP:-}"
if [[ -z "${PUBLIC_IP}" ]]; then
  PUBLIC_IP="$(curl -4 -fsS --max-time 10 https://api.ipify.org || true)"
fi
if [[ -z "${PUBLIC_IP}" ]]; then
  echo "Could not detect the public IPv4 address. Re-run with PUBLIC_IP=x.x.x.x." >&2
  exit 1
fi

PRIVATE_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") { print $(i+1); exit }}')"
if [[ -z "${PRIVATE_IP}" ]]; then
  PRIVATE_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
fi
if [[ -z "${PRIVATE_IP}" ]]; then
  echo "Could not detect the private IPv4 address." >&2
  exit 1
fi

# Cloud providers commonly NAT a private interface to a public IPv4. Coturn
# needs the public/private mapping in that case, but only the public address
# when it is assigned directly to an interface.
if ip -4 addr show 2>/dev/null | grep -q "inet ${PUBLIC_IP}/"; then
  EXTERNAL_IP="${PUBLIC_IP}"
  RELAY_IP="${PUBLIC_IP}"
else
  EXTERNAL_IP="${PUBLIC_IP}/${PRIVATE_IP}"
  RELAY_IP="${PRIVATE_IP}"
fi

if [[ -z "${TURN_PASSWORD:-}" ]]; then
  TURN_PASSWORD="$(openssl rand -hex 16 2>/dev/null || od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
fi

if ss -ltnup 2>/dev/null | grep -Eq ":(${TURN_ALT_PORT})\b"; then
  echo "Port ${TURN_ALT_PORT} is already in use. Set TURN_ALT_PORT to a free port and retry." >&2
  exit 1
fi

install -d -m 700 "${INSTALL_DIR}"
if [[ -f "${SCRIPT_DIR}/docker-compose.yml" ]]; then
  cp "${SCRIPT_DIR}/docker-compose.yml" "${INSTALL_DIR}/docker-compose.yml"
else
  curl -fsSL --max-time 30 \
    "https://raw.githubusercontent.com/ahouchens/mesh-chat/main/deploy/relay/docker-compose.yml" \
    -o "${INSTALL_DIR}/docker-compose.yml"
fi
cat > "${INSTALL_DIR}/.env" <<EOF
PUBLIC_IP=${PUBLIC_IP}
PRIVATE_IP=${PRIVATE_IP}
EXTERNAL_IP=${EXTERNAL_IP}
RELAY_IP=${RELAY_IP}
TURN_USER=${TURN_USER}
TURN_PASSWORD=${TURN_PASSWORD}
REALM=${REALM}
TURN_ALT_PORT=${TURN_ALT_PORT}
RELAY_PORT_MIN=${RELAY_PORT_MIN}
RELAY_PORT_MAX=${RELAY_PORT_MAX}
EOF
chmod 600 "${INSTALL_DIR}/.env"

if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow 3478/tcp >/dev/null
  ufw allow 3478/udp >/dev/null
  ufw allow "${TURN_ALT_PORT}"/tcp >/dev/null
  ufw allow "${TURN_ALT_PORT}"/udp >/dev/null
  ufw allow "${RELAY_PORT_MIN}:${RELAY_PORT_MAX}"/udp >/dev/null
  echo "Opened TURN ports in ufw."
fi

cd "${INSTALL_DIR}"
docker compose pull
docker compose up -d

sleep 2
if ! docker inspect -f '{{.State.Running}}' mesh-chat-relay 2>/dev/null | grep -q true; then
  echo "The relay container is not running. Recent logs:" >&2
  docker compose logs --tail 50 >&2
  exit 1
fi

cat <<EOF

Mesh Chat relay is running.

TURN URL (preferred, TCP 443):
  turn:${PUBLIC_IP}:${TURN_ALT_PORT}?transport=tcp

TURN URL (UDP 3478):
  turn:${PUBLIC_IP}:3478?transport=udp

Username: ${TURN_USER}
Password: ${TURN_PASSWORD}

Enter the preferred URL, username, and password in Mesh Chat on both devices:
Settings -> WebRTC calls -> TURN server.

Open these ports in the cloud security group / firewall:
  3478/tcp, 3478/udp, ${TURN_ALT_PORT}/tcp, ${TURN_ALT_PORT}/udp,
  ${RELAY_PORT_MIN}-${RELAY_PORT_MAX}/udp

Credentials are stored in ${INSTALL_DIR}/.env (mode 600).
Re-run with PUBLIC_IP=x.x.x.x to repair a changed address, or set
TURN_PASSWORD=... to rotate the password.

Check logs:
  cd ${INSTALL_DIR} && docker compose logs -f --tail 50

TURN over TLS on 443 (turns:) is not configured. Add a DNS name and a real
certificate if your network blocks plain TCP 443; do not use a self-signed
certificate for turns:.
EOF
