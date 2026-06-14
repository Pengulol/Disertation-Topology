#!/bin/bash

echo "[degraded] applying delay/loss/rate-limit on s1-s6 link"

tc qdisc replace dev s6-eth1 root netem delay 250ms loss 20% rate 5mbit
tc qdisc replace dev s1-eth3 root netem delay 250ms loss 20% rate 5mbit

echo "[degraded] done"
