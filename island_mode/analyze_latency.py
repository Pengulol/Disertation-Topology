#!/usr/bin/env python3
import argparse
import csv
import math
import os
from collections import defaultdict


PHASE_ORDER = [
    "NORMAL",
    "DEGRADED",
    "ISLANDED",
    "ISLANDED_MESH",
    "TRUST_AWARE_MESH",
    "INTER_ISLAND_MESH",
    "REATTACH",
    "NORMAL_RESTORED",
    "ALL_PHASES",
]

RESPONDER_ACTORS = {"zt_responder", "zt_responder_i2"}


def to_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default


def percentile(values, p):
    if not values:
        return 0.0

    values = sorted(values)
    idx = math.ceil((p / 100.0) * len(values)) - 1
    idx = max(0, min(idx, len(values) - 1))
    return values[idx]


def avg(values):
    return sum(values) / len(values) if values else 0.0


def phase_key(phase):
    if phase in PHASE_ORDER:
        return PHASE_ORDER.index(phase)
    return 999


def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="/mnt/shared/results/integrated_metrics.csv")
    parser.add_argument("--outdir", default="/mnt/shared/results")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    with open(args.input, newline="") as f:
        rows = list(csv.DictReader(f))


    critical_rows = [
        r for r in rows
        if r.get("actor") in RESPONDER_ACTORS
        and r.get("service") in ("svc_critical", "svc_alert")
        and r.get("result") == "success"
    ]

    groups = defaultdict(list)
    for r in critical_rows:
        groups[r["phase"]].append(to_float(r["latency_ms"]))

    summary = []

    for phase in sorted(groups.keys(), key=phase_key):
        vals = groups[phase]

        summary.append({
            "phase": phase,
            "successful_critical_requests": len(vals),
            "avg_latency_ms": f"{avg(vals):.2f}",
            "p50_latency_ms": f"{percentile(vals, 50):.2f}",
            "p95_latency_ms": f"{percentile(vals, 95):.2f}",
            "p99_latency_ms": f"{percentile(vals, 99):.2f}",
            "max_latency_ms": f"{max(vals):.2f}",
        })

    all_vals = [to_float(r["latency_ms"]) for r in critical_rows]

    if all_vals:
        summary.append({
            "phase": "ALL_PHASES",
            "successful_critical_requests": len(all_vals),
            "avg_latency_ms": f"{avg(all_vals):.2f}",
            "p50_latency_ms": f"{percentile(all_vals, 50):.2f}",
            "p95_latency_ms": f"{percentile(all_vals, 95):.2f}",
            "p99_latency_ms": f"{percentile(all_vals, 99):.2f}",
            "max_latency_ms": f"{max(all_vals):.2f}",
        })

    out_path = os.path.join(args.outdir, "integrated_critical_latency_by_phase.csv")

    write_csv(out_path, summary, [
        "phase",
        "successful_critical_requests",
        "avg_latency_ms",
        "p50_latency_ms",
        "p95_latency_ms",
        "p99_latency_ms",
        "max_latency_ms",
    ])

    print("")
    print("=== Critical/alert responder latency by phase ===")
    for r in summary:
        print(
            f"{r['phase']:18s} "
            f"n={r['successful_critical_requests']:4d} "
            f"avg={r['avg_latency_ms']:>7s} ms "
            f"p50={r['p50_latency_ms']:>7s} ms "
            f"p95={r['p95_latency_ms']:>7s} ms "
            f"max={r['max_latency_ms']:>7s} ms"
        )

    print("")
    print("[saved]", out_path)


if __name__ == "__main__":
    main()
