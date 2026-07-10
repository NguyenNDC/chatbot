#!/bin/sh

set -eu

if [ -f /app/server.js ]; then
  exec node /app/server.js
fi

if [ -f /app/apps/web/server.js ]; then
  exec node /app/apps/web/server.js
fi

echo "[web-entrypoint] Could not find Next standalone server.js"
echo "[web-entrypoint] Checked /app/server.js and /app/apps/web/server.js"
exit 1
