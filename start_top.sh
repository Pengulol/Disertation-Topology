#!/bin/bash
set -e

echo "[cleanup] running Mininet cleanup"
sudo mn -c

echo "[cleanup] removing stale custom topology veth links"
for i in $(ip -o link show | awk -F': ' '{print $2}' | cut -d'@' -f1 | grep -E '^(s[0-9]+-(s[0-9]+|ap[0-9]+)|ap[0-9]+-(s[0-9]+|ap[0-9]+))$'); do
    echo "[cleanup] deleting stale link $i"
    sudo ip link del "$i" 2>/dev/null || true
done

echo "[cleanup] removing stale OVS bridges"
for br in s1 s2 s3 s4 s5 s6 s7 s8 ap2 ap3 ap4 ap5 ap6; do
    sudo ovs-vsctl --if-exists del-br "$br"
done

echo "[cleanup] removing old Mininet Docker containers"
sudo docker ps -a --format '{{.Names}}' | grep '^mn\.' | xargs -r sudo docker rm -f

echo "[start] starting topology"
sudo env PYTHONPATH=$HOME/mininet-wifi:$HOME/containernet-wifi python3 /mnt/shared/top-with-manet-and-containers.py
