#!/bin/bash

echo "[end] cleaning experiment environment"

echo "[end] stopping watch/PDP"
bash /mnt/shared/island_mode/stop_watch.sh 2>/dev/null || true
bash /mnt/shared/local_pdp/stop_pdp.sh 2>/dev/null || true

echo "[end] restoring core/backhaul link"
bash /mnt/shared/island_mode/restore_core_link.sh 2>/dev/null || true

echo "[end] restoring access/backhaul links"
ip link set s6-s2 up 2>/dev/null || true
ip link set s2-s6 up 2>/dev/null || true

ip link set s6-s3 up 2>/dev/null || true
ip link set s3-s6 up 2>/dev/null || true

ip link set s6-s4 up 2>/dev/null || true
ip link set s4-s6 up 2>/dev/null || true

ip link set s6-s5 up 2>/dev/null || true
ip link set s5-s6 up 2>/dev/null || true

ip link set s2-ap2 up 2>/dev/null || true
ip link set ap2-s2 up 2>/dev/null || true

ip link set s3-ap3 up 2>/dev/null || true
ip link set ap3-s3 up 2>/dev/null || true

ip link set s4-ap4 up 2>/dev/null || true
ip link set ap4-s4 up 2>/dev/null || true

ip link set s5-ap5 up 2>/dev/null || true
ip link set ap5-s5 up 2>/dev/null || true

echo "[end] disabling AP mesh fallback links"
ip link set ap2-ap3 down 2>/dev/null || true
ip link set ap3-ap2 down 2>/dev/null || true

ip link set ap3-ap4 down 2>/dev/null || true
ip link set ap4-ap3 down 2>/dev/null || true

ip link set ap4-ap5 down 2>/dev/null || true
ip link set ap5-ap4 down 2>/dev/null || true

echo "[end] restoring default forwarding and normal mode"
python3 /mnt/shared/island_mode/edge_mode_controller.py normal 2>/dev/null || true

echo "[end] done"
