#!/usr/bin/env python3

from mininet.log import setLogLevel, info
from mininet.node import Controller, OVSKernelSwitch, OVSSwitch
from mininet.link import TCLink
from mn_wifi.net import Mininet_wifi
from mn_wifi.cli import CLI
from time import sleep

def start_http(host, text):
    host.cmd(f"mkdir -p /tmp/{host.name}")
    host.cmd(f"echo '{text}' > /tmp/{host.name}/index.html")
    host.cmd(f"cd /tmp/{host.name} && python3 -m http.server 8000 >/tmp/{host.name}.log 2>&1 &")


def topology():
    net = Mininet_wifi(
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
    crit  = net.addHost("crit",  ip="10.0.0.30/24")
    ncrit = net.addHost("ncrit", ip="10.0.0.40/24")
    pdp   = net.addHost("pdp",   ip="10.0.0.50/24")
    audit = net.addHost("audit", ip="10.0.0.60/24")
    inet  = net.addHost("inet",  ip="10.0.0.70/24")

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
    for host in [cidp, cp, crit, ncrit, pdp, audit, inet]:
        resp.cmd(f"ping -c 1 -W 1 {host.IP()} > /dev/null 2>&1 &")

    info("*** Starting simple HTTP services\n")
    start_http(cidp,  "central-identity-provider")
    start_http(cp,    "central-policy-server")
    start_http(crit,  "critical-service")
    start_http(ncrit, "non-critical-service")
    start_http(pdp,   "local-pdp-placeholder")
    start_http(audit, "audit-buffer-placeholder")
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

    CLI(net)

    info("*** Stopping network\n")
    net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    topology()
