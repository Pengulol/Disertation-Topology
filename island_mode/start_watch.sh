#!/bin/bash

LOG_FILE="/mnt/shared/island_mode/watch.log"
PID_FILE="/mnt/shared/island_mode/watch.pid"
CONTROLLER="/mnt/shared/island_mode/edge_mode_controller.py"

rm -f "$LOG_FILE" "$PID_FILE"

nohup python3 -u "$CONTROLLER" watch > "$LOG_FILE" 2>&1 &

echo $! > "$PID_FILE"

echo "[watch] started with PID $(cat "$PID_FILE")"
echo "[watch] log: $LOG_FILE"
