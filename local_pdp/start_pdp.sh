#!/bin/bash
set -e

CONTAINER="mn.pdp"
PDP_SRC="/mnt/shared/local_pdp/local_pdp_service.py"
CONFIG_SRC="/mnt/shared/island_mode"
PID_FILE="/mnt/shared/local_pdp/pdp.pid"

echo "[pdp] starting PDP inside Docker container: $CONTAINER"

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    echo "[pdp] ERROR: container $CONTAINER is not running"
    echo "[pdp] Start the topology first."
    exit 1
fi

echo "[pdp] adding host management IP on s6 if needed"
ip addr show dev s6 | grep -q "10.0.0.254/24" || ip addr add 10.0.0.254/24 dev s6
ip link set s6 up

echo "[pdp] installing host/controller access flows for PDP and audit"
ovs-ofctl add-flow s6 "priority=510,ip,nw_src=10.0.0.254,nw_dst=10.0.0.50,actions=NORMAL" 2>/dev/null || true
ovs-ofctl add-flow s6 "priority=510,ip,nw_src=10.0.0.254,nw_dst=10.0.0.60,actions=NORMAL" 2>/dev/null || true
ovs-ofctl add-flow s6 "priority=100,actions=NORMAL" 2>/dev/null || true

echo "[pdp] stopping old PDP process in container"
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

rm -f /tmp/pdp.log
'

echo "[pdp] copying PDP code and config files into container"
docker exec "$CONTAINER" sh -c 'mkdir -p /zt/config'

docker cp "$PDP_SRC" "$CONTAINER:/zt/local_pdp_service.py"
docker cp "$CONFIG_SRC/identity_cache.json" "$CONTAINER:/zt/config/identity_cache.json"
docker cp "$CONFIG_SRC/service_registry.json" "$CONTAINER:/zt/config/service_registry.json"
docker cp "$CONFIG_SRC/policy_model.json" "$CONTAINER:/zt/config/policy_model.json"

echo "[pdp] launching PDP on 0.0.0.0:8088 inside container"
docker exec -d "$CONTAINER" sh -c '
PDP_HOST=0.0.0.0 PDP_PORT=8088 PDP_CONFIG_DIR=/zt/config \
nohup python3 -u /zt/local_pdp_service.py >/tmp/pdp.log 2>&1 &
echo $! >/tmp/pdp.pid
'

echo "container:$CONTAINER" > "$PID_FILE"

echo "[pdp] waiting for PDP health at http://10.0.0.50:8088/health"
for i in $(seq 1 20); do
    if curl -s --connect-timeout 1 http://10.0.0.50:8088/health >/tmp/pdp_health.json 2>/dev/null; then
        cat /tmp/pdp_health.json
        echo ""
        echo "[pdp] started in container at http://10.0.0.50:8088"
        echo "[pdp] container log: docker exec $CONTAINER cat /tmp/pdp.log"
        exit 0
    fi
    sleep 1
done

echo "[pdp] ERROR: PDP did not become reachable from host/controller"
echo "[pdp] container-side log:"
docker exec "$CONTAINER" sh -c 'cat /tmp/pdp.log 2>/dev/null || true'
exit 1
