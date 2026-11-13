#!/usr/bin/env bash
# Roda NO EC2 (chamado pelo GitHub Actions via SSH, ou na mao):
# atualiza o codigo para a branch do deploy e reconstroi o container.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BRANCH="${DEPLOY_BRANCH:-master}"
cd "$APP_DIR"

echo "==> $APP_DIR @ $BRANCH"
[ -f .env ] || { echo "ERRO: falta $APP_DIR/.env (copie .env.example e coloque a TOMORROW_API_KEY)"; exit 1; }

git fetch --prune origin "$BRANCH"
git checkout -q "$BRANCH"
git reset --hard "origin/$BRANCH"
echo "==> commit $(git log -1 --format='%h %s')"

NET="$(grep -E '^PROXY_NETWORK=' .env | cut -d= -f2- || true)"
NET="${NET:-fortran_default}"
docker network inspect "$NET" >/dev/null 2>&1 \
  || { echo "ERRO: rede docker '$NET' nao existe (o Caddy do ~/fortran esta no ar? ajuste PROXY_NETWORK no .env)"; exit 1; }

docker compose up -d --build --remove-orphans
docker image prune -f >/dev/null

echo "==> esperando /api/health"
for _ in $(seq 1 20); do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null; then
    echo "==> ok"; exit 0
  fi
  sleep 2
done
echo "ERRO: container nao respondeu; ultimos logs:"
docker compose logs --tail 50 notam-tw
exit 1
