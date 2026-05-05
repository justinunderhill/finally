#!/usr/bin/env sh
set -eu

if docker ps -a --format "{{.Names}}" | grep -q "^finally$"; then
  docker stop finally >/dev/null 2>&1 || true
  docker rm finally >/dev/null 2>&1 || true
  printf "Stopped FinAlly.\n"
else
  printf "FinAlly is not running.\n"
fi
