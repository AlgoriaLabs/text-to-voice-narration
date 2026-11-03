#!/bin/sh
# Starts the FastAPI app and the gateway in front of it. When either one stops, so does the other, and the container
# exits for its host to restart. A stop signal goes to the gateway first, which finishes the requests in flight; the
# API, which may be narrating for one of them, stops after it.

uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1 --log-level warning &
api=$!
node node_modules/@stellar-agent-services/provider-kit/dist/cli/index.js serve --config provider.config.json &
gateway=$!

asked=0
trap 'asked=1; kill -TERM "$gateway" 2>/dev/null; wait "$gateway" 2>/dev/null; kill -TERM "$api" 2>/dev/null' TERM INT
while kill -0 "$api" 2>/dev/null && kill -0 "$gateway" 2>/dev/null; do sleep 1; done
kill -TERM "$api" "$gateway" 2>/dev/null
wait
# 0 when asked to stop; 1 when one of them stopped by itself.
[ "$asked" = 1 ]
