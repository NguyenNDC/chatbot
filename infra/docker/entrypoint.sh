#!/bin/sh

set -eu

if [ "${PRELOAD_EMBEDDING_MODEL:-${PRELOAD_BGE_M3:-false}}" = "true" ]; then
  echo "[entrypoint] Preloading embedding provider ${EMBEDDING_PROVIDER:-unknown} (${EMBEDDING_MODEL_NAME:-unknown}) into ${HF_HOME:-/opt/hf-cache}"
  if ! python /app/infra/scripts/preload_bge_m3.py; then
    echo "[entrypoint] Embedding preload failed; continuing without warm cache"
  fi
fi

exec "$@"
