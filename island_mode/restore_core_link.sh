#!/bin/bash

echo "[normal] restoring s1-s6 core/backhaul link"

ip link set s6-eth1 up 2>/dev/null || true
ip link set s1-eth3 up 2>/dev/null || true

tc qdisc del dev s6-eth1 root 2>/dev/null || true
tc qdisc del dev s1-eth3 root 2>/dev/null || true

echo "[normal] done"
