#!/bin/bash
set -e

CONTAINER="mn.audit"
AUDIT_SRC="/mnt/shared/audit/audit_service.py"
PID_FILE="/mnt/shared/audit/audit.pid"

echo "[audit] starting audit collector inside Docker container: $CONTAINER"

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    echo "[audit] ERROR: container $CONTAINER is not running"
    echo "[audit] Start the topology first."
    exit 1
fi

echo "[audit] stopping old audit service in container"
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

rm -f /tmp/audit.log /tmp/audit_events.jsonl
'

echo "[audit] copying audit service"
docker cp "$AUDIT_SRC" "$CONTAINER:/zt_audit_service.py"

echo "[audit] launching service on 0.0.0.0:8090"
docker exec -d "$CONTAINER" sh -c '
nohup python3 -u /zt_audit_service.py >/tmp/audit.log 2>&1 &
echo $! >/tmp/audit.pid
'

echo "container:$CONTAINER" > "$PID_FILE"

echo "[audit] waiting for health at http://10.0.0.60:8090/health"
for i in $(seq 1 20); do
    if curl -s --connect-timeout 1 http://10.0.0.60:8090/health >/tmp/audit_health.json 2>/dev/null; then
        cat /tmp/audit_health.json
        echo ""
        echo "[audit] started at http://10.0.0.60:8090"
        exit 0
    fi
    sleep 1
done

echo "[audit] ERROR: audit collector did not become reachable"
docker exec "$CONTAINER" sh -c 'cat /tmp/audit.log 2>/dev/null || true'
exit 1
