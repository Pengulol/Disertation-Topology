#!/usr/bin/env python3

from mininet.log import setLogLevel, info
from mininet.node import Controller, OVSKernelSwitch, OVSSwitch
from mininet.link import TCLink
from containernet.net import Containernet
from containernet.cli import CLI
import subprocess
import time
from time import sleep

def start_http(host, text):
    host.cmd(f"mkdir -p /tmp/{host.name}")
    host.cmd(f"echo '{text}' > /tmp/{host.name}/index.html")
    host.cmd(f"cd /tmp/{host.name} && python3 -m http.server 8000 >/tmp/{host.name}.log 2>&1 &")

def docker_exec(name, command, detach=False):
    cmd = ["docker", "exec"]

    if detach:
        cmd.append("-d")

    cmd.extend([f"mn.{name}", "bash", "-lc", command])

    result = subprocess.run(cmd, text=True, capture_output=True)

    if result.stdout:
        print(result.stdout, end="")

    if result.stderr:
        print(result.stderr, end="")

    return result.returncode


def configure_container_intf(node, intf, ip):
    print(node.cmd(f"ip link set {intf} up"), end="")
    print(node.cmd(f"ip addr flush dev {intf}"), end="")
    print(node.cmd(f"ip addr add {ip} dev {intf}"), end="")


def start_container_http(name, text):
    command = (
        "mkdir -p /www && "
        f"echo {text} > /www/index.html && "
        "cd /www && "
        "python3 -m http.server 8000 --bind 0.0.0.0 "
        ">/tmp/http.log 2>&1"
    )

    return docker_exec(name, command, detach=True)


def wait_container_http(name, timeout=3):
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        result = subprocess.run(
            [
                "docker", "exec", f"mn.{name}",
                "python3", "-c",
                "import socket; s=socket.socket(); s.settimeout(0.2); print(s.connect_ex(('127.0.0.1',8000)))"
            ],
            text=True,
            capture_output=True
        )

        if result.stdout.strip() == "0":
            print(f"{name}: http server is ready")
            return True

        time.sleep(0.2)

    print(f"{name}: http server did not become ready")
    docker_exec(name, "cat /tmp/http.log 2>/dev/null || true")
    return False


def wait_reachable(node, ip, label, timeout=2):
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        result = node.cmd(f"ping -c 1 -W 1 {ip} >/dev/null 2>&1; echo $?").strip()

        if result == "0":
            print(f"{label}: reachable")
            return True

        time.sleep(0.2)

    print(f"{label}: not reachable")
    return False


def topology():
    net = Containernet(
        controller=Controller,
        switch=OVSKernelSwitch,
        # autoSetMacs=True,
        autoSetMacs=False,
    )

    info("\n\n\n Adding controller")
    c0 = net.addController("c0")

    info("\n\n\n Adding central and edge switches")

    s1 = net.addSwitch("s1", failMode="standalone")
    s6 = net.addSwitch("s6", failMode="standalone")

    info("\n\n\n Adding city access/backhaul switches")
    s2 = net.addSwitch("s2", failMode="standalone")
    s3 = net.addSwitch("s3", failMode="standalone")
    s4 = net.addSwitch("s4", failMode="standalone")
    s5 = net.addSwitch("s5", failMode="standalone")

    info("\n\n\n Adding second island switches")
    s7 = net.addSwitch("s7", failMode="standalone")
    s8 = net.addSwitch("s8", failMode="standalone")

    info("\n\n\n Adding access zones\n")
    ap2 = net.addAccessPoint("ap2", ssid="zone2-responder", mode="g", channel="6",
                             position="20,50,0",  range=50, failMode="standalone")
    ap3 = net.addAccessPoint("ap3", ssid="zone3-users",    mode="g", channel="6",
                             position="50,50,0",  range=50, failMode="standalone")
    ap4 = net.addAccessPoint("ap4", ssid="zone4-iot",      mode="g", channel="6",
                             position="80,50,0",  range=50, failMode="standalone")
    ap5 = net.addAccessPoint("ap5", ssid="zone5-other",    mode="g", channel="6",
                             position="110,50,0", range=50, failMode="standalone")

    ap6 = net.addAccessPoint("ap6",ssid="zone6-second-island",mode="g",channel="6",
                             position="155,50,0",range=45,failMode="standalone")


    info("\n\n\n Adding stations")
    resp = net.addStation(
        "resp",
        ip="10.0.0.101/24",
        mac="02:00:00:00:01:01",
        position="20,40,0",
        defaultRoute="via 10.0.0.1"
    )

    usr = net.addStation(
        "usr",
        ip="10.0.0.102/24",
        mac="02:00:00:00:01:02",
        position="50,40,0",
        defaultRoute="via 10.0.0.1"
    )

    sens = net.addStation(
        "sens",
        ip="10.0.0.103/24",
        mac="02:00:00:00:01:03",
        position="80,40,0",
        defaultRoute="via 10.0.0.1"
    )

    atk = net.addStation(
        "atk",
        ip="10.0.0.104/24",
        mac="02:00:00:00:01:04",
        position="110,40,0",
        defaultRoute="via 10.0.0.1"
    )

    resp2 = net.addStation(
        "resp2",
        ip="10.0.0.111/24",
        mac="02:00:00:00:02:01",
        position="155,40,0",
        defaultRoute="via 10.0.0.1"
    )

    usr2 = net.addStation(
        "usr2",
        ip="10.0.0.112/24",
        mac="02:00:00:00:02:02",
        position="158,40,0",
        defaultRoute="via 10.0.0.1"
    )

    sens2 = net.addStation(
        "sens2",
        ip="10.0.0.113/24",
        mac="02:00:00:00:02:03",
        position="152,40,0",
        defaultRoute="via 10.0.0.1"
    )

    atk2 = net.addStation(
        "atk2",
        ip="10.0.0.114/24",
        mac="02:00:00:00:02:04",
        position="160,40,0",
        defaultRoute="via 10.0.0.1"
    )

    info("\n\n\n Adding central services")
    cidp  = net.addHost("cidp",  ip="10.0.0.10/24")
    cp    = net.addHost("cp",    ip="10.0.0.11/24")

    info("\n\n\n Adding edge services")
    crit = net.addDocker(
       "crit",
        ip="10.0.0.30/24",
        dimage="mec-python:latest",
        dcmd="/bin/bash ",
        rm=True
    )

    alert = net.addDocker(
        "alert",
        ip="10.0.0.31/24",
        dimage="mec-python:latest",
        dcmd="/bin/bash",
        rm=True
    )
    
    ncrit = net.addDocker(
        "ncrit",
        ip="10.0.0.40/24",
        dimage="mec-python:latest",
        dcmd="/bin/bash",
        rm=True
    )
    
    pdp = net.addDocker(
        "pdp",
        ip="10.0.0.50/24",
        dimage="mec-python:latest",
        dcmd="/bin/bash",
        rm=True
    )

    audit = net.addDocker(
        "audit",
        ip="10.0.0.60/24",
        dimage="mec-python:latest",
        dcmd="/bin/bash",
        rm=True
    )

    inet = net.addHost("inet", ip="10.0.0.70/24")

    info("\n\n\n Creating central links")
    net.addLink(cidp, s1)
    net.addLink(cp,   s1)

    info("\n\n\n Creating programmable core/backhaul/xhaul link\n")
    net.addLink(s1, s6, cls=TCLink, bw=50, delay="10ms", loss=0)

    info("\n\n\n Creating city access/backhaul links\n")
    net.addLink(
        s6, s2,
        cls=TCLink,
        bw=20,
        delay="5ms",
        loss=0,
        intfName1="s6-s2",
        intfName2="s2-s6"
    )

    net.addLink(
        s6, s3,
        cls=TCLink,
        bw=20,
        delay="5ms",
        loss=0,
        intfName1="s6-s3",
        intfName2="s3-s6"
    )

    net.addLink(
        s6, s4,
        cls=TCLink,
        bw=20,
        delay="5ms",
        loss=0,
        intfName1="s6-s4",
        intfName2="s4-s6"
    )

    net.addLink(
        s6, s5,
        cls=TCLink,
        bw=20,
        delay="5ms",
        loss=0,
        intfName1="s6-s5",
        intfName2="s5-s6"
    )

    info("\n\n\n Creating AP attachment links to city access points\n")
    net.addLink(
        s2, ap2,
        cls=TCLink,
        bw=20,
        delay="5ms",
        loss=0,
        intfName1="s2-ap2",
        intfName2="ap2-s2"
    )

    net.addLink(
        s3, ap3,
        cls=TCLink,
        bw=20,
        delay="5ms",
        loss=0,
        intfName1="s3-ap3",
        intfName2="ap3-s3"
    )

    net.addLink(
        s4, ap4,
        cls=TCLink,
        bw=20,
        delay="5ms",
        loss=0,
        intfName1="s4-ap4",
        intfName2="ap4-s4"
    )

    net.addLink(
        s5, ap5,
        cls=TCLink,
        bw=20,
        delay="5ms",
        loss=0,
        intfName1="s5-ap5",
        intfName2="ap5-s5"
    )

    info("\n\n\n Creating AP-level MANET/mesh fallback links\n")
    net.addLink(
        ap2, ap3,
        cls=TCLink,
        bw=5,
        delay="20ms",
        loss=1,
        intfName1="ap2-ap3",
        intfName2="ap3-ap2"
    )

    net.addLink(
        ap3, ap4,
        cls=TCLink,
        bw=5,
        delay="20ms",
        loss=1,
        intfName1="ap3-ap4",
        intfName2="ap4-ap3"
    )

    net.addLink(
        ap4, ap5,
        cls=TCLink,
        bw=5,
        delay="20ms",
        loss=1,
        intfName1="ap4-ap5",
        intfName2="ap5-ap4"
    )
    net.addLink(
        ap3, ap5,
        cls=TCLink,
        bw=5,
        delay="25ms",
        loss=1,
        intfName1="ap3-ap5",
        intfName2="ap5-ap3"
    )

    info("\n\n\n Creating second island links")

    net.addLink(
        s1, s7,
        intfName1="s1-s7",
        intfName2="s7-s1"
    )

    net.addLink(
        s7, s8,
        intfName1="s7-s8",
        intfName2="s8-s7"
    )

    net.addLink(
        s8, ap6,
        intfName1="s8-ap6",
        intfName2="ap6-s8"
    )


    net.addLink(
        s6, s7,
        intfName1="s6-s7",
        intfName2="s7-s6"
    )


    info("\n\n\n Creating edge service links")
    net.addLink(crit,  s6)
    net.addLink(ncrit, s6)
    net.addLink(pdp,   s6)
    net.addLink(audit, s6)
    net.addLink(alert, s6)
    net.addLink(inet,  s6)

    info("\n\n\n Configuring Wi-Fi nodes")
    net.setPropagationModel(model="logDistance", exp=4)
    net.configureWifiNodes()

    info("\n\n\n Building network")
    net.build()

    info("\n\n\n Starting network")
    c0.start()
    
    s1.start([])
    s6.start([])

    s2.start([])
    s3.start([])
    s4.start([])
    s5.start([])
    s7.start([])
    s8.start([])

    ap2.start([])
    ap3.start([])
    ap4.start([])
    ap5.start([])
    ap6.start([])

    info("\n\n\n Configuring Docker MEC interfaces")
    configure_container_intf(crit, "crit-eth0", "10.0.0.30/24")
    configure_container_intf(ncrit, "ncrit-eth0", "10.0.0.40/24")
    configure_container_intf(pdp, "pdp-eth0", "10.0.0.50/24")
    configure_container_intf(audit, "audit-eth0", "10.0.0.60/24")
    configure_container_intf(alert, "alert-eth0", "10.0.0.31/24")


    info("\n\n\n Adding AP wireless interfaces to OVS bridges")
    for ap in [ap2, ap3, ap4, ap5, ap6]:
        ap.cmd(f"ovs-vsctl --may-exist add-port {ap.name} {ap.name}-wlan1")

    info("\n\n\n Installing default L2 forwarding rules")
    for br in [s1, s6, s2, s3, s4, s5, s7, s8, ap2, ap3, ap4, ap5, ap6]:
        br.cmd(f"ovs-ofctl del-flows {br.name}")
        br.cmd(f'ovs-ofctl add-flow {br.name} "priority=100,actions=NORMAL"')

    info("\n\n\n Disabling AP-level MANET/mesh fallback links by default")
    ap2.cmd("ip link set ap2-ap3 down")
    ap3.cmd("ip link set ap3-ap2 down")

    ap3.cmd("ip link set ap3-ap4 down")
    ap4.cmd("ip link set ap4-ap3 down")

    ap4.cmd("ip link set ap4-ap5 down")
    ap5.cmd("ip link set ap5-ap4 down")

    ap3.cmd("ip link set ap3-ap5 down")
    ap5.cmd("ip link set ap5-ap3 down")

    info("\n\n\n Disabling inter-island fallback link by default")
    s6.cmd("ip link set s6-s7 down")
    s7.cmd("ip link set s7-s6 down")

    info("\n\n\n Forcing wireless associations")

    resp.setAssociation(ap2, intf="resp-wlan0")
    usr.setAssociation(ap3,  intf="usr-wlan0")
    sens.setAssociation(ap4, intf="sens-wlan0")
    atk.setAssociation(ap5,  intf="atk-wlan0")
    resp2.setAssociation(ap6, intf="resp2-wlan0")
    usr2.setAssociation(ap6, intf="usr2-wlan0")
    sens2.setAssociation(ap6, intf="sens2-wlan0")
    atk2.setAssociation(ap6, intf="atk2-wlan0")
    info("\n\n\n setAssociation OK\n")

    sleep(2)


    info("\n\n\n Flushing neighbour tables before dynamic ARP warm-up\n")
    for host in [resp, usr, sens, atk, resp2, usr2, sens2, atk2, cidp, cp, crit, alert, ncrit, pdp, audit, inet]:
        host.cmd("ip neigh flush all 2>/dev/null || true")

    info("\n\n\n Warming up ARP/MAC tables sequentially...\n")
    for host in [cidp, cp, crit, alert, ncrit, pdp, audit, inet]:
        resp.cmd(f"ping -c 2 -W 1 {host.IP()} > /dev/null 2>&1")
        host.cmd(f"ping -c 1 -W 1 {resp.IP()} > /dev/null 2>&1")


    info("\n\n\n Starting simple HTTP services\n")
    
    start_http(cidp,  "central-identity-provider")
    start_http(cp,    "central-policy-server")
    
    start_container_http("crit", "critical-container-service")
    start_container_http("ncrit", "non-critical-container-service")
    start_container_http("pdp", "local-pdp-mec-service")
    start_container_http("audit", "audit-buffer-mec-service")
    start_container_http("alert", "critical-alert-service")
    
    for container_name in ["crit", "alert", "ncrit", "pdp", "audit"]:
        if not wait_container_http(container_name):
            raise RuntimeError(f"{container_name} container HTTP server failed")


    start_http(inet,  "internet-data-network-placeholder")


    info("\n\n\n City access topology:\n")
    info("s6 -> s2 -> ap2 -> resp\n")
    info("s6 -> s3 -> ap3 -> usr\n")
    info("s6 -> s4 -> ap4 -> sens\n")
    info("s6 -> s5 -> ap5 -> atk\n\n")
    info("s1 -> s7 -> s8 -> ap6 -> resp2/usr2/sens2/atk2\n")
    info("inter-island fallback: s6 <-> s7 disabled by default\n\n")

    info("\n\n\n Topology started\n")
    info("source /mnt/shared/test/test-manet/scenario_topology_baseline\n\n")

    CLI(net)

    info("\n\n\n Stopping network\n")
    net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    topology()
