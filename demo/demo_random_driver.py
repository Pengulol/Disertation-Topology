import json
import os
import random
import subprocess
import time
from pathlib import Path

RESULTS_DIR = Path(os.environ.get("DEMO_RESULTS_DIR", "/mnt/shared/results/demo_run"))
METRICS = RESULTS_DIR / "demo_metrics.csv"
EVENT_LOG = RESULTS_DIR / "demo_events.log"

PHASE_FILE = Path("/tmp/island_phase")
STOP_FILE = Path("/tmp/traffic_probe.stop")
START_FILE = Path("/tmp/traffic_probe_start")

MESH_PROFILE = Path("/mnt/shared/island_mode/mesh_profile.json")

SEED = int(os.environ.get("DEMO_SEED", str(int(time.time()))))
rng = random.Random(SEED)

AP_SSIDS = {
    "ap2": "zone2-responder",
    "ap3": "zone3-users",
    "ap4": "zone4-iot",
    "ap5": "zone5-other",
    "ap6": "zone6-second-island",
}


AP_FREQ = {
    "ap2": "2412",
    "ap3": "2437",
    "ap4": "2462",
    "ap5": "2412",
    "ap6": "2437",
}

AP_BSSID = {
    "ap2": "02:00:00:00:08:00",
    "ap3": "02:00:00:00:09:00",
    "ap4": "02:00:00:00:0a:00",
    "ap5": "02:00:00:00:0b:00",
    "ap6": "02:00:00:00:0c:00",
}

AP_PRIMARY_IFACES = {
    "ap2": ["s2-ap2", "ap2-s2"],
    "ap3": ["s3-ap3", "ap3-s3"],
    "ap4": ["s4-ap4", "ap4-s4"],
    "ap5": ["s5-ap5", "ap5-s5"],
    "ap6": ["s8-ap6", "ap6-s8"],
}


def sh(cmd: str) -> None:
    print(f"+ {cmd}")
    subprocess.run(cmd, shell=True, text=True)


def log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line)
    with EVENT_LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def phase(name: str) -> None:
    PHASE_FILE.write_text(name)
    log(f"PHASE={name}")


def node_cmd(node: str, cmd: str) -> str:
    n = net.get(node)
    full = f"{node}$ {cmd}"
    log(full)
    out = n.cmd(cmd)
    if out.strip():
        print(out.strip())
    return out


def move_station(node: str, ap: str) -> None:
    iface = f"{node}-wlan0"
    ssid = AP_SSIDS[ap]
    freq = AP_FREQ.get(ap, "")
    bssid = AP_BSSID.get(ap, "")

    log(f"MOVE {node} -> {ap} ({ssid})")
    node_cmd(node, f"iw dev {iface} disconnect 2>/dev/null || true")
    time.sleep(0.5)

    connect_cmd = f"iw dev {iface} connect {ssid}"
    if freq:
        connect_cmd += f" {freq}"
    if bssid:
        connect_cmd += f" {bssid}"
    connect_cmd += " 2>/dev/null || true"

    node_cmd(node, connect_cmd)
    time.sleep(0.8)


    link = node_cmd(node, f"iw dev {iface} link || true")
    if "Connected" not in link:
        log(f"RETRY associate {node} -> {ap}")
        node_cmd(node, f"iw dev {iface} disconnect 2>/dev/null || true")
        time.sleep(0.5)
        node_cmd(node, connect_cmd)
        time.sleep(1.0)
        node_cmd(node, f"iw dev {iface} link || true")


def random_mobility() -> None:
    node = rng.choice(["resp", "atk", "usr", "sens"])
    ap = rng.choice(["ap2", "ap3", "ap4", "ap5"])
    move_station(node, ap)


def randomize_mesh_costs() -> None:
    profile = json.loads(MESH_PROFILE.read_text())

    changed = []
    for link in profile.get("mesh_links", []):
        if not link["name"].startswith("ap"):
            continue

        old = link.get("cost", 100)
        new = rng.randint(15, 55)
        link["cost"] = new
        changed.append(f"{link['name']}:{old}->{new}")

    MESH_PROFILE.write_text(json.dumps(profile, indent=2) + "\n")
    log("MESH_COST_UPDATE " + ", ".join(changed))


def fail_ap_primary(ap: str) -> None:
    log(f"FAIL_PRIMARY_PATH {ap}")

    for iface in AP_PRIMARY_IFACES[ap]:
        sh(f"ip link set {iface} down 2>/dev/null || true")

def repair_ap(ap: str) -> None:
    log(f"REPAIR_REQUEST {ap}")
    sh(f"python3 /mnt/shared/island_mode/sdn_mesh_controller.py repair {ap}")


    sh("ovs-appctl fdb/flush ap2 2>/dev/null || true")
    sh("ovs-appctl fdb/flush ap3 2>/dev/null || true")
    sh("ovs-appctl fdb/flush ap4 2>/dev/null || true")
    sh("ovs-appctl fdb/flush ap5 2>/dev/null || true")
    sh("ovs-appctl fdb/flush ap6 2>/dev/null || true")
    sh("ovs-appctl fdb/flush s6 2>/dev/null || true")
    sh("ovs-appctl fdb/flush s7 2>/dev/null || true")
    sh("python3 /mnt/shared/island_mode/sdn_mesh_controller.py status")

def trust_aware_mesh_step() -> None:
    log("\nTRUST_AWARE_MESH_STEP start")

    sh("python3 /mnt/shared/island_mode/sdn_mesh_controller.py reset")
    sh("python3 /mnt/shared/island_mode/sdn_mesh_controller.py clear-quarantine")


    sh("python3 /mnt/shared/island_mode/sdn_mesh_controller.py set-cost ap4-ap5 10")
    sh("python3 /mnt/shared/island_mode/sdn_mesh_controller.py set-cost ap3-ap5 80")

    sh("python3 /mnt/shared/island_mode/sdn_mesh_controller.py quarantine-node ap4")
    sh("python3 /mnt/shared/island_mode/sdn_mesh_controller.py trust-status")

    fail_ap_primary("ap5")

    repair_ap("ap5")

    log("\nTRUST_AWARE_MESH_STEP end")

def start_traffic_probe(node: str, actor: str, service: str, url: str) -> None:
    log(f"START_PROBE node={node} actor={actor} service={service} url={url}")

    cmd = (
        f"python3 /mnt/shared/island_mode/traffic_probe.py "
        f"--actor {actor} "
        f"--service {service} "
        f"--url {url} "
        f"--out {METRICS} "
        f"--interval 1 "
        f"--timeout 2 "
        f"> /tmp/demo_probe_{actor}_{service}.log 2>&1 &"
    )

    node_cmd(node, cmd)

def start_second_island_probes() -> None:
    log("START_SECOND_ISLAND_PROBES")

    start_traffic_probe("resp2", "zt_responder_i2", "svc_critical", "http://10.0.0.30:8000")
    start_traffic_probe("resp2", "zt_responder_i2", "svc_alert", "http://10.0.0.31:8000")
    start_traffic_probe("resp2", "zt_responder_i2", "svc_noncritical", "http://10.0.0.40:8000")
    start_traffic_probe("resp2", "zt_responder_i2", "svc_central_identity", "http://10.0.0.10:8000")

    start_traffic_probe("usr2", "zt_civilian_user_i2", "svc_critical", "http://10.0.0.30:8000")
    start_traffic_probe("sens2", "zt_sensor_i2", "svc_alert", "http://10.0.0.31:8000")
    start_traffic_probe("atk2", "zt_attacker_i2", "svc_critical", "http://10.0.0.30:8000")


def prepare_metrics_file() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    with METRICS.open("w", encoding="utf-8") as f:
        f.write(
            "t_rel_s,phase,actor,service,url,result,http_code,latency_ms,error\n"
        )


def start_primary_island_probes() -> None:
    log("START_PRIMARY_ISLAND_PROBES")

    START_FILE.write_text(str(time.time()))
    STOP_FILE.unlink(missing_ok=True)
    prepare_metrics_file()

    start_traffic_probe("resp", "zt_responder", "svc_critical", "http://10.0.0.30:8000")
    start_traffic_probe("resp", "zt_responder", "svc_alert", "http://10.0.0.31:8000")
    start_traffic_probe("resp", "zt_responder", "svc_central_identity", "http://10.0.0.10:8000")
    start_traffic_probe("resp", "zt_responder", "svc_noncritical", "http://10.0.0.40:8000")
    start_traffic_probe("resp", "zt_responder", "svc_external", "http://10.0.0.70:8000")

    start_traffic_probe("usr", "zt_civilian_user", "svc_noncritical", "http://10.0.0.40:8000")
    start_traffic_probe("usr", "zt_civilian_user", "svc_external", "http://10.0.0.70:8000")
    start_traffic_probe("usr", "zt_civilian_user", "svc_central_identity", "http://10.0.0.10:8000")
    start_traffic_probe("usr", "zt_civilian_user", "svc_critical", "http://10.0.0.30:8000")

    start_traffic_probe("sens", "zt_sensor", "svc_alert", "http://10.0.0.31:8000")
    start_traffic_probe("sens", "zt_sensor", "svc_central_identity", "http://10.0.0.10:8000")
    start_traffic_probe("sens", "zt_sensor", "svc_external", "http://10.0.0.70:8000")

    start_traffic_probe("atk", "zt_attacker", "svc_critical", "http://10.0.0.30:8000")
    start_traffic_probe("atk", "zt_attacker", "svc_alert", "http://10.0.0.31:8000")
    start_traffic_probe("atk", "zt_attacker", "svc_external", "http://10.0.0.70:8000")

def stop_all_probes() -> None:
    STOP_FILE.write_text("stop\n")
    time.sleep(2)


def random_activity(seconds: int, allow_mesh: bool = False) -> None:
    end = time.time() + seconds

    while time.time() < end:
        action = rng.choice(["move", "cost", "wait", "move"])

        if action == "move":
            random_mobility()

        elif action == "cost":
            randomize_mesh_costs()

        else:
            log("WAIT")

        time.sleep(rng.randint(3, 6))


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    profile_backup = MESH_PROFILE.read_text()

    sh("rm -f /tmp/island_audit.log /tmp/island_topology_events.log")
    sh(f"rm -f {METRICS}")
    sh(f"rm -f {EVENT_LOG}")
    sh("rm -f /tmp/traffic_probe.stop /tmp/traffic_probe_start")

    log("=== RANDOM DEMO RUN START ===")
    log(f"DEMO_SEED={SEED}")



    log("\nReset network and policy state")
    sh("python3 /mnt/shared/island_mode/sdn_mesh_controller.py reset")
    sh("python3 /mnt/shared/island_mode/sdn_mesh_controller.py clear-quarantine")
    sh("python3 /mnt/shared/island_mode/edge_mode_controller.py normal")
    sh("/mnt/shared/island_mode/restore_core_link.sh")

    log("\nStart watch agent")
    sh("/mnt/shared/island_mode/stop_watch.sh")
    sh("/mnt/shared/island_mode/start_watch.sh")

    phase("NORMAL")

    log("\nUrban baseline: normal city traffic before disruption")
    move_station("resp", rng.choice(["ap2", "ap3"]))
    move_station("usr", rng.choice(["ap3", "ap4"]))
    move_station("sens", rng.choice(["ap4", "ap5"]))
    move_station("atk", rng.choice(["ap4", "ap5"]))

    log("\nSecond-island nodes remain attached to ap6")
    node_cmd("resp2", "iw dev resp2-wlan0 link || true")
    node_cmd("usr2", "iw dev usr2-wlan0 link || true")
    node_cmd("sens2", "iw dev sens2-wlan0 link || true")
    node_cmd("atk2", "iw dev atk2-wlan0 link || true")


    start_primary_island_probes()

    random_activity(25)

    phase("DEGRADED")
    log("\nApply degraded core conditions")
    sh("/mnt/shared/island_mode/degrade_core.sh")
    random_activity(18)

    phase("ISLANDED")
    log("\nForce full core outage")
    sh("ip link set s6-eth1 down 2>/dev/null || true")
    time.sleep(8)

    random_activity(10)

    phase("ISLANDED_MESH")
    randomize_mesh_costs()

    failed_ap = rng.choice(["ap4", "ap5"])
    fail_ap_primary(failed_ap)

    if failed_ap == "ap5" and rng.choice([True, False]):
        fail_ap_primary("ap4")

    repair_ap(failed_ap)
    random_activity(12)

    phase("TRUST_AWARE_MESH")
    log("\nTrust-aware mesh routing: quarantine cheaper relay and force alternate path")
    trust_aware_mesh_step()
    random_activity(8)

    phase("INTER_ISLAND_MESH")
    log("\nEnable inter-island fallback and start second-island actors")
    sh("python3 /mnt/shared/island_mode/sdn_mesh_controller.py inter-island")
    sh("python3 /mnt/shared/island_mode/sdn_mesh_controller.py status")

    start_second_island_probes()

    sh("ovs-appctl fdb/flush s6 2>/dev/null || true")
    sh("ovs-appctl fdb/flush s7 2>/dev/null || true")
    sh("ovs-appctl fdb/flush s8 2>/dev/null || true")
    sh("ovs-appctl fdb/flush ap6 2>/dev/null || true")

    random_activity(10)

    phase("REATTACH")
    log("\nRestore core/backhaul")
    sh("/mnt/shared/island_mode/stop_watch.sh")
    sh("/mnt/shared/island_mode/restore_core_link.sh")
    sh("python3 /mnt/shared/island_mode/sdn_mesh_controller.py clear-quarantine")
    sh("python3 /mnt/shared/island_mode/sdn_mesh_controller.py reset")
    sh("python3 /mnt/shared/island_mode/edge_mode_controller.py normal")
    time.sleep(10)

    phase("NORMAL_RESTORED")
    sh("python3 /mnt/shared/island_mode/edge_mode_controller.py normal")
    random_activity(10)


    log("\nStopping probes and watch")
    stop_all_probes()
    sh("/mnt/shared/island_mode/stop_watch.sh")

    log("\nRestore mesh profile")
    MESH_PROFILE.write_text(profile_backup)

    log("\nRestore clean network")
    sh("/mnt/shared/island_mode/restore_core_link.sh")
    sh("python3 /mnt/shared/island_mode/sdn_mesh_controller.py clear-quarantine")
    sh("python3 /mnt/shared/island_mode/sdn_mesh_controller.py reset")
    sh("python3 /mnt/shared/island_mode/edge_mode_controller.py normal")

    log("=== RANDOM DEMO RUN END ===")


main()
