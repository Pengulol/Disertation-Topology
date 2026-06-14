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


def wait_container_http(name, timeout=5):
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        result = subprocess.run(
            [
                "docker", "exec", f"mn.{name}",
                "python3", "-c",
                "import socket; s=socket.socket(); print(s.connect_ex(('127.0.0.1',8000)))"
            ],
            text=True,
            capture_output=True
        )

        if result.stdout.strip() == "0":
            print(f"{name}: http server is ready")
            return True

    print(f"{name}: http server did not become ready")
    docker_exec(name, "cat /tmp/http.log 2>/dev/null || true")
    return False


def wait_reachable(node, ip, label, timeout=8):
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        result = node.cmd(f"ping -c 1 -W 1 {ip} >/dev/null 2>&1; echo $?").strip()

        if result == "0":
            print(f"{label}: reachable")
            return True

    print(f"{label}: not reachable")
    return False


def topology():
    net = Containernet(
        controller=Controller,
        switch=OVSKernelSwitch,
        # FIX: autoSetMacs ajuta ARP-ul sa functioneze corect
        autoSetMacs=True,
    )

    info("*** Adding controller\n")
    c0 = net.addController("c0")

    info("*** Adding central and edge switches\n")
    # FIX: failMode="standalone" pe toate switch-urile/AP-urile
    # In standalone, switch-ul invata adresele MAC singur (L2 learning)
    # si nu are nevoie de controller pentru forwarding de baza.
    # Nu mai apelam start([c0]) pe ele — standalone ignora controllerul oricum.
    s1 = net.addSwitch("s1", failMode="standalone")
    s6 = net.addSwitch("s6", failMode="standalone")

    info("*** Adding access zones\n")
    # FIX: canale non-overlapping: 1, 6, 11, 1 (ap5 refoloseste 1 — distanta spatiala mare)
    ap2 = net.addAccessPoint("ap2", ssid="zone2-responder", mode="g", channel="1",
                             position="20,50,0",  range=50, failMode="standalone")
    ap3 = net.addAccessPoint("ap3", ssid="zone3-users",    mode="g", channel="6",
                             position="50,50,0",  range=50, failMode="standalone")
    ap4 = net.addAccessPoint("ap4", ssid="zone4-iot",      mode="g", channel="11",
                             position="80,50,0",  range=50, failMode="standalone")
    ap5 = net.addAccessPoint("ap5", ssid="zone5-other",    mode="g", channel="1",
                             position="110,50,0", range=50, failMode="standalone")

    info("*** Adding stations\n")
    resp = net.addStation("resp", ip="10.0.0.101/24", position="20,40,0",
                          defaultRoute="via 10.0.0.1")
    usr  = net.addStation("usr",  ip="10.0.0.102/24", position="50,40,0",
                          defaultRoute="via 10.0.0.1")
    sens = net.addStation("sens", ip="10.0.0.103/24", position="80,40,0",
                          defaultRoute="via 10.0.0.1")
    atk  = net.addStation("atk",  ip="10.0.0.104/24", position="110,40,0",
                          defaultRoute="via 10.0.0.1")

    info("*** Adding central services\n")
    cidp  = net.addHost("cidp",  ip="10.0.0.10/24")
    cp    = net.addHost("cp",    ip="10.0.0.11/24")

    info("*** Adding edge services\n")
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

    info("*** Creating central links\n")
    net.addLink(cidp, s1)
    net.addLink(cp,   s1)

    info("*** Creating programmable core/backhaul/xhaul link\n")
    net.addLink(s1, s6, cls=TCLink, bw=50, delay="10ms", loss=0)

    info("*** Creating programmable access/edge xhaul links\n")
    net.addLink(s6, ap2, cls=TCLink, bw=20, delay="5ms", loss=0)
    net.addLink(s6, ap3, cls=TCLink, bw=20, delay="5ms", loss=0)
    net.addLink(s6, ap4, cls=TCLink, bw=20, delay="5ms", loss=0)
    net.addLink(s6, ap5, cls=TCLink, bw=20, delay="5ms", loss=0)

    info("*** Creating edge service links\n")
    net.addLink(crit,  s6)
    net.addLink(ncrit, s6)
    net.addLink(pdp,   s6)
    net.addLink(audit, s6)
    net.addLink(alert, s6)
    net.addLink(inet,  s6)

    # FIX: configureWifiNodes() DUPA toate addLink-urile
    info("*** Configuring Wi-Fi nodes\n")
    net.setPropagationModel(model="logDistance", exp=4)
    net.configureWifiNodes()

    info("*** Building network\n")
    net.build()

    info("*** Starting network\n")
    # FIX: controller pornit dar switch-urile standalone nu au nevoie de el
    # pentru forwarding — il pornim doar ca sa nu crape build()
    c0.start()
    # FIX: switch-urile standalone se pornesc cu lista goala, NU cu [c0]
    s1.start([])
    s6.start([])
    ap2.start([])
    ap3.start([])
    ap4.start([])
    ap5.start([])

    info("*** Configuring Docker MEC interfaces\n")
    configure_container_intf(crit, "crit-eth0", "10.0.0.30/24")
    configure_container_intf(ncrit, "ncrit-eth0", "10.0.0.40/24")
    configure_container_intf(pdp, "pdp-eth0", "10.0.0.50/24")
    configure_container_intf(audit, "audit-eth0", "10.0.0.60/24")
    configure_container_intf(alert, "alert-eth0", "10.0.0.31/24")


    info("*** Adding AP wireless interfaces to OVS bridges\n")
    for ap in [ap2, ap3, ap4, ap5]:
        ap.cmd(f"ovs-vsctl --may-exist add-port {ap.name} {ap.name}-wlan1")

    info("*** Installing default L2 forwarding rules\n")
    for br in [s1, s6, ap2, ap3, ap4, ap5]:
        br.cmd(f"ovs-ofctl del-flows {br.name}")
        br.cmd(f'ovs-ofctl add-flow {br.name} "priority=100,actions=NORMAL"')

    # FIX: asociere explicita prin setAssociation (API stabil in mn-wifi)
    # daca versiunea ta nu are setAssociation, foloseste blocul de iw de mai jos
    info("*** Forcing wireless associations\n")
    try:
        resp.setAssociation(ap2, intf="resp-wlan0")
        usr.setAssociation(ap3,  intf="usr-wlan0")
        sens.setAssociation(ap4, intf="sens-wlan0")
        atk.setAssociation(ap5,  intf="atk-wlan0")
        info("*** setAssociation OK\n")
    except Exception:
        info("*** setAssociation indisponibil, folosim iw connect\n")
        resp.cmd("iw dev resp-wlan0 connect zone2-responder")
        usr.cmd("iw dev usr-wlan0 connect zone3-users")
        sens.cmd("iw dev sens-wlan0 connect zone4-iot")
        atk.cmd("iw dev atk-wlan0 connect zone5-other")

    sleep(2)
    net.staticArp()

    # FIX: toate hosturile sunt pe acelasi subnet /24 — nu e nevoie de routing,
    # doar ARP trebuie sa functioneze. Cu autoSetMacs=True si standalone
    # switch-urile invata MAC-urile din trafic. Facem un ping scurt
    # pentru a "incalzi" tabla ARP/MAC inainte de CLI.
    info("*** Warming up ARP tables (poate dura 5-10s)...\n")
    for host in [cidp, cp, crit, alert, ncrit, pdp, audit, inet]:
        resp.cmd(f"ping -c 1 -W 1 {host.IP()} > /dev/null 2>&1 &")

    info("*** Starting simple HTTP services\n")
    
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

    info("\n*** Normal mode tests:\n")
    info("resp curl -s http://10.0.0.10:8000   # central identity\n")
    info("resp curl -s http://10.0.0.11:8000   # central policy\n")
    info("resp curl -s http://10.0.0.30:8000   # critical service\n")
    info("resp curl -s http://10.0.0.40:8000   # non-critical service\n")
    info("resp curl -s http://10.0.0.70:8000   # internet/data network\n\n")

    info("*** Daca ping/curl esueaza inca, ruleaza manual in CLI:\n")
    info("sh ovs-ofctl add-flow s1 priority=0,actions=NORMAL\n")
    info("sh ovs-ofctl add-flow s6 priority=0,actions=NORMAL\n")
    info("sh ovs-ofctl add-flow ap2 priority=0,actions=NORMAL\n")
    info("sh ovs-ofctl add-flow ap3 priority=0,actions=NORMAL\n")
    info("sh ovs-ofctl add-flow ap4 priority=0,actions=NORMAL\n")
    info("sh ovs-ofctl add-flow ap5 priority=0,actions=NORMAL\n\n")

    info("*** Link tests:\n")
    info("link s1 s6 down      # simulate central/core/backhaul outage\n")
    info("link s1 s6 up        # restore central/core/backhaul\n")
    info("link s6 ap5 down     # isolate access zone ap5\n")
    info("link s6 ap5 up       # restore access zone ap5\n\n")


    info("*** Integrated topology readiness checks\n")
    

    wait_reachable(resp, "10.0.0.30", "resp -> critical coordination container")
    wait_reachable(resp, "10.0.0.31", "resp -> critical alert container")
    wait_reachable(resp, "10.0.0.40", "resp -> non-critical container")
    wait_reachable(resp, "10.0.0.50", "resp -> local PDP MEC container")
    wait_reachable(resp, "10.0.0.60", "resp -> audit MEC container")

    info(resp.cmd("curl --connect-timeout 2 http://10.0.0.30:8000"))
    info(resp.cmd("curl --connect-timeout 2 http://10.0.0.31:8000"))
    info(resp.cmd("curl --connect-timeout 2 http://10.0.0.40:8000"))
    info(resp.cmd("curl --connect-timeout 2 http://10.0.0.50:8000"))
    info(resp.cmd("curl --connect-timeout 2 http://10.0.0.60:8000"))

    CLI(net)

    info("*** Stopping network\n")
    net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    topology()
