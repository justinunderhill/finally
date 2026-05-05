#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

if [ "${1:-}" = "--build" ] || ! docker image inspect finally:latest >/dev/null 2>&1; then
  docker build -t finally:latest .
fi

if docker ps -a --format "{{.Names}}" | grep -q "^finally$"; then
  docker stop finally >/dev/null 2>&1 || true
  docker rm finally >/dev/null 2>&1 || true
fi

docker run \
  --detach \
  --name finally \
  --volume finally-data:/app/db \
  --publish 8000:8000 \
  --env-file .env \
  finally:latest >/dev/null

printf "FinAlly is running at http://localhost:8000\n"
