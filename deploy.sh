#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  SUDO="sudo"
fi

docker_ready() {
  command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1
}

install_docker() {
  if [ ! -r /etc/os-release ] || ! grep -qi '^ID=ubuntu$' /etc/os-release; then
    echo "Docker не найден. Автоустановка рассчитана на Ubuntu." >&2
    exit 1
  fi

  $SUDO apt-get update
  $SUDO apt-get install -y ca-certificates curl
  $SUDO install -m 0755 -d /etc/apt/keyrings
  $SUDO curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  $SUDO chmod a+r /etc/apt/keyrings/docker.asc

  # shellcheck disable=SC1091
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    | $SUDO tee /etc/apt/sources.list.d/docker.list >/dev/null

  $SUDO apt-get update
  $SUDO apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  $SUDO systemctl enable --now docker
}

if ! docker_ready; then
  install_docker
fi

if ! $SUDO systemctl is-active --quiet docker; then
  $SUDO systemctl enable --now docker
fi

if [ ! -f .env ]; then
  cp .env.example .env
fi

if docker info >/dev/null 2>&1; then
  docker compose up -d --build
else
  $SUDO docker compose up -d --build
fi

echo "Приложение: http://localhost:8000"
echo "Консоль MinIO: http://localhost:9001"
