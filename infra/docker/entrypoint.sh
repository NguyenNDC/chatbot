#!/bin/sh

set -eu

if [ "${PRELOAD_BGE_M3:-false}" = "true" ]; then
  echo "[entrypoint] Preloading BGE-M3 into ${HF_HOME:-/opt/hf-cache}"
  if ! python /app/infra/scripts/preload_bge_m3.py; then
    echo "[entrypoint] BGE-M3 preload failed; continuing without warm cache"
  fi
fi

exec "$@"
