#!/bin/bash

CONTAINER="mn.audit"
PID_FILE="/mnt/shared/audit/audit.pid"

echo "[audit] stopping audit collector inside Docker container: $CONTAINER"

if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    docker exec "$CONTAINER" sh -c '
    if [ -f /tmp/audit.pid ]; then
        OLD_PID=$(cat /tmp/audit.pid)
        kill "$OLD_PID" 2>/dev/null || true
        rm -f /tmp/audit.pid
    fi

    PIDS=$(pgrep -f "[a]udit_service.py" 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        kill $PIDS 2>/dev/null || true
    fi
    '

    echo "[audit] stopped"
else
    echo "[audit] container $CONTAINER is not running"
fi

rm -f "$PID_FILE"
