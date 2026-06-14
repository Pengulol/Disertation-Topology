#!/usr/bin/env python3
import argparse
import csv
import os
from collections import defaultdict


ORDER = [
    "NORMAL",
    "DEGRADED",
    "ISLANDED",
    "ISLANDED_MESH",
    "TRUST_AWARE_MESH",
    "INTER_ISLAND_MESH",
    "REATTACH",
    "NORMAL_RESTORED",
]

RESPONDER_ACTORS = {"zt_responder", "zt_responder_i2"}
CIVILIAN_ACTORS = {"zt_civilian_user", "zt_civilian_user_i2"}
ATTACKER_ACTORS = {"zt_attacker", "zt_attacker_i2"}
UNAUTHORIZED_ACTORS = CIVILIAN_ACTORS | ATTACKER_ACTORS

ISLAND_PHASES = {
    "ISLANDED",
    "ISLANDED_MESH",
    "TRUST_AWARE_MESH",
    "INTER_ISLAND_MESH",
}


def to_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default


def pct(part, total):
    if total == 0:
        return 0.0
    return 100.0 * part / total


def avg(values):
    return sum(values) / len(values) if values else 0.0


def phase_sort_key(phase):
    if phase in ORDER:
        return ORDER.index(phase)
    return 999


def expected_result(phase, actor, service):
    if phase in ("NORMAL", "NORMAL_RESTORED"):
        return "success"

    if phase == "DEGRADED":
        if actor in RESPONDER_ACTORS and service in (
            "svc_critical",
            "svc_alert",
            "svc_noncritical",
            "svc_central_identity",
        ):
            return "success"

        if actor in RESPONDER_ACTORS and service == "svc_external":
            return "blocked"

        if actor in UNAUTHORIZED_ACTORS and service == "svc_critical":
            return "blocked"

    if phase in ISLAND_PHASES:
        if actor in RESPONDER_ACTORS and service in ("svc_critical", "svc_alert"):
            return "success"

        if actor in RESPONDER_ACTORS and service in (
            "svc_noncritical",
            "svc_external",
            "svc_central_identity",
        ):
            return "blocked"

        if actor in UNAUTHORIZED_ACTORS and service == "svc_critical":
            return "blocked"

    if phase == "REATTACH":
        return "skip"

    return "skip"


def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def filter_rows(rows, phases=None, actors=None, services=None, results=None):
    out = []
    for r in rows:
        if phases is not None and r["phase"] not in phases:
            continue
        if actors is not None and r["actor"] not in actors:
            continue
        if services is not None and r["service"] not in services:
            continue
        if results is not None and r["result"] not in results:
            continue
        out.append(r)
    return out


def success_rate(rows):
    return pct(len([r for r in rows if r["result"] == "success"]), len(rows))


def block_rate(rows):
    return pct(len([r for r in rows if r["result"] == "blocked"]), len(rows))


def avg_success_latency(rows):
    lat = [to_float(r["latency_ms"]) for r in rows if r["result"] == "success"]
    return avg(lat)


def max_latency(rows):
    vals = [to_float(r["latency_ms"]) for r in rows]
    return max(vals) if vals else 0.0


def pass_rate(rows):
    scored = []
    passed = 0

    for r in rows:
        expected = expected_result(r["phase"], r["actor"], r["service"])
        if expected == "skip":
            continue
        scored.append(r)
        if r["result"] == expected:
            passed += 1

    return pct(passed, len(scored)), passed, len(scored)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="/mnt/shared/results/integrated_metrics.csv")
    parser.add_argument("--outdir", default="/mnt/shared/results")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    with open(args.input, newline="") as f:
        rows = list(csv.DictReader(f))

    for r in rows:
        r["t_rel_s"] = str(to_float(r.get("t_rel_s", "0")))
        r["latency_ms"] = str(to_float(r.get("latency_ms", "0")))

    phase_groups = defaultdict(list)
    detail_groups = defaultdict(list)

    for r in rows:
        phase_groups[r["phase"]].append(r)
        detail_groups[(r["phase"], r["actor"], r["service"])].append(r)


    phase_summary = []
    for phase in sorted(phase_groups.keys(), key=phase_sort_key):
        group = phase_groups[phase]
        times = [to_float(r["t_rel_s"]) for r in group]
        succ = filter_rows(group, results={"success"})
        blocked = filter_rows(group, results={"blocked"})

        phase_summary.append({
            "phase": phase,
            "start_s": f"{min(times):.3f}",
            "end_s": f"{max(times):.3f}",
            "duration_s": f"{max(times) - min(times):.3f}",
            "total_requests": len(group),
            "success_count": len(succ),
            "blocked_count": len(blocked),
            "success_rate_pct": f"{success_rate(group):.2f}",
            "block_rate_pct": f"{block_rate(group):.2f}",
            "avg_success_latency_ms": f"{avg_success_latency(group):.2f}",
            "max_latency_ms": f"{max_latency(group):.2f}",
        })


    expectation_summary = []
    for key in sorted(detail_groups.keys(), key=lambda k: (phase_sort_key(k[0]), k[1], k[2])):
        phase, actor, service = key
        group = detail_groups[key]
        expected = expected_result(phase, actor, service)
        pr, pc, scored = pass_rate(group)

        expectation_summary.append({
            "phase": phase,
            "actor": actor,
            "service": service,
            "expected": expected,
            "total_requests": len(group),
            "success_count": len(filter_rows(group, results={"success"})),
            "blocked_count": len(filter_rows(group, results={"blocked"})),
            "pass_count": "" if expected == "skip" else pc,
            "scored_requests": "" if expected == "skip" else scored,
            "pass_rate_pct": "" if expected == "skip" else f"{pr:.2f}",
            "avg_success_latency_ms": f"{avg_success_latency(group):.2f}",
            "max_latency_ms": f"{max_latency(group):.2f}",
        })

    kpi_rows = []

    def add_kpi(name, description, selected, metric_type, value):
        kpi_rows.append({
            "kpi": name,
            "description": description,
            "requests": len(selected),
            "metric_type": metric_type,
            "value": f"{value:.2f}",
        })

    critical_continuity_rows = filter_rows(
        rows,
        phases={
            "DEGRADED",
            "ISLANDED",
            "ISLANDED_MESH",
            "TRUST_AWARE_MESH",
            "INTER_ISLAND_MESH",
        },
        actors=RESPONDER_ACTORS,
        services={"svc_critical", "svc_alert"},
    )
    add_kpi(
        "critical_service_continuity",
        "Responder access to critical and alert services during degraded/islanded operation",
        critical_continuity_rows,
        "success_rate_pct",
        success_rate(critical_continuity_rows),
    )

    unauthorized_rows = filter_rows(
        rows,
        phases={
            "DEGRADED",
            "ISLANDED",
            "ISLANDED_MESH",
            "TRUST_AWARE_MESH",
            "INTER_ISLAND_MESH",
        },
        actors=UNAUTHORIZED_ACTORS,
        services={"svc_critical"},
    )
    add_kpi(
        "unauthorized_access_blocking",
        "Attacker and civilian requests to critical service must be blocked outside normal mode",
        unauthorized_rows,
        "block_rate_pct",
        block_rate(unauthorized_rows),
    )

    island_restriction_rows = filter_rows(
        rows,
        phases={
            "ISLANDED",
            "ISLANDED_MESH",
            "TRUST_AWARE_MESH",
            "INTER_ISLAND_MESH",
        },
        actors=RESPONDER_ACTORS,
        services={"svc_noncritical", "svc_external", "svc_central_identity"},
    )
    add_kpi(
        "island_graceful_degradation",
        "Non-critical, external and central identity access should be restricted in island mode",
        island_restriction_rows,
        "block_rate_pct",
        block_rate(island_restriction_rows),
    )

    trust_aware_rows = filter_rows(
        rows,
        phases={"TRUST_AWARE_MESH"},
        actors={"zt_responder"},
        services={"svc_critical", "svc_alert"},
    )
    add_kpi(
        "trust_aware_mesh_continuity",
        "Responder critical/alert access while quarantined mesh relay is avoided",
        trust_aware_rows,
        "success_rate_pct",
        success_rate(trust_aware_rows),
    )

    inter_island_rows = filter_rows(
        rows,
        phases={"INTER_ISLAND_MESH"},
        actors={"zt_responder_i2"},
        services={"svc_critical", "svc_alert"},
    )
    add_kpi(
        "inter_island_fallback_continuity",
        "Second-island responder access to critical/alert services through inter-island fallback",
        inter_island_rows,
        "success_rate_pct",
        success_rate(inter_island_rows),
    )

    normal_restore_rows = filter_rows(
        rows,
        phases={"NORMAL_RESTORED"},
    )
    add_kpi(
        "normal_restore_availability",
        "Service availability after reattach and restoration to normal forwarding",
        normal_restore_rows,
        "success_rate_pct",
        success_rate(normal_restore_rows),
    )

    scored_pass_pct, scored_pass_count, scored_total = pass_rate(rows)
    kpi_rows.append({
        "kpi": "overall_policy_correctness",
        "description": "Requests matching expected policy outcome across all scored phases",
        "requests": scored_total,
        "metric_type": "pass_rate_pct",
        "value": f"{scored_pass_pct:.2f}",
    })

    critical_latency_rows = filter_rows(
        rows,
        phases={
            "NORMAL",
            "DEGRADED",
            "ISLANDED",
            "ISLANDED_MESH",
            "TRUST_AWARE_MESH",
            "INTER_ISLAND_MESH",
            "NORMAL_RESTORED",
        },
        actors=RESPONDER_ACTORS,
        services={"svc_critical", "svc_alert"},
    )
    add_kpi(
        "critical_success_latency_avg",
        "Average latency for successful responder critical/alert requests",
        critical_latency_rows,
        "avg_success_latency_ms",
        avg_success_latency(critical_latency_rows),
    )

    phase_out = os.path.join(args.outdir, "integrated_phase_summary.csv")
    expectation_out = os.path.join(args.outdir, "integrated_expectation_summary.csv")
    kpi_out = os.path.join(args.outdir, "integrated_kpi_summary.csv")

    write_csv(phase_out, phase_summary, [
        "phase",
        "start_s",
        "end_s",
        "duration_s",
        "total_requests",
        "success_count",
        "blocked_count",
        "success_rate_pct",
        "block_rate_pct",
        "avg_success_latency_ms",
        "max_latency_ms",
    ])

    write_csv(expectation_out, expectation_summary, [
        "phase",
        "actor",
        "service",
        "expected",
        "total_requests",
        "success_count",
        "blocked_count",
        "pass_count",
        "scored_requests",
        "pass_rate_pct",
        "avg_success_latency_ms",
        "max_latency_ms",
    ])

    write_csv(kpi_out, kpi_rows, [
        "kpi",
        "description",
        "requests",
        "metric_type",
        "value",
    ])

    print("")
    print("=== Phase summary ===")
    for r in phase_summary:
        print(
            f"{r['phase']:18s} "
            f"n={r['total_requests']:4d} "
            f"success={r['success_rate_pct']:>6s}% "
            f"blocked={r['block_rate_pct']:>6s}% "
            f"avg_latency={r['avg_success_latency_ms']:>7s} ms "
            f"duration={r['duration_s']:>7s}s"
        )

    print("")
    print("=== KPI summary ===")
    for r in kpi_rows:
        print(
            f"{r['kpi']:32s} "
            f"{r['metric_type']:24s} "
            f"value={r['value']:>7s} "
            f"n={r['requests']}"
        )

    print("")
    print("[saved]", phase_out)
    print("[saved]", expectation_out)
    print("[saved]", kpi_out)


if __name__ == "__main__":
    main()
