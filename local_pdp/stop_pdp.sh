#!/bin/bash

CONTAINER="mn.pdp"
PID_FILE="/mnt/shared/local_pdp/pdp.pid"

echo "[pdp] stopping PDP inside Docker container: $CONTAINER"

if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    docker exec "$CONTAINER" sh -c '
    if [ -f /tmp/pdp.pid ]; then
        OLD_PID=$(cat /tmp/pdp.pid)
        kill "$OLD_PID" 2>/dev/null || true
        rm -f /tmp/pdp.pid
    fi

    PIDS=$(pgrep -f "[l]ocal_pdp_service.py" 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        kill $PIDS 2>/dev/null || true
    fi
    '
    echo "[pdp] stopped container PDP"
else
    echo "[pdp] container $CONTAINER is not running"
fi

rm -f "$PID_FILE"
