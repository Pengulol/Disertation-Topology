#!/bin/bash

PID_FILE="/mnt/shared/island_mode/watch.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "[watch] no PID file found"
    exit 0
fi

PID=$(cat "$PID_FILE")

if kill "$PID" 2>/dev/null; then
    echo "[watch] stopped PID $PID"
    rm -f "$PID_FILE"
else
    echo "[watch] process not running"
    rm -f "$PID_FILE"
fi
