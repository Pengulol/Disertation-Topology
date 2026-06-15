#!/usr/bin/env python3

import argparse
import csv
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


CONFIG_DIR = Path("/mnt/shared/island_mode")
RUNTIME_DIR = Path(os.environ.get("ISLAND_RUNTIME_DIR", str(CONFIG_DIR / "runtime")))

KNOWLEDGE_PATH = RUNTIME_DIR / "outage_knowledge.json"
AUDIT_PATH = Path("/tmp/island_audit.log")
PROFILE_PATH = RUNTIME_DIR / "mesh_profile.json"

def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def parse_audit_kv(line: str) -> dict[str, str]:
    result = {}

    for part in line.split(","):
        if "=" not in part:
            continue

        key, value = part.split("=", 1)
        result[key.strip()] = value.strip()

    return result


def read_mesh_repairs() -> list[dict[str, str]]:
    if not AUDIT_PATH.exists():
        return []

    repairs = []

    for line in AUDIT_PATH.read_text(encoding="utf-8").splitlines():
        if "MESH,REPAIR" not in line:
            continue

        kv = parse_audit_kv(line)

        if "source" not in kv or "path" not in kv or "gateway" not in kv:
            continue

        repairs.append({
            "raw": line,
            "source": kv.get("source", "unknown"),
            "gateway": kv.get("gateway", "unknown"),
            "path": kv.get("path", "unknown"),
            "cost": kv.get("cost", "unknown"),
        })

    return repairs

def link_names_from_path(path_text: str) -> list[str]:
    profile = load_json(PROFILE_PATH, {})
    mesh_links = profile.get("mesh_links", [])

    pair_to_link = {}

    for link in mesh_links:
        nodes = link.get("nodes", [])
        if len(nodes) != 2:
            continue

        key = tuple(sorted(nodes))
        pair_to_link[key] = link.get("name")

    nodes = path_text.split("->")
    names = []

    for a, b in zip(nodes, nodes[1:]):
        key = tuple(sorted([a, b]))
        name = pair_to_link.get(key)
        if name:
            names.append(name)

    return names


def read_mesh_latency(metrics_path: Path) -> dict[str, float]:
    if not metrics_path.exists():
        return {}

    values = []

    with metrics_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            if row.get("phase") != "ISLANDED_MESH":
                continue

            if row.get("actor") != "zt_responder":
                continue

            if row.get("service") not in ("svc_critical", "svc_alert"):
                continue

            if row.get("result") != "success":
                continue

            try:
                values.append(float(row.get("latency_ms", "0")))
            except Exception:
                pass

    if not values:
        return {}

    values = sorted(values)
    p95_index = max(0, min(len(values) - 1, int(0.95 * len(values)) - 1))

    return {
        "samples": len(values),
        "avg_latency_ms": round(sum(values) / len(values), 2),
        "p95_latency_ms": round(values[p95_index], 2),
        "max_latency_ms": round(max(values), 2),
    }


def score(success_rate: float, avg_latency_ms: float) -> float:
    latency_penalty = min(0.30, avg_latency_ms / 1000.0) if avg_latency_ms > 0 else 0.0
    return round(max(0.0, min(1.0, success_rate - latency_penalty)), 3)


def update(metrics_path: Path) -> None:
    repairs = read_mesh_repairs()

    if not repairs:
        print("[learn] no MESH,REPAIR events found in /tmp/island_audit.log")
        return

    latency = read_mesh_latency(metrics_path)

    knowledge = load_json(KNOWLEDGE_PATH, {
        "updated_at": None,
        "paths": {},
        "links": {},
    })

    knowledge.setdefault("paths", {})
    knowledge.setdefault("links", {})

    for repair in repairs:
        path_name = repair["path"]

        entry = knowledge["paths"].setdefault(path_name, {
            "attempts": 0,
            "successes": 0,
            "last_source": None,
            "last_gateway": None,
            "last_cost": None,
            "last_used_at": None,
            "avg_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "max_latency_ms": 0.0,
            "latency_samples": 0,
            "score": 0.0,
        })

        entry["attempts"] += 1
        entry["successes"] += 1
        entry["last_source"] = repair["source"]
        entry["last_gateway"] = repair["gateway"]
        entry["last_cost"] = repair["cost"]
        entry["last_used_at"] = now()

        if latency:
            entry["avg_latency_ms"] = latency["avg_latency_ms"]
            entry["p95_latency_ms"] = latency["p95_latency_ms"]
            entry["max_latency_ms"] = latency["max_latency_ms"]
            entry["latency_samples"] = latency["samples"]

        success_rate = entry["successes"] / max(1, entry["attempts"])
        entry["score"] = score(success_rate, float(entry["avg_latency_ms"]))
        for link_name in link_names_from_path(path_name):
            link_entry = knowledge["links"].setdefault(link_name, {
                "attempts": 0,
                "successes": 0,
                "last_used_at": None,
                "score": 0.0,
            })

            link_entry["attempts"] += 1
            link_entry["successes"] += 1
            link_entry["last_used_at"] = now()

            link_success_rate = link_entry["successes"] / max(1, link_entry["attempts"])
            link_entry["score"] = score(link_success_rate, float(entry["avg_latency_ms"]))

    knowledge["updated_at"] = now()

    save_json(KNOWLEDGE_PATH, knowledge)

    print(f"[learn] updated {KNOWLEDGE_PATH}")
    print(json.dumps(knowledge, indent=2, sort_keys=True))


def show() -> None:
    print(json.dumps(load_json(KNOWLEDGE_PATH, {}), indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["update", "show"])
    parser.add_argument("--metrics", default="/mnt/shared/results/integrated_metrics.csv")
    args = parser.parse_args()

    if args.command == "update":
        update(Path(args.metrics))
    else:
        show()


if __name__ == "__main__":
    main()
