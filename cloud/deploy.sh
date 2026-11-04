#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

echo "=========================================================="
echo " Deploying Telegram Personal Client on Cloud (Docker)"
echo "=========================================================="

if [ ! -f .env ]; then
    echo "[ERROR] .env file not found in cloud/ directory!"
    echo "Please copy cloud/.env.example to cloud/.env and configure your secrets."
    exit 1
fi

chmod 600 .env

echo "Building Docker container image..."
docker compose build

echo "Starting container in background..."
docker compose up -d

echo ""
echo "Checking container status..."
docker compose ps

echo ""
echo "Deployment completed!"
echo "Useful commands:"
echo "  View logs        : docker compose logs -f"
echo "  Check health     : docker compose ps"
echo "  Stop container   : docker compose down"
echo "  Restart container: docker compose restart"
