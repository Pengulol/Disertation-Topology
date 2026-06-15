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

DEFAULT_KNOWLEDGE = RUNTIME_DIR / "outage_knowledge.json"
DEFAULT_HISTORY = RUNTIME_DIR / "path_history.json"
DEFAULT_SHADOW_PLAN = RUNTIME_DIR / "shadow_repair_plan.json"
DEFAULT_AUDIT = Path("/tmp/island_audit.log")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def read_text(path: Path) -> str:
    if not path.exists():
        return ""

    return path.read_text(encoding="utf-8", errors="replace")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_audit_counts(audit_text: str) -> dict[str, int]:
    counts = {
        "plan_events": 0,
        "repair_events": 0,
        "trust_events": 0,
        "inter_island_repairs": 0,
        "failed_repairs": 0,
    }

    for line in audit_text.splitlines():
        if "MESH,PLAN" in line:
            counts["plan_events"] += 1
        if "MESH,REPAIR" in line:
            counts["repair_events"] += 1
        if "MESH,TRUST" in line:
            counts["trust_events"] += 1
        if "inter-island" in line or "s6-s7-up" in line:
            counts["inter_island_repairs"] += 1
        if "MESH,FAILED" in line:
            counts["failed_repairs"] += 1

    return counts


def flatten_paths(knowledge: dict[str, Any], history: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    paths = knowledge.get("paths", {}) if isinstance(knowledge, dict) else {}
    all_names = sorted(set(paths.keys()) | set(history.keys()))

    for name in all_names:
        k = paths.get(name, {}) if isinstance(paths.get(name, {}), dict) else {}
        h = history.get(name, {}) if isinstance(history.get(name, {}), dict) else {}

        rows.append({
            "path": name,
            "knowledge_attempts": k.get("attempts", 0),
            "knowledge_successes": k.get("successes", 0),
            "history_success_count": h.get("success_count", 0),
            "last_source": k.get("last_source", ""),
            "last_gateway": k.get("last_gateway", h.get("last_gateway_ap", "")),
            "last_cost": k.get("last_cost", h.get("last_cost", "")),
            "score": k.get("score", ""),
            "last_used_at": k.get("last_used_at", h.get("last_used_at", "")),
        })

    return rows


def flatten_links(knowledge: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    links = knowledge.get("links", {}) if isinstance(knowledge, dict) else {}

    for name, entry in sorted(links.items()):
        if not isinstance(entry, dict):
            continue

        rows.append({
            "link": name,
            "attempts": entry.get("attempts", 0),
            "successes": entry.get("successes", 0),
            "score": entry.get("score", ""),
            "last_used_at": entry.get("last_used_at", ""),
        })

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize adaptation knowledge for Zero-Trust Island Mode."
    )

    parser.add_argument("--knowledge", default=str(DEFAULT_KNOWLEDGE))
    parser.add_argument("--history", default=str(DEFAULT_HISTORY))
    parser.add_argument("--shadow-plan", default=str(DEFAULT_SHADOW_PLAN))
    parser.add_argument("--audit", default=str(DEFAULT_AUDIT))
    parser.add_argument("--outdir", default="/mnt/shared/results")

    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    knowledge = load_json(Path(args.knowledge), {"paths": {}, "links": {}})
    history = load_json(Path(args.history), {})
    shadow_plan = load_json(Path(args.shadow_plan), {})
    audit_text = read_text(Path(args.audit))

    audit_counts = parse_audit_counts(audit_text)
    path_rows = flatten_paths(knowledge, history)
    link_rows = flatten_links(knowledge)

    selected_shadow = shadow_plan.get("selected") or {}
    selected_path = selected_shadow.get("path", "") if isinstance(selected_shadow, dict) else ""

    most_reused_path = ""
    most_reused_count = -1

    for row in path_rows:
        count = int(row.get("knowledge_attempts") or 0) + int(row.get("history_success_count") or 0)

        if count > most_reused_count:
            most_reused_count = count
            most_reused_path = row["path"]

    summary_rows = [
        {
            "item": "learned_paths",
            "value": len(path_rows),
            "interpretation": "number of mesh repair paths preserved in knowledge/history",
        },
        {
            "item": "learned_links",
            "value": len(link_rows),
            "interpretation": "number of mesh links with learned scores",
        },
        {
            "item": "plan_events",
            "value": audit_counts["plan_events"],
            "interpretation": "shadow/twin-lite planning events before execution",
        },
        {
            "item": "repair_events",
            "value": audit_counts["repair_events"],
            "interpretation": "executed mesh/inter-island repair events",
        },
        {
            "item": "trust_events",
            "value": audit_counts["trust_events"],
            "interpretation": "quarantine or trust-state changes observed by planner",
        },
        {
            "item": "most_reused_path",
            "value": most_reused_path,
            "interpretation": "path most frequently reused by repair/history evidence",
        },
        {
            "item": "last_shadow_selected_path",
            "value": selected_path,
            "interpretation": "candidate selected by latest shadow repair plan",
        },
    ]

    write_csv(
        outdir / "adaptation_knowledge_summary.csv",
        summary_rows,
        ["item", "value", "interpretation"],
    )

    write_csv(
        outdir / "adaptation_knowledge_paths.csv",
        path_rows,
        [
            "path",
            "knowledge_attempts",
            "knowledge_successes",
            "history_success_count",
            "last_source",
            "last_gateway",
            "last_cost",
            "score",
            "last_used_at",
        ],
    )

    write_csv(
        outdir / "adaptation_knowledge_links.csv",
        link_rows,
        ["link", "attempts", "successes", "score", "last_used_at"],
    )

    report = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "model": "DLiSA-inspired lightweight adaptation knowledge report",
        "scope": "Zero-Trust Island Mode mesh recovery and orchestration",
        "summary": summary_rows,
        "paths": path_rows,
        "links": link_rows,
        "latest_shadow_plan": shadow_plan,
        "not_full_dlisa": [
            "no evolutionary configuration planning",
            "no ranked workload similarity over software configuration vectors",
            "no weighted GA seeding",
            "no trained surrogate Cyber-Twin",
        ],
    }

    report_path = outdir / "adaptation_knowledge_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("=== Adaptation knowledge report ===")
    for row in summary_rows:
        print(f"{row['item']:<28} {row['value']}")

    print(f"\n[saved] {outdir / 'adaptation_knowledge_summary.csv'}")
    print(f"[saved] {outdir / 'adaptation_knowledge_paths.csv'}")
    print(f"[saved] {outdir / 'adaptation_knowledge_links.csv'}")
    print(f"[saved] {report_path}")


if __name__ == "__main__":
    main()
