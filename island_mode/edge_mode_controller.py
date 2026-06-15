#!/usr/bin/env python3

import json
import subprocess
import sys
import os
from datetime import datetime
from pathlib import Path
import time
import urllib.request
import re

CONFIG_DIR = Path("/mnt/shared/island_mode")
RUNTIME_DIR = Path(os.environ.get("ISLAND_RUNTIME_DIR", str(CONFIG_DIR / "runtime")))

IDENTITY_CACHE_PATH = CONFIG_DIR / "identity_cache.json"
SERVICE_REGISTRY_PATH = CONFIG_DIR / "service_registry.json"
POLICY_MODEL_PATH = CONFIG_DIR / "policy_model.json"
PDP_URL = os.environ.get("PDP_URL", "http://10.0.0.50:8088")
POLICY_CACHE_PATH = RUNTIME_DIR / "compiled_policy_cache.json"
AUDIT_PATH = Path("/tmp/island_audit.log")
AUDIT_URL = os.environ.get("AUDIT_URL", "http://10.0.0.60:8090/audit")


BRIDGES = [
    "s1", "s6", "s7",
    "s2", "s3", "s4", "s5", "s8",
    "ap2", "ap3", "ap4", "ap5", "ap6",
]


EDGE_PEP_BRIDGES = ["s6", "s7"]

CONTROL_PLANE_SRC_IP = os.environ.get("CONTROL_PLANE_SRC_IP", "10.0.0.254")
CONTROL_PLANE_SERVICE_IPS = ["10.0.0.50", "10.0.0.60"]

POLICY_CACHE_MAX_AGE_SECONDS = int(os.environ.get("POLICY_CACHE_MAX_AGE_SECONDS", "3600"))

CORE_IFACE = "s6-eth1"
CHECK_INTERVAL = 2
DOWN_THRESHOLD = 2
UP_THRESHOLD = 2
DEGRADED_THRESHOLD = 2

DEGRADED_DELAY_MS = 100.0
DEGRADED_LOSS_PCT = 1.0
DEGRADED_RATE_MBIT = 10.0

LIMIT_METER_BASE_ID = int(os.environ.get("LIMIT_METER_BASE_ID", "1000"))
LIMIT_RATE_KBPS = int(os.environ.get("LIMIT_RATE_KBPS", "2000"))
LIMIT_BURST_KB = int(os.environ.get("LIMIT_BURST_KB", "200"))


def run(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    print(f"+ {cmd}")
    return subprocess.run(cmd, shell=True, text=True, check=check)

def install_control_plane_exceptions(bridge: str) -> None:
    for dst_ip in CONTROL_PLANE_SERVICE_IPS:
        run(
            f'ovs-ofctl add-flow {bridge} '
            f'"priority=510,ip,nw_src={CONTROL_PLANE_SRC_IP},nw_dst={dst_ip},actions=NORMAL"'
        )



def bridge_exists(bridge: str) -> bool:
    result = subprocess.run(
        ["ovs-vsctl", "br-exists", bridge],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def existing_bridges(bridges: list[str]) -> list[str]:
    return [bridge for bridge in bridges if bridge_exists(bridge)]


def audit(message: str) -> None:
    timestamp = datetime.now().isoformat(timespec="seconds")
    line = f"{timestamp},{message}\n"

    with AUDIT_PATH.open("a", encoding="utf-8") as f:
        f.write(line)

    event = {
        "ts": timestamp,
        "source": "edge_mode_controller",
        "event": message,
    }

    try:
        payload = json.dumps(event).encode("utf-8")
        request = urllib.request.Request(
            AUDIT_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(request, timeout=0.3).read()
    except Exception:
        pass


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_model() -> tuple[dict, dict, dict]:
    identities = load_json(IDENTITY_CACHE_PATH)
    services = load_json(SERVICE_REGISTRY_PATH)
    policies = load_json(POLICY_MODEL_PATH)
    return identities, services, policies


def load_policy_cache() -> dict:
    if not POLICY_CACHE_PATH.exists():
        return {}

    with POLICY_CACHE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_policy_cache(mode: str, rules: list[dict]) -> None:
    cache = load_policy_cache()
    mode = mode.upper()

    cache[mode] = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "rules": rules
    }

    POLICY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with POLICY_CACHE_PATH.open("w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)
        f.write("\n")


def is_policy_cache_entry_valid(entry: dict) -> bool:
    updated_at = entry.get("updated_at")

    if not updated_at:
        return False

    try:
        cache_time = datetime.fromisoformat(updated_at)
    except ValueError:
        return False

    age_seconds = (datetime.now() - cache_time).total_seconds()
    return age_seconds <= POLICY_CACHE_MAX_AGE_SECONDS


def load_cached_rules(mode: str) -> list[dict]:
    cache = load_policy_cache()
    mode = mode.upper()

    entry = cache.get(mode)
    if not entry:
        return []

    if not is_policy_cache_entry_valid(entry):
        print(f"[fallback] cached policy for {mode} expired; refusing to use it")
        audit(f"{mode},FALLBACK,cached-policy-expired")
        return []

    return entry.get("rules", [])


def fail_closed_rules(mode: str) -> list[dict]:
    services = load_json(SERVICE_REGISTRY_PATH)
    mode = mode.upper()

    rules = []

    for service_name, service_data in services.items():
        service_class = service_data.get("class")
        dst_ip = service_data.get("ip")

        if service_class in ["critical", "non-critical", "external"]:
            rules.append({
                "mode": mode,
                "actor": "*",
                "role": "*",
                "src_ip": None,
                "src_mac": None,
                "service": service_name,
                "service_class": service_class,
                "dst_ip": dst_ip,
                "action": "deny",
                "priority": 480,
                "reason": "fail-closed fallback: no PDP and no cached policy"
            })

    return rules


def request_pdp_compile(mode: str) -> list[dict]:
    mode = mode.upper()

    payload = json.dumps({"mode": mode}).encode("utf-8")

    request = urllib.request.Request(
        f"{PDP_URL}/compile",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            data = json.loads(response.read().decode("utf-8"))

        rules = data["rules"]
        save_policy_cache(mode, rules)

        print(f"[pdp] compiled policy received and cached for {mode}")
        audit(f"{mode},PDP,compiled-policy-cached")

        return rules

    except Exception as exc:
        print(f"[fallback] local PDP unavailable: {exc}")

        cached_rules = load_cached_rules(mode)
        if cached_rules:
            print(f"[fallback] using cached compiled policy for {mode}")
            audit(f"{mode},FALLBACK,using-cached-compiled-policy")
            return cached_rules

        print(f"[fallback] no cached policy for {mode}; applying fail-closed rules")
        audit(f"{mode},FALLBACK,no-cache-fail-closed")
        return fail_closed_rules(mode)


def install_normal_mode() -> None:
    print("[normal] restoring default L2 forwarding")

    for bridge in BRIDGES:
        if not bridge_exists(bridge):
            print(f"[normal] skipping missing bridge {bridge}")
            continue

        run(f"ovs-ofctl del-flows {bridge}")
        run(f'ovs-ofctl add-flow {bridge} "priority=100,actions=NORMAL"')

    audit("NORMAL,default-l2-forwarding-restored")
    print("[normal] done")


def ovs_action(action: str, meter_id: int | None = None) -> str:
    if action == "allow":
        return "NORMAL"

    if action == "deny":
        return "drop"

    if action == "limit":
        if meter_id is None:
            return "drop"
        return f"meter:{meter_id},NORMAL"

    raise ValueError(f"Unsupported action from PDP: {action}")


def limited_rule_key(rule: dict) -> tuple:
    return (
        rule.get("actor"),
        rule.get("role"),
        rule.get("src_ip"),
        rule.get("src_mac"),
        rule.get("service"),
        rule.get("dst_ip"),
    )


def build_flow(pep_bridge: str, rule: dict, limit_meters: dict[tuple, int] | None = None) -> str:
    priority = rule["priority"]
    dst_ip = rule["dst_ip"]
    src_ip = rule.get("src_ip")
    src_mac = rule.get("src_mac")
    action = rule["action"]

    limit_meters = limit_meters or {}
    of_prefix = ""

    if action == "limit":
        meter_id = limit_meters.get(limited_rule_key(rule))
        ovs_act = ovs_action("limit", meter_id=meter_id)
        if meter_id is not None:
            of_prefix = "-O OpenFlow13 "
    else:
        ovs_act = ovs_action(action)

    if src_ip is None:
        return (
            f'ovs-ofctl {of_prefix}add-flow {pep_bridge} '
            f'"priority={priority},ip,nw_dst={dst_ip},actions={ovs_act}"'
        )

    if src_mac:
        return (
            f'ovs-ofctl {of_prefix}add-flow {pep_bridge} '
            f'"priority={priority},dl_src={src_mac},ip,nw_src={src_ip},nw_dst={dst_ip},actions={ovs_act}"'
        )

    return (
        f'ovs-ofctl {of_prefix}add-flow {pep_bridge} '
        f'"priority={priority},ip,nw_src={src_ip},nw_dst={dst_ip},actions={ovs_act}"'
    )


def setup_limit_meters(bridge: str, rules: list[dict]) -> dict[tuple, int]:
    limited_rules = [r for r in rules if r.get("action") == "limit"]
    if not limited_rules:
        return {}

    run(f"ovs-vsctl set bridge {bridge} protocols=OpenFlow10,OpenFlow13", check=False)

    meter_map: dict[tuple, int] = {}
    for index, rule in enumerate(limited_rules, start=1):
        meter_id = LIMIT_METER_BASE_ID + index
        key = limited_rule_key(rule)

        run(
            f"ovs-ofctl -O OpenFlow13 del-meter {bridge} meter={meter_id}",
            check=False,
        )
        result = run(
            f"ovs-ofctl -O OpenFlow13 add-meter {bridge} "
            f"\"meter={meter_id},kbps,band=type=drop,rate={LIMIT_RATE_KBPS}\"",
            check=False,
        )

        if result.returncode == 0:
            meter_map[key] = meter_id
            audit(
                f"LIMIT,meter-ready,bridge={bridge},meter={meter_id},"
                f"actor={rule.get('actor')},service={rule.get('service')},"
                f"rate_kbps={LIMIT_RATE_KBPS}"
            )
        else:
            print(
                f"[limit] meter setup failed on {bridge} for "
                f"actor={rule.get('actor')} service={rule.get('service')}; "
                "limited flow will fail closed to drop"
            )
            audit(
                f"LIMIT,meter-failed,bridge={bridge},meter={meter_id},"
                f"actor={rule.get('actor')},service={rule.get('service')},"
                "fallback=drop"
            )

    return meter_map


def install_policy_mode(mode: str) -> None:
    mode = mode.upper()

    print(f"[{mode.lower()}] requesting compiled policy from local PDP")
    compiled_rules = request_pdp_compile(mode)

    peps = existing_bridges(EDGE_PEP_BRIDGES)
    if not peps:
        print(f"[{mode.lower()}] no existing PEP bridge found from {EDGE_PEP_BRIDGES}")
        audit(f"{mode},ERROR,no-existing-pep-bridge")
        return

    print(f"[{mode.lower()}] installing PDP-driven enforcement on {', '.join(peps)}")

    total_installed = 0

    for pep in peps:
        run(f"ovs-ofctl del-flows {pep}")
        run(f'ovs-ofctl add-flow {pep} "priority=100,actions=NORMAL"')
        install_control_plane_exceptions(pep)

        limit_meters = setup_limit_meters(pep, compiled_rules)

        installed_on_pep = 0

        for rule in compiled_rules:
            flow = build_flow(pep, rule, limit_meters=limit_meters)
            run(flow)
            installed_on_pep += 1
            total_installed += 1

        print(f"[{mode.lower()}] installed {installed_on_pep} PDP rules on {pep}")

    for rule in compiled_rules:
        audit(
            f"{mode},{rule['action'].upper()},actor={rule.get('actor')},"
            f"role={rule.get('role')},service={rule.get('service')},"
            f"service_class={rule.get('service_class')},reason={rule.get('reason')}"
        )

    print(f"[{mode.lower()}] installed {total_installed} total PDP rules into OVS")
    print(f"[{mode.lower()}] done")


def install_degraded_mode() -> None:
    install_policy_mode("DEGRADED")


def install_island_mode() -> None:
    install_policy_mode("ISLANDED")


def show_status() -> None:
    peps = existing_bridges(EDGE_PEP_BRIDGES)

    if not peps:
        print("[status] no PEP bridges exist")
    else:
        for pep in peps:
            print(f"[status] flows on {pep}")
            run(f"ovs-ofctl dump-flows {pep}", check=False)
            print()

    print("[status] known bridges")
    for bridge in BRIDGES:
        print(f"  {bridge}: {'present' if bridge_exists(bridge) else 'missing'}")

    print("\n[status] audit log")
    if AUDIT_PATH.exists():
        print(AUDIT_PATH.read_text())
    else:
        print("No audit log yet.")


def is_core_link_up() -> bool:
    result = subprocess.run(
        f"ip link show {CORE_IFACE}",
        shell=True,
        text=True,
        capture_output=True
    )

    if result.returncode != 0:
        print(f"[watch] could not read interface {CORE_IFACE}")
        return False

    output = result.stdout
    return "LOWER_UP" in output and "state UP" in output


def _delay_to_ms(value: float, unit: str) -> float:
    if unit == "us":
        return value / 1000.0
    if unit == "ms":
        return value
    if unit == "s":
        return value * 1000.0
    return value


def _rate_to_mbit(value: float, unit: str) -> float:
    if unit == "bit":
        return value / 1_000_000.0
    if unit == "kbit":
        return value / 1000.0
    if unit == "mbit":
        return value
    if unit == "gbit":
        return value * 1000.0
    return value


def is_core_link_degraded() -> bool:
    result = subprocess.run(
        f"tc qdisc show dev {CORE_IFACE}",
        shell=True,
        text=True,
        capture_output=True
    )

    if result.returncode != 0:
        print(f"[watch] could not read qdisc for {CORE_IFACE}")
        return False

    output = result.stdout.lower()

    delay_match = re.search(r"delay\s+([0-9.]+)(us|ms|s)", output)
    if delay_match:
        delay_value = float(delay_match.group(1))
        delay_unit = delay_match.group(2)
        delay_ms = _delay_to_ms(delay_value, delay_unit)

        if delay_ms >= DEGRADED_DELAY_MS:
            return True

    loss_match = re.search(r"loss\s+(?:random\s+)?([0-9.]+)%", output)
    if loss_match:
        loss_pct = float(loss_match.group(1))

        if loss_pct >= DEGRADED_LOSS_PCT:
            return True

    rate_match = re.search(r"rate\s+([0-9.]+)(bit|kbit|mbit|gbit)", output)
    if rate_match:
        rate_value = float(rate_match.group(1))
        rate_unit = rate_match.group(2)
        rate_mbit = _rate_to_mbit(rate_value, rate_unit)

        if rate_mbit <= DEGRADED_RATE_MBIT:
            return True

    return False


def watch() -> None:
    print("[watch] starting local resilience agent")
    print(f"[watch] monitoring core link interface: {CORE_IFACE}")

    current_mode = "NORMAL"

    down_count = 0
    degraded_count = 0
    healthy_count = 0

    audit("WATCH,started,mode=NORMAL")

    try:
        while True:
            core_up = is_core_link_up()
            core_degraded = is_core_link_degraded() if core_up else False

            if not core_up:
                down_count += 1
                degraded_count = 0
                healthy_count = 0

                print(
                    f"[watch] core link DOWN "
                    f"({down_count}/{DOWN_THRESHOLD}) mode={current_mode}"
                )

                if current_mode != "ISLANDED" and down_count >= DOWN_THRESHOLD:
                    print("[watch] core link lost, entering ISLANDED")
                    install_island_mode()
                    current_mode = "ISLANDED"
                    audit("ISLANDED,entered-by-watch")

            elif core_degraded:
                degraded_count += 1
                down_count = 0
                healthy_count = 0

                print(
                    f"[watch] core link DEGRADED "
                    f"({degraded_count}/{DEGRADED_THRESHOLD}) mode={current_mode}"
                )

                if current_mode != "DEGRADED" and degraded_count >= DEGRADED_THRESHOLD:
                    if current_mode == "ISLANDED":
                        print("[watch] core link restored but degraded, entering REATTACH")
                        audit("REATTACH,core-link-restored-but-degraded")

                    print("[watch] degradation detected, entering DEGRADED")
                    install_degraded_mode()
                    current_mode = "DEGRADED"
                    audit("DEGRADED,entered-by-watch")

            else:
                healthy_count += 1
                down_count = 0
                degraded_count = 0

                print(
                    f"[watch] core link HEALTHY "
                    f"({healthy_count}/{UP_THRESHOLD}) mode={current_mode}"
                )

                if current_mode != "NORMAL" and healthy_count >= UP_THRESHOLD:
                    print("[watch] core link healthy, entering REATTACH")
                    audit("REATTACH,core-link-healthy")
                    install_normal_mode()
                    current_mode = "NORMAL"
                    audit("NORMAL,restored-by-watch")

            time.sleep(CHECK_INTERVAL)

    except KeyboardInterrupt:
        print("\n[watch] stopped")
        audit("WATCH,stopped")



def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(1)

    command = sys.argv[1]

    if command == "normal":
        install_normal_mode()
    elif command == "island":
        install_island_mode()
    elif command == "status":
        show_status()
    elif command == "watch":
        watch()
    elif command == "degraded":
        install_degraded_mode()
    else:
        usage()
        sys.exit(1)


if __name__ == "__main__":
    main()
