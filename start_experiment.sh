#!/bin/bash

echo "[start] preparing clean experiment environment"

echo "[start] stopping old watch/PDP processes"
bash /mnt/shared/island_mode/stop_watch.sh 2>/dev/null || true
bash /mnt/shared/local_pdp/stop_pdp.sh 2>/dev/null || true

echo "[start] cleaning logs, pid files and policy cache"
rm -f /tmp/island_audit.log
rm -f /tmp/island_topology_events.log
rm -f /tmp/island_phase
rm -f /tmp/traffic_probe.stop
rm -f /tmp/traffic_probe_start

rm -f /mnt/shared/island_mode/watch.log
rm -f /mnt/shared/island_mode/watch.pid
rm -f /mnt/shared/local_pdp/pdp.log
rm -f /mnt/shared/local_pdp/pdp.pid
rm -f /mnt/shared/island_mode/compiled_policy_cache.json
rm -f /mnt/shared/island_mode/shadow_repair_plan.json


echo "NORMAL" > /tmp/island_phase

echo "[start] restoring core/backhaul link"
bash /mnt/shared/island_mode/restore_core_link.sh 2>/dev/null || true

echo "[start] restoring mesh/access topology and clearing quarantine"
python3 /mnt/shared/island_mode/sdn_mesh_controller.py reset 2>/dev/null || true
python3 /mnt/shared/island_mode/sdn_mesh_controller.py clear-quarantine 2>/dev/null || true

echo "[start] restoring default forwarding and normal mode"
python3 /mnt/shared/island_mode/edge_mode_controller.py normal 2>/dev/null || true

echo "[start] starting local PDP"
bash /mnt/shared/local_pdp/start_pdp.sh

echo "[start] checking local PDP"
curl -s --max-time 2 http://10.0.0.50:8088/health || true
echo

echo "[start] mesh status"
python3 /mnt/shared/island_mode/sdn_mesh_controller.py trust-status 2>/dev/null || true

echo "[start] done"
