#!/usr/bin/env python3
import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean


def to_float(value, default=0.0):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def to_int(value, default=0):
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def read_csv(path: Path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def pass_sort_key(path: Path):
    m = re.search(r"(\d+)$", path.name)
    return int(m.group(1)) if m else 999999


def discover_passes(base: Path):
    passes = sorted(
        [p for p in base.iterdir() if p.is_dir() and p.name.startswith("pass")],
        key=pass_sort_key,
    )
    if passes:
        return passes

    if (base / "integrated_kpi_summary.csv").exists():
        return [base]

    return []


def weighted_mean(pairs):
    total_w = sum(w for _, w in pairs)
    if total_w <= 0:
        vals = [v for v, _ in pairs]
        return mean(vals) if vals else 0.0

    return sum(v * w for v, w in pairs) / total_w


def aggregate_kpis(pass_dirs, outdir: Path):
    by_pass = []
    groups = defaultdict(list)

    for idx, pass_dir in enumerate(pass_dirs, start=1):
        pass_name = pass_dir.name if pass_dir.name.startswith("pass") else f"pass{idx}"

        for row in read_csv(pass_dir / "integrated_kpi_summary.csv"):
            kpi = row.get("kpi", "")
            requests = to_int(row.get("requests"))
            value = to_float(row.get("value"))
            metric_type = row.get("metric_type", "")
            description = row.get("description", "")

            by_pass.append(
                {
                    "pass": pass_name,
                    "kpi": kpi,
                    "description": description,
                    "requests": requests,
                    "metric_type": metric_type,
                    "value": f"{value:.2f}",
                }
            )

            groups[kpi].append(
                {
                    "description": description,
                    "requests": requests,
                    "metric_type": metric_type,
                    "value": value,
                }
            )

    aggregate = []

    for kpi, rows in groups.items():
        values = [r["value"] for r in rows]
        weights = [r["requests"] for r in rows]

        aggregate.append(
            {
                "kpi": kpi,
                "description": rows[0]["description"],
                "metric_type": rows[0]["metric_type"],
                "runs": len(rows),
                "total_requests": sum(weights),
                "mean_value": f"{mean(values):.2f}",
                "weighted_value": f"{weighted_mean(list(zip(values, weights))):.2f}",
                "min_value": f"{min(values):.2f}",
                "max_value": f"{max(values):.2f}",
            }
        )

    write_csv(
        outdir / "demo_kpi_by_pass.csv",
        by_pass,
        ["pass", "kpi", "description", "requests", "metric_type", "value"],
    )

    write_csv(
        outdir / "demo_kpi_aggregate.csv",
        aggregate,
        [
            "kpi",
            "description",
            "metric_type",
            "runs",
            "total_requests",
            "mean_value",
            "weighted_value",
            "min_value",
            "max_value",
        ],
    )

    return aggregate


def aggregate_phases(pass_dirs, outdir: Path):
    by_pass = []
    groups = defaultdict(list)

    for idx, pass_dir in enumerate(pass_dirs, start=1):
        pass_name = pass_dir.name if pass_dir.name.startswith("pass") else f"pass{idx}"

        for row in read_csv(pass_dir / "integrated_phase_summary.csv"):
            phase = row.get("phase", "")
            if phase.lower() == "phase":
                continue

            by_pass.append(
                {
                    "pass": pass_name,
                    "phase": phase,
                    "duration_s": f"{to_float(row.get('duration_s')):.3f}",
                    "total_requests": to_int(row.get("total_requests")),
                    "success_count": to_int(row.get("success_count")),
                    "blocked_count": to_int(row.get("blocked_count")),
                    "success_rate_pct": f"{to_float(row.get('success_rate_pct')):.2f}",
                    "block_rate_pct": f"{to_float(row.get('block_rate_pct')):.2f}",
                    "avg_success_latency_ms": f"{to_float(row.get('avg_success_latency_ms')):.2f}",
                    "max_latency_ms": f"{to_float(row.get('max_latency_ms')):.2f}",
                }
            )

            groups[phase].append(
                {
                    "duration_s": to_float(row.get("duration_s")),
                    "total_requests": to_int(row.get("total_requests")),
                    "success_count": to_int(row.get("success_count")),
                    "blocked_count": to_int(row.get("blocked_count")),
                    "avg_success_latency_ms": to_float(row.get("avg_success_latency_ms")),
                    "max_latency_ms": to_float(row.get("max_latency_ms")),
                }
            )

    aggregate = []

    for phase, rows in groups.items():
        total_requests = sum(r["total_requests"] for r in rows)
        total_success = sum(r["success_count"] for r in rows)
        total_blocked = sum(r["blocked_count"] for r in rows)

        latency_pairs = [
            (r["avg_success_latency_ms"], r["success_count"]) for r in rows
        ]

        aggregate.append(
            {
                "phase": phase,
                "runs": len(rows),
                "total_duration_s": f"{sum(r['duration_s'] for r in rows):.3f}",
                "mean_duration_s": f"{mean([r['duration_s'] for r in rows]):.3f}",
                "total_requests": total_requests,
                "success_count": total_success,
                "blocked_count": total_blocked,
                "weighted_success_rate_pct": f"{(100 * total_success / total_requests) if total_requests else 0:.2f}",
                "weighted_block_rate_pct": f"{(100 * total_blocked / total_requests) if total_requests else 0:.2f}",
                "weighted_avg_success_latency_ms": f"{weighted_mean(latency_pairs):.2f}",
                "max_latency_ms": f"{max([r['max_latency_ms'] for r in rows]) if rows else 0:.2f}",
            }
        )

    write_csv(
        outdir / "demo_phase_by_pass.csv",
        by_pass,
        [
            "pass",
            "phase",
            "duration_s",
            "total_requests",
            "success_count",
            "blocked_count",
            "success_rate_pct",
            "block_rate_pct",
            "avg_success_latency_ms",
            "max_latency_ms",
        ],
    )

    write_csv(
        outdir / "demo_phase_aggregate.csv",
        aggregate,
        [
            "phase",
            "runs",
            "total_duration_s",
            "mean_duration_s",
            "total_requests",
            "success_count",
            "blocked_count",
            "weighted_success_rate_pct",
            "weighted_block_rate_pct",
            "weighted_avg_success_latency_ms",
            "max_latency_ms",
        ],
    )

    return aggregate


def aggregate_latency(pass_dirs, outdir: Path):
    by_pass = []
    groups = defaultdict(list)

    for idx, pass_dir in enumerate(pass_dirs, start=1):
        pass_name = pass_dir.name if pass_dir.name.startswith("pass") else f"pass{idx}"

        for row in read_csv(pass_dir / "integrated_critical_latency_by_phase.csv"):
            phase = row.get("phase", "")
            if phase.lower() == "phase":
                continue

            n = to_int(row.get("successful_critical_requests"))
            avg_latency = to_float(row.get("avg_latency_ms"))

            by_pass.append(
                {
                    "pass": pass_name,
                    "phase": phase,
                    "successful_critical_requests": n,
                    "avg_latency_ms": f"{avg_latency:.2f}",
                    "p50_latency_ms": f"{to_float(row.get('p50_latency_ms')):.2f}",
                    "p95_latency_ms": f"{to_float(row.get('p95_latency_ms')):.2f}",
                    "p99_latency_ms": f"{to_float(row.get('p99_latency_ms')):.2f}",
                    "max_latency_ms": f"{to_float(row.get('max_latency_ms')):.2f}",
                }
            )

            groups[phase].append(
                {
                    "n": n,
                    "avg_latency_ms": avg_latency,
                    "p50_latency_ms": to_float(row.get("p50_latency_ms")),
                    "p95_latency_ms": to_float(row.get("p95_latency_ms")),
                    "p99_latency_ms": to_float(row.get("p99_latency_ms")),
                    "max_latency_ms": to_float(row.get("max_latency_ms")),
                }
            )

    aggregate = []

    for phase, rows in groups.items():
        aggregate.append(
            {
                "phase": phase,
                "runs": len(rows),
                "successful_critical_requests": sum(r["n"] for r in rows),
                "weighted_avg_latency_ms": f"{weighted_mean([(r['avg_latency_ms'], r['n']) for r in rows]):.2f}",
                "mean_p50_latency_ms": f"{mean([r['p50_latency_ms'] for r in rows]):.2f}",
                "mean_p95_latency_ms": f"{mean([r['p95_latency_ms'] for r in rows]):.2f}",
                "mean_p99_latency_ms": f"{mean([r['p99_latency_ms'] for r in rows]):.2f}",
                "max_latency_ms": f"{max([r['max_latency_ms'] for r in rows]) if rows else 0:.2f}",
            }
        )

    write_csv(
        outdir / "demo_latency_by_pass.csv",
        by_pass,
        [
            "pass",
            "phase",
            "successful_critical_requests",
            "avg_latency_ms",
            "p50_latency_ms",
            "p95_latency_ms",
            "p99_latency_ms",
            "max_latency_ms",
        ],
    )

    write_csv(
        outdir / "demo_latency_aggregate.csv",
        aggregate,
        [
            "phase",
            "runs",
            "successful_critical_requests",
            "weighted_avg_latency_ms",
            "mean_p50_latency_ms",
            "mean_p95_latency_ms",
            "mean_p99_latency_ms",
            "max_latency_ms",
        ],
    )

    return aggregate


def print_kpi_table(rows):
    print("\n=== Demo KPI aggregate ===")
    print(
        f"{'KPI':35} {'runs':>4} {'n':>6} {'mean':>8} "
        f"{'weighted':>10} {'min':>8} {'max':>8}"
    )

    for r in rows:
        print(
            f"{r['kpi'][:35]:35} "
            f"{r['runs']:>4} "
            f"{r['total_requests']:>6} "
            f"{r['mean_value']:>8} "
            f"{r['weighted_value']:>10} "
            f"{r['min_value']:>8} "
            f"{r['max_value']:>8}"
        )


def main():
    parser = argparse.ArgumentParser(description="Aggregate repeated demo pass results.")
    parser.add_argument(
        "--base",
        default="/mnt/shared/results/demo_run",
        help="Base demo results directory containing pass1/pass2/... folders",
    )
    parser.add_argument(
        "--outdir",
        default=None,
        help="Output directory for aggregate CSV files. Defaults to --base",
    )
    args = parser.parse_args()

    base = Path(args.base)
    outdir = Path(args.outdir) if args.outdir else base

    if not base.exists():
        raise SystemExit(f"[error] base directory does not exist: {base}")

    pass_dirs = discover_passes(base)

    if not pass_dirs:
        raise SystemExit(f"[error] no pass folders or summary files found under: {base}")

    print(f"[aggregate] base={base}")
    print("[aggregate] passes=" + ", ".join(str(p) for p in pass_dirs))

    kpi_rows = aggregate_kpis(pass_dirs, outdir)
    aggregate_phases(pass_dirs, outdir)
    aggregate_latency(pass_dirs, outdir)

    print_kpi_table(kpi_rows)

    print("\n[saved]", outdir / "demo_kpi_by_pass.csv")
    print("[saved]", outdir / "demo_kpi_aggregate.csv")
    print("[saved]", outdir / "demo_phase_by_pass.csv")
    print("[saved]", outdir / "demo_phase_aggregate.csv")
    print("[saved]", outdir / "demo_latency_by_pass.csv")
    print("[saved]", outdir / "demo_latency_aggregate.csv")


if __name__ == "__main__":
    main()
