#!/usr/bin/env python3

import heapq
import json
import subprocess
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Any

CONFIG_DIR = Path("/mnt/shared/island_mode")
RUNTIME_DIR = Path(os.environ.get("ISLAND_RUNTIME_DIR", str(CONFIG_DIR / "runtime")))

PROFILE_TEMPLATE_PATH = CONFIG_DIR / "mesh_profile.json"
PROFILE_PATH = Path(os.environ.get("ISLAND_MESH_PROFILE", str(RUNTIME_DIR / "mesh_profile.json")))

EVENT_LOG = Path(os.environ.get("ISLAND_TOPOLOGY_EVENTS_LOG", "/tmp/island_topology_events.log"))
AUDIT_LOG = Path(os.environ.get("ISLAND_AUDIT_LOG", "/tmp/island_audit.log"))

HISTORY_PATH = RUNTIME_DIR / "path_history.json"
KNOWLEDGE_PATH = RUNTIME_DIR / "outage_knowledge.json"
TRUST_STATE_PATH = RUNTIME_DIR / "mesh_trust_state.json"
SHADOW_PLAN_PATH = RUNTIME_DIR / "shadow_repair_plan.json"

DEFAULT_PROFILE: dict[str, Any] = {
    "ap_nodes": ["ap2", "ap3", "ap4", "ap5", "ap6"],
    "primary_links": [
        {"name": "s6-s2", "ifaces": ["s6-s2", "s2-s6"]},
        {"name": "s6-s3", "ifaces": ["s6-s3", "s3-s6"]},
        {"name": "s6-s4", "ifaces": ["s6-s4", "s4-s6"]},
        {"name": "s6-s5", "ifaces": ["s6-s5", "s5-s6"]},

        {"name": "s2-ap2", "ifaces": ["s2-ap2", "ap2-s2"]},
        {"name": "s3-ap3", "ifaces": ["s3-ap3", "ap3-s3"]},
        {"name": "s4-ap4", "ifaces": ["s4-ap4", "ap4-s4"]},
        {"name": "s5-ap5", "ifaces": ["s5-ap5", "ap5-s5"]},

        {"name": "s1-s7", "ifaces": ["s1-s7", "s7-s1"]},
        {"name": "s7-s8", "ifaces": ["s7-s8", "s8-s7"]},
        {"name": "s8-ap6", "ifaces": ["s8-ap6", "ap6-s8"]},
    ],
    "fallback_links": [
        {"name": "ap2-ap3", "ifaces": ["ap2-ap3", "ap3-ap2"]},
        {"name": "ap3-ap4", "ifaces": ["ap3-ap4", "ap4-ap3"]},
        {"name": "ap4-ap5", "ifaces": ["ap4-ap5", "ap5-ap4"]},
        {"name": "ap3-ap5", "ifaces": ["ap3-ap5", "ap5-ap3"]},
        {"name": "s6-s7", "ifaces": ["s6-s7", "s7-s6"]},
    ],
    "primary_paths": {
        "ap2": {"ifaces": ["s6-s2", "s2-s6", "s2-ap2", "ap2-s2"]},
        "ap3": {"ifaces": ["s6-s3", "s3-s6", "s3-ap3", "ap3-s3"]},
        "ap4": {"ifaces": ["s6-s4", "s4-s6", "s4-ap4", "ap4-s4"]},
        "ap5": {"ifaces": ["s6-s5", "s5-s6", "s5-ap5", "ap5-s5"]},
        # ap6 is in the second island. Its primary local path is to s7/s1.
        "ap6": {"ifaces": ["s1-s7", "s7-s1", "s7-s8", "s8-s7", "s8-ap6", "ap6-s8"]},
    },
    "mesh_links": [
        {
            "name": "ap2-ap3",
            "nodes": ["ap2", "ap3"],
            "ifaces": ["ap2-ap3", "ap3-ap2"],
            "available": True,
            "cost": 40,
        },
        {
            "name": "ap3-ap4",
            "nodes": ["ap3", "ap4"],
            "ifaces": ["ap3-ap4", "ap4-ap3"],
            "available": True,
            "cost": 18,
        },
        {
            "name": "ap4-ap5",
            "nodes": ["ap4", "ap5"],
            "ifaces": ["ap4-ap5", "ap5-ap4"],
            "available": True,
            "cost": 25,
        },
        {
            "name": "ap3-ap5",
            "nodes": ["ap3", "ap5"],
            "ifaces": ["ap3-ap5", "ap5-ap3"],
            "available": True,
            "cost": 35,
        },
    ],
}


def sh(cmd: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, text=True, capture_output=True, check=check)


def run(cmd: str) -> None:
    print(f"+ {cmd}")
    subprocess.run(cmd, shell=True, check=False)


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def append(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def audit(event: str) -> None:
    timestamp = now()

    append(EVENT_LOG, f"{timestamp},{event}")
    append(AUDIT_LOG, f"{timestamp},MESH,{event}")


def merge_profile(default: dict[str, Any], loaded: dict[str, Any]) -> dict[str, Any]:
    profile = dict(default)
    profile.update(loaded)

    if "primary_links" not in profile:
        profile["primary_links"] = default["primary_links"]
    if "fallback_links" not in profile:
        profile["fallback_links"] = default["fallback_links"]

    return profile


def load_profile() -> dict[str, Any]:
    if PROFILE_PATH.exists():
        with PROFILE_PATH.open("r", encoding="utf-8") as f:
            loaded = json.load(f)
        return merge_profile(DEFAULT_PROFILE, loaded)

    if PROFILE_TEMPLATE_PATH.exists():
        with PROFILE_TEMPLATE_PATH.open("r", encoding="utf-8") as f:
            loaded = json.load(f)
        return merge_profile(DEFAULT_PROFILE, loaded)

    return DEFAULT_PROFILE

def save_profile(profile: dict[str, Any]) -> None:
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with PROFILE_PATH.open("w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)
        f.write("\n")


def load_knowledge() -> dict[str, Any]:
    if not KNOWLEDGE_PATH.exists():
        return {}

    try:
        with KNOWLEDGE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def default_trust_state() -> dict[str, Any]:
    return {
        "quarantined_nodes": [],
        "quarantined_links": [],
    }


def load_trust_state() -> dict[str, Any]:
    if not TRUST_STATE_PATH.exists():
        return default_trust_state()

    try:
        with TRUST_STATE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return default_trust_state()

    state = default_trust_state()
    state.update(data)
    return state


def save_trust_state(state: dict[str, Any]) -> None:
    TRUST_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

    clean_state = {
        "quarantined_nodes": sorted(set(state.get("quarantined_nodes", []))),
        "quarantined_links": sorted(set(state.get("quarantined_links", []))),
    }

    with TRUST_STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(clean_state, f, indent=2)
        f.write("\n")


def quarantine_from_profile(profile: dict[str, Any], key: str) -> set[str]:
    values: set[str] = set()
    quarantine = profile.get("quarantine", {})
    if isinstance(quarantine, dict):
        values.update(quarantine.get(key, []))

    if key == "nodes":
        values.update(profile.get("quarantined_nodes", []))
    elif key == "links":
        values.update(profile.get("quarantined_links", []))

    return values


def quarantined_nodes(profile: dict[str, Any], trust_state: dict[str, Any]) -> set[str]:
    nodes = set(trust_state.get("quarantined_nodes", []))
    nodes.update(quarantine_from_profile(profile, "nodes"))
    return nodes


def quarantined_links(profile: dict[str, Any], trust_state: dict[str, Any]) -> set[str]:
    links = set(trust_state.get("quarantined_links", []))
    links.update(quarantine_from_profile(profile, "links"))
    return links


def canonical_mesh_link_name(profile: dict[str, Any], link_name: str) -> str | None:
    names = {link["name"] for link in profile.get("mesh_links", [])}

    if link_name in names:
        return link_name

    if "-" in link_name:
        a, b = link_name.split("-", 1)
        reverse = f"{b}-{a}"
        if reverse in names:
            return reverse

    return None


def link_trust_status(
    profile: dict[str, Any],
    link: dict[str, Any],
    trust_state: dict[str, Any],
) -> tuple[bool, str]:
    q_nodes = quarantined_nodes(profile, trust_state)
    q_links = quarantined_links(profile, trust_state)

    if link["name"] in q_links:
        return False, "excluded:link-quarantined"

    for node in link.get("nodes", []):
        if node in q_nodes:
            return False, f"excluded:node-quarantined:{node}"

    if link.get("quarantine") is True or link.get("quarantined") is True:
        return False, "excluded:link-profile-quarantine"

    return True, "trusted"



def learned_link_cost(link: dict[str, Any]) -> int:
    base_cost = int(link.get("cost", 100))
    knowledge = load_knowledge()

    link_name = link.get("name")
    link_info = knowledge.get("links", {}).get(link_name, {})

    score = float(link_info.get("score", 0.0))


    discount = int(base_cost * 0.30 * score)

    return max(1, base_cost - discount)


def iface_exists(iface: str) -> bool:
    return sh(f"ip link show dev {iface}").returncode == 0


def iface_is_up(iface: str) -> bool:
    result = sh(f"ip -o link show dev {iface}")
    if result.returncode != 0:
        return False

    out = result.stdout
    return "UP" in out and "state DOWN" not in out


def set_iface(iface: str, state: str) -> None:
    if not iface_exists(iface):
        print(f"[mesh] skip missing iface {iface}")
        return

    run(f"ip link set {iface} {state}")


def iface_state_label(iface: str) -> str:
    if not iface_exists(iface):
        return "MISSING"
    return "UP" if iface_is_up(iface) else "DOWN"


def link_is_up(link: dict[str, Any]) -> bool:
    return all(iface_is_up(iface) for iface in link["ifaces"])


def all_mesh_ifaces(profile: dict[str, Any]) -> list[str]:
    ifaces: list[str] = []
    for link in profile.get("mesh_links", []):
        ifaces.extend(link["ifaces"])
    return ifaces


def primary_path_up(profile: dict[str, Any], ap: str) -> bool:
    path = profile["primary_paths"].get(ap)
    if not path:
        return False

    return all(iface_is_up(iface) for iface in path["ifaces"])


def healthy_gateways(profile: dict[str, Any]) -> set[str]:
    trust_state = load_trust_state()
    q_nodes = quarantined_nodes(profile, trust_state)

    return {
        ap
        for ap in profile["ap_nodes"]
        if ap not in q_nodes and primary_path_up(profile, ap)
    }

def build_graph(profile: dict[str, Any]) -> dict[str, list[tuple[str, int, dict[str, Any]]]]:
    trust_state = load_trust_state()
    q_nodes = quarantined_nodes(profile, trust_state)

    graph: dict[str, list[tuple[str, int, dict[str, Any]]]] = {
        ap: [] for ap in profile["ap_nodes"] if ap not in q_nodes
    }

    for link in profile.get("mesh_links", []):
        if not link.get("available", False):
            continue

        trusted, _reason = link_trust_status(profile, link, trust_state)
        if not trusted:
            continue

        a, b = link["nodes"]

        if a in q_nodes or b in q_nodes:
            continue

        cost = learned_link_cost(link)
        graph.setdefault(a, []).append((b, cost, link))
        graph.setdefault(b, []).append((a, cost, link))

    return graph

def shortest_path_to_gateway(profile: dict[str, Any], source: str, gateways: set[str]):
    graph = build_graph(profile)

    if source not in graph:
        return None

    counter = 0
    queue: list[tuple[int, int, str, list[str], list[dict[str, Any]]]] = [
        (0, counter, source, [source], [])
    ]
    seen: dict[str, int] = {}

    while queue:
        cost, _, node, nodes, links = heapq.heappop(queue)

        if node in seen and seen[node] <= cost:
            continue
        seen[node] = cost

        if node in gateways and node != source:
            return {
                "source": source,
                "gateway_ap": node,
                "cost": cost,
                "nodes": nodes,
                "links": links,
            }

        for neighbour, edge_cost, link in graph.get(node, []):
            counter += 1
            heapq.heappush(queue, (
                cost + edge_cost,
                counter,
                neighbour,
                nodes + [neighbour],
                links + [link],
            ))

    return None

def enumerate_paths_to_gateways(profile: dict[str, Any],source: str,gateways: set[str],max_hops: int = 4) -> list[dict[str, Any]]:

    graph = build_graph(profile)

    if source not in graph:
        return []

    candidates: list[dict[str, Any]] = []

    def dfs(
        node: str,
        cost: int,
        nodes: list[str],
        links: list[dict[str, Any]],
    ) -> None:
        if len(nodes) > max_hops + 1:
            return

        if node in gateways and node != source:
            candidates.append({
                "source": source,
                "gateway_ap": node,
                "cost": cost,
                "nodes": list(nodes),
                "links": list(links),
            })
            return

        for neighbour, edge_cost, link in graph.get(node, []):
            if neighbour in nodes:
                continue

            dfs(
                neighbour,
                cost + edge_cost,
                nodes + [neighbour],
                links + [link],
            )

    dfs(source, 0, [source], [])

    candidates.sort(key=lambda p: (p["cost"], len(p["nodes"]), "->".join(p["nodes"])))
    return candidates


def serialise_path(path: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": path.get("source"),
        "gateway_ap": path.get("gateway_ap"),
        "cost": path.get("cost"),
        "nodes": path.get("nodes", []),
        "path": "->".join(path.get("nodes", [])),
        "links": [link.get("name") for link in path.get("links", [])],
    }


def write_shadow_plan(
    profile: dict[str, Any],
    source: str,
    candidates: list[dict[str, Any]],
) -> None:
    trust_state = load_trust_state()
    gateways = sorted(healthy_gateways(profile))

    selected = serialise_path(candidates[0]) if candidates else None

    data = {
        "generated_at": now(),
        "model": "twin-lite shadow mesh planner",
        "source": source,
        "healthy_gateways": gateways,
        "quarantined_nodes": sorted(quarantined_nodes(profile, trust_state)),
        "quarantined_links": sorted(quarantined_links(profile, trust_state)),
        "candidate_count": len(candidates),
        "selected": selected,
        "candidates": [serialise_path(path) for path in candidates],
        "note": "Candidate paths are evaluated without changing live interfaces. The executor applies only the selected path during repair.",
    }

    SHADOW_PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SHADOW_PLAN_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def plan_one(profile: dict[str, Any], ap: str) -> list[dict[str, Any]]:
    if ap not in profile["ap_nodes"]:
        print(f"[mesh] unknown AP: {ap}")
        audit(f"PLAN,source={ap},reason=unknown-ap,candidate_count=0")
        write_shadow_plan(profile, ap, [])
        return []

    trust_state = load_trust_state()

    if ap in quarantined_nodes(profile, trust_state):
        print(f"[mesh] {ap} is quarantined; no shadow repair plan")
        audit(f"PLAN,source={ap},reason=source-quarantined,candidate_count=0")
        write_shadow_plan(profile, ap, [])
        return []

    gateways = healthy_gateways(profile)

    if not gateways:
        print("[mesh] no healthy AP gateway path for shadow planning")
        audit(f"PLAN,source={ap},reason=no-healthy-gateway,candidate_count=0")
        write_shadow_plan(profile, ap, [])
        return []

    candidates = enumerate_paths_to_gateways(profile, ap, gateways)
    write_shadow_plan(profile, ap, candidates)

    if not candidates:
        print(f"[mesh] shadow plan: no feasible candidate for {ap}")
        audit(f"PLAN,source={ap},reason=no-feasible-path,candidate_count=0")
        return []

    selected = candidates[0]
    selected_text = "->".join(selected["nodes"])

    audit(
        f"PLAN,source={ap},selected={selected_text},cost={selected['cost']},"
        f"candidate_count={len(candidates)}"
    )

    print(f"[mesh] shadow plan for {ap}: {len(candidates)} candidate(s)")
    for index, path in enumerate(candidates, start=1):
        path_text = "->".join(path["nodes"])
        link_text = ",".join(link["name"] for link in path["links"])
        marker = "*" if index == 1 else " "

        print(
            f"  {marker} candidate {index}: "
            f"path={path_text} cost={path['cost']} gateway={path['gateway_ap']} links={link_text}"
        )

    print(f"[mesh] shadow plan saved: {SHADOW_PLAN_PATH}")
    return candidates


def disable_fallback_links(profile: dict[str, Any]) -> None:
    for link in profile.get("fallback_links", []):
        for iface in link["ifaces"]:
            set_iface(iface, "down")


def reset_mesh(profile: dict[str, Any]) -> None:
    if profile.get("fallback_links"):
        return

    for iface in all_mesh_ifaces(profile):
        set_iface(iface, "down")

def restore_primary(profile: dict[str, Any]) -> None:
    primary_links = profile.get("primary_links", [])

    if primary_links:
        for link in primary_links:
            for iface in link["ifaces"]:
                set_iface(iface, "up")
        return

    for path in profile.get("primary_paths", {}).values():
        for iface in path["ifaces"]:
            set_iface(iface, "up")


def enable_path(path: dict[str, Any]) -> None:
    for link in path["links"]:
        for iface in link["ifaces"]:
            set_iface(iface, "up")


def update_history(path: dict[str, Any]) -> None:
    if HISTORY_PATH.exists():
        with HISTORY_PATH.open("r", encoding="utf-8") as f:
            history = json.load(f)
    else:
        history = {}

    key = "->".join(path["nodes"])
    entry = history.setdefault(key, {
        "success_count": 0,
        "last_cost": path["cost"],
        "last_gateway_ap": path["gateway_ap"],
        "last_used_at": None,
    })

    entry["success_count"] += 1
    entry["last_cost"] = path["cost"]
    entry["last_gateway_ap"] = path["gateway_ap"]
    entry["last_used_at"] = now()

    with HISTORY_PATH.open("w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)
        f.write("\n")


def show_status(profile: dict[str, Any]) -> None:
    trust_state = load_trust_state()
    q_nodes = quarantined_nodes(profile, trust_state)
    q_links = quarantined_links(profile, trust_state)

    print("[mesh] primary links")
    for link in profile.get("primary_links", []):
        states = [f"{iface}={iface_state_label(iface)}" for iface in link["ifaces"]]
        print(f"  {link['name']}: " + ", ".join(states))

    print("\n[mesh] fallback links")
    for link in profile.get("fallback_links", []):
        states = [f"{iface}={iface_state_label(iface)}" for iface in link["ifaces"]]
        print(f"  {link['name']}: " + ", ".join(states))

    print("\n[mesh] trust state")
    print(f"  quarantined_nodes: {', '.join(sorted(q_nodes)) if q_nodes else 'none'}")
    print(f"  quarantined_links: {', '.join(sorted(q_links)) if q_links else 'none'}")

    print("\n[mesh] primary AP paths")
    for ap in profile["ap_nodes"]:
        trust = "QUARANTINED" if ap in q_nodes else "trusted"
        print(f"  {ap}: {'UP' if primary_path_up(profile, ap) else 'DOWN'} trust={trust}")

    print("\n[mesh] candidate AP mesh links")
    for link in profile.get("mesh_links", []):
        states = [f"{iface}={iface_state_label(iface)}" for iface in link["ifaces"]]
        availability = "available" if link.get("available") else "blocked"
        trusted, reason = link_trust_status(profile, link, trust_state)
        base_cost = int(link.get("cost", 100))
        learned_cost = learned_link_cost(link)

        print(
            f"  {link['name']}: "
            f"{availability}, "
            f"trust={'trusted' if trusted else reason}, "
            f"base_cost={base_cost}, "
            f"learned_cost={learned_cost}, "
            + ", ".join(states)
        )

    gateways = sorted(healthy_gateways(profile))
    print(f"\n[mesh] healthy gateway APs: {', '.join(gateways) if gateways else 'none'}")


def repair_one(profile: dict[str, Any], ap: str, reset_first: bool = True) -> bool:
    if ap not in profile["ap_nodes"]:
        print(f"[mesh] unknown AP: {ap}")
        audit(f"FAILED,source={ap},reason=unknown-ap")
        return False

    trust_state = load_trust_state()
    if ap in quarantined_nodes(profile, trust_state):
        print(f"[mesh] {ap} is quarantined; repair refused")
        audit(f"FAILED,source={ap},reason=source-quarantined")
        return False

    if reset_first:
        disable_fallback_links(profile)
        reset_mesh(profile)

    if primary_path_up(profile, ap):
        print(f"[mesh] {ap} already has a primary path")
        audit(f"NOOP,source={ap},primary-path-up")
        return True

    gateways = healthy_gateways(profile)
    if not gateways:
        print("[mesh] no healthy AP gateway path")
        audit(f"FAILED,source={ap},reason=no-healthy-gateway")
        return False

    candidates = plan_one(profile, ap)
    if not candidates:
        print(f"[mesh] no feasible mesh path from {ap} to any healthy gateway AP")
        audit(f"FAILED,source={ap},reason=no-feasible-path")
        return False

    path = candidates[0]


    enable_path(path)
    update_history(path)

    path_text = "->".join(path["nodes"])
    print(f"[mesh] selected fallback path for {ap}: {path_text} cost={path['cost']} gateway={path['gateway_ap']}")
    audit(f"REPAIR,source={ap},path={path_text},cost={path['cost']},gateway={path['gateway_ap']}")
    return True


def repair_all(profile: dict[str, Any]) -> bool:
    disable_fallback_links(profile)
    reset_mesh(profile)

    affected = [ap for ap in profile["ap_nodes"] if not primary_path_up(profile, ap)]
    gateways = healthy_gateways(profile)

    if not affected:
        print("[mesh] all APs have primary paths")
        audit("NOOP,repair-all,no-affected-aps")
        return True

    if not gateways:
        print("[mesh] no healthy AP gateway path")
        audit("FAILED,repair-all,reason=no-healthy-gateway")
        return False

    selected_links: dict[str, dict[str, Any]] = {}
    selected_paths = []

    for ap in affected:
        path = shortest_path_to_gateway(profile, ap, gateways)
        if path is None:
            print(f"[mesh] no feasible path for {ap}")
            audit(f"FAILED,source={ap},reason=no-feasible-path")
            continue

        selected_paths.append(path)
        for link in path["links"]:
            selected_links[link["name"]] = link

    if not selected_paths:
        return False

    for link in selected_links.values():
        for iface in link["ifaces"]:
            set_iface(iface, "up")

    for path in selected_paths:
        update_history(path)
        path_text = "->".join(path["nodes"])
        print(f"[mesh] selected fallback path for {path['source']}: {path_text} cost={path['cost']} gateway={path['gateway_ap']}")
        audit(f"REPAIR,source={path['source']},path={path_text},cost={path['cost']},gateway={path['gateway_ap']}")

    return True


def enable_inter_island(profile: dict[str, Any]) -> None:
    for link in profile.get("fallback_links", []):
        if link["name"] == "s6-s7":
            for iface in link["ifaces"]:
                set_iface(iface, "up")
            audit("REPAIR,inter-island,s6-s7-up")
            print("[mesh] inter-island fallback s6-s7 enabled")
            return

    print("[mesh] inter-island fallback link s6-s7 not configured")

def set_node_quarantine(profile: dict[str, Any], node: str, enabled: bool) -> bool:
    if node not in profile["ap_nodes"]:
        print(f"[mesh] unknown AP node: {node}")
        return False

    state = load_trust_state()
    nodes = set(state.get("quarantined_nodes", []))

    if enabled:
        nodes.add(node)
        action = "quarantine-node"
    else:
        nodes.discard(node)
        action = "unquarantine-node"

    state["quarantined_nodes"] = sorted(nodes)
    save_trust_state(state)

    audit(f"TRUST,{action}={node}")
    print(f"[mesh] {action}: {node}")
    return True


def set_link_quarantine(profile: dict[str, Any], link_name: str, enabled: bool) -> bool:
    canonical = canonical_mesh_link_name(profile, link_name)
    if canonical is None:
        print(f"[mesh] unknown mesh link: {link_name}")
        return False

    state = load_trust_state()
    links = set(state.get("quarantined_links", []))

    if enabled:
        links.add(canonical)
        action = "quarantine-link"
    else:
        links.discard(canonical)
        action = "unquarantine-link"

    state["quarantined_links"] = sorted(links)
    save_trust_state(state)

    audit(f"TRUST,{action}={canonical}")
    print(f"[mesh] {action}: {canonical}")
    return True


def clear_quarantine() -> None:
    save_trust_state(default_trust_state())
    audit("TRUST,clear-quarantine")
    print("[mesh] cleared mesh trust quarantine state")


def set_mesh_cost(profile: dict[str, Any], link_name: str, cost: int) -> bool:
    canonical = canonical_mesh_link_name(profile, link_name)
    if canonical is None:
        print(f"[mesh] unknown mesh link: {link_name}")
        return False

    for link in profile.get("mesh_links", []):
        if link["name"] == canonical:
            old = link.get("cost", 100)
            link["cost"] = cost
            save_profile(profile)
            audit(f"COST,set,{canonical},{old}->{cost}")
            print(f"[mesh] set cost {canonical}: {old}->{cost}")
            return True

    return False


def show_trust_status(profile: dict[str, Any]) -> None:
    state = load_trust_state()
    q_nodes = quarantined_nodes(profile, state)
    q_links = quarantined_links(profile, state)

    print("[mesh] trust state")
    print(f"  state_file: {TRUST_STATE_PATH}")
    print(f"  quarantined_nodes: {', '.join(sorted(q_nodes)) if q_nodes else 'none'}")
    print(f"  quarantined_links: {', '.join(sorted(q_links)) if q_links else 'none'}")

def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(1)

    profile = load_profile()
    command = sys.argv[1]

    if command == "status":
        show_status(profile)
        return

    if command == "reset":
        restore_primary(profile)
        disable_fallback_links(profile)
        reset_mesh(profile)
        audit("RESET,primary-up,fallback-down")
        print("[mesh] primary links restored, fallback/mesh links disabled")
        return

    if command == "repair":
        if len(sys.argv) != 3:
            usage()
            sys.exit(1)
        ok = repair_one(profile, sys.argv[2], reset_first=True)
        sys.exit(0 if ok else 2)

    if command == "repair-all":
        ok = repair_all(profile)
        sys.exit(0 if ok else 2)

    if command == "inter-island":
        enable_inter_island(profile)
        return

    if command == "trust-status":
        show_trust_status(profile)
        return

    if command == "clear-quarantine":
        clear_quarantine()
        return

    if command == "quarantine-node":
        if len(sys.argv) != 3:
            usage()
            sys.exit(1)
        ok = set_node_quarantine(profile, sys.argv[2], enabled=True)
        sys.exit(0 if ok else 2)

    if command == "unquarantine-node":
        if len(sys.argv) != 3:
            usage()
            sys.exit(1)
        ok = set_node_quarantine(profile, sys.argv[2], enabled=False)
        sys.exit(0 if ok else 2)

    if command == "quarantine-link":
        if len(sys.argv) != 3:
            usage()
            sys.exit(1)
        ok = set_link_quarantine(profile, sys.argv[2], enabled=True)
        sys.exit(0 if ok else 2)

    if command == "unquarantine-link":
        if len(sys.argv) != 3:
            usage()
            sys.exit(1)
        ok = set_link_quarantine(profile, sys.argv[2], enabled=False)
        sys.exit(0 if ok else 2)

    if command == "set-cost":
        if len(sys.argv) != 4:
            usage()
            sys.exit(1)
        ok = set_mesh_cost(profile, sys.argv[2], int(sys.argv[3]))
        sys.exit(0 if ok else 2)

    if command == "plan":
        if len(sys.argv) != 3:
            usage()
            sys.exit(1)

        candidates = plan_one(profile, sys.argv[2])
        sys.exit(0 if candidates else 2)

    usage()
    sys.exit(1)


if __name__ == "__main__":
    main()
