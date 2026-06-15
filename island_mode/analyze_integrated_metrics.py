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
    "INTER_ISLAND_FALLBACK",
    "REATTACH",
    "NORMAL_RESTORED",
]

RESPONDER_ACTORS = {"zt_responder", "zt_responder_i2"}
CIVILIAN_ACTORS = {"zt_civilian_user", "zt_civilian_user_i2"}
SENSOR_ACTORS = {"zt_sensor", "zt_sensor_i2"}
ATTACKER_ACTORS = {"zt_attacker", "zt_attacker_i2"}

DEGRADED_LIMITED_ACTORS = CIVILIAN_ACTORS | SENSOR_ACTORS
ISLAND_UNAUTHORIZED_ACTORS = CIVILIAN_ACTORS | SENSOR_ACTORS | ATTACKER_ACTORS

CRITICAL_SERVICES = {"svc_critical", "svc_alert"}
RESTRICTED_SERVICES = {"svc_noncritical", "svc_external", "svc_central_identity"}

ACTOR_ALIASES = {
    "10.0.0.101": "zt_responder",
    "10.0.0.102": "zt_civilian_user",
    "10.0.0.103": "zt_sensor",
    "10.0.0.104": "zt_attacker",
    "10.0.0.111": "zt_responder_i2",
    "10.0.0.112": "zt_civilian_user_i2",
    "10.0.0.113": "zt_sensor_i2",
    "10.0.0.114": "zt_attacker_i2",
}

SERVICE_ALIASES = {
    "critical": "svc_critical",
    "crit": "svc_critical",
    "10.0.0.30": "svc_critical",
    "alert": "svc_alert",
    "10.0.0.31": "svc_alert",
    "noncritical": "svc_noncritical",
    "non-critical": "svc_noncritical",
    "ncrit": "svc_noncritical",
    "10.0.0.40": "svc_noncritical",
    "central_identity": "svc_central_identity",
    "central-control": "svc_central_identity",
    "central_control": "svc_central_identity",
    "10.0.0.10": "svc_central_identity",
    "external": "svc_external",
    "inet": "svc_external",
    "10.0.0.70": "svc_external",
}


def normalize_actor(actor):
    return ACTOR_ALIASES.get(actor, actor)


def normalize_service(service):
    return SERVICE_ALIASES.get(service, service)


ISLAND_PHASES = {
    "ISLANDED",
    "ISLANDED_MESH",
    "TRUST_AWARE_MESH",
    "INTER_ISLAND_MESH",
    "INTER_ISLAND_FALLBACK",
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


def percentile(values, p):
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * p
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    frac = rank - lower
    return ordered[lower] * (1 - frac) + ordered[upper] * frac


def phase_sort_key(phase):
    if phase in ORDER:
        return ORDER.index(phase)
    return 999


def expected_result_details(phase, actor, service):

    phase = phase.upper()

    if phase in ("NORMAL", "NORMAL_RESTORED"):
        return "success", "normal"

    if phase == "DEGRADED":
        if service in RESTRICTED_SERVICES:
            return "blocked", "deny"

        if service in CRITICAL_SERVICES:
            if actor in RESPONDER_ACTORS:
                return "success", "full"
            if actor in DEGRADED_LIMITED_ACTORS:
                return "success", "limited"
            if actor in ATTACKER_ACTORS:
                return "blocked", "deny"

    if phase in ISLAND_PHASES:
        if actor in RESPONDER_ACTORS and service in CRITICAL_SERVICES:
            return "success", "full"

        if actor in RESPONDER_ACTORS and service in RESTRICTED_SERVICES:
            return "blocked", "deny"

        if actor in ISLAND_UNAUTHORIZED_ACTORS and service in CRITICAL_SERVICES:
            return "blocked", "deny"

    if phase == "REATTACH":
        return "skip", "skip"

    return "skip", "skip"


def expected_result(phase, actor, service):
    return expected_result_details(phase, actor, service)[0]


def expected_tier(phase, actor, service):
    return expected_result_details(phase, actor, service)[1]


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


def p95_success_latency(rows):
    lat = [to_float(r["latency_ms"]) for r in rows if r["result"] == "success"]
    return percentile(lat, 0.95)


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
        r["actor_raw"] = r.get("actor", "")
        r["service_raw"] = r.get("service", "")
        r["actor"] = normalize_actor(r.get("actor", ""))
        r["service"] = normalize_service(r.get("service", ""))
        r["t_rel_s"] = str(to_float(r.get("t_rel_s", "0")))
        r["latency_ms"] = str(to_float(r.get("latency_ms", "0")))
        r["result"] = r.get("result", "") or "unknown"

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
            "p95_success_latency_ms": f"{p95_success_latency(group):.2f}",
            "max_latency_ms": f"{max_latency(group):.2f}",
        })

    expectation_summary = []
    for key in sorted(detail_groups.keys(), key=lambda k: (phase_sort_key(k[0]), k[1], k[2])):
        phase, actor, service = key
        group = detail_groups[key]
        expected = expected_result(phase, actor, service)
        tier = expected_tier(phase, actor, service)
        pr, pc, scored = pass_rate(group)

        expectation_summary.append({
            "phase": phase,
            "actor": actor,
            "service": service,
            "expected": expected,
            "expected_tier": tier,
            "total_requests": len(group),
            "success_count": len(filter_rows(group, results={"success"})),
            "blocked_count": len(filter_rows(group, results={"blocked"})),
            "pass_count": "" if expected == "skip" else pc,
            "scored_requests": "" if expected == "skip" else scored,
            "pass_rate_pct": "" if expected == "skip" else f"{pr:.2f}",
            "avg_success_latency_ms": f"{avg_success_latency(group):.2f}",
            "p95_success_latency_ms": f"{p95_success_latency(group):.2f}",
            "max_latency_ms": f"{max_latency(group):.2f}",
        })

    degraded_limit_summary = []
    degraded_keys = [
        key for key in detail_groups.keys()
        if key[0] == "DEGRADED" and expected_tier(key[0], key[1], key[2]) in {"full", "limited", "deny"}
    ]
    for key in sorted(degraded_keys, key=lambda k: (k[1], k[2])):
        phase, actor, service = key
        group = detail_groups[key]
        expected = expected_result(phase, actor, service)
        tier = expected_tier(phase, actor, service)
        pr, pc, scored = pass_rate(group)

        degraded_limit_summary.append({
            "phase": phase,
            "actor": actor,
            "service": service,
            "expected": expected,
            "expected_tier": tier,
            "meter_expected": "yes" if tier == "limited" else "no",
            "total_requests": len(group),
            "success_count": len(filter_rows(group, results={"success"})),
            "blocked_count": len(filter_rows(group, results={"blocked"})),
            "pass_count": "" if expected == "skip" else pc,
            "scored_requests": "" if expected == "skip" else scored,
            "pass_rate_pct": "" if expected == "skip" else f"{pr:.2f}",
            "success_rate_pct": f"{success_rate(group):.2f}",
            "block_rate_pct": f"{block_rate(group):.2f}",
            "avg_success_latency_ms": f"{avg_success_latency(group):.2f}",
            "p95_success_latency_ms": f"{p95_success_latency(group):.2f}",
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
            "INTER_ISLAND_FALLBACK",
        },
        actors=RESPONDER_ACTORS,
        services=CRITICAL_SERVICES,
    )
    add_kpi(
        "critical_service_continuity",
        "Responder access to critical and alert services during degraded/islanded operation",
        critical_continuity_rows,
        "success_rate_pct",
        success_rate(critical_continuity_rows),
    )

    degraded_attacker_rows = filter_rows(
        rows,
        phases={"DEGRADED"},
        actors=ATTACKER_ACTORS,
        services=CRITICAL_SERVICES,
    )
    island_unauthorized_rows = filter_rows(
        rows,
        phases=ISLAND_PHASES,
        actors=ISLAND_UNAUTHORIZED_ACTORS,
        services=CRITICAL_SERVICES,
    )
    unauthorized_rows = degraded_attacker_rows + island_unauthorized_rows
    add_kpi(
        "unauthorized_access_blocking",
        "Attackers remain blocked in degraded mode; all non-responders are blocked from critical/alert services in island mode",
        unauthorized_rows,
        "block_rate_pct",
        block_rate(unauthorized_rows),
    )

    island_restriction_rows = filter_rows(
        rows,
        phases=ISLAND_PHASES,
        actors=RESPONDER_ACTORS,
        services=RESTRICTED_SERVICES,
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
        services=CRITICAL_SERVICES,
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
        phases={"INTER_ISLAND_MESH", "INTER_ISLAND_FALLBACK"},
        actors={"zt_responder_i2"},
        services=CRITICAL_SERVICES,
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

    degraded_full_rows = filter_rows(
        rows,
        phases={"DEGRADED"},
        actors=RESPONDER_ACTORS,
        services=CRITICAL_SERVICES,
    )
    add_kpi(
        "degraded_full_access_continuity",
        "Responder full-tier critical/alert access in degraded mode",
        degraded_full_rows,
        "success_rate_pct",
        success_rate(degraded_full_rows),
    )

    degraded_limited_rows = filter_rows(
        rows,
        phases={"DEGRADED"},
        actors=DEGRADED_LIMITED_ACTORS,
        services=CRITICAL_SERVICES,
    )
    add_kpi(
        "degraded_limited_access_availability",
        "Civilian/sensor limited-tier critical/alert access in degraded mode; should succeed through rate-limited OVS meters",
        degraded_limited_rows,
        "success_rate_pct",
        success_rate(degraded_limited_rows),
    )
    add_kpi(
        "degraded_limited_access_latency_avg",
        "Average latency for successful limited-tier degraded critical/alert requests",
        degraded_limited_rows,
        "avg_success_latency_ms",
        avg_success_latency(degraded_limited_rows),
    )

    add_kpi(
        "degraded_attacker_blocking",
        "Attacker/unknown critical/alert access must remain blocked in degraded mode",
        degraded_attacker_rows,
        "block_rate_pct",
        block_rate(degraded_attacker_rows),
    )

    degraded_restricted_rows = filter_rows(
        rows,
        phases={"DEGRADED"},
        services=RESTRICTED_SERVICES,
    )
    add_kpi(
        "degraded_restricted_service_blocking",
        "Non-critical, external and central-control services are restricted during degraded mode",
        degraded_restricted_rows,
        "block_rate_pct",
        block_rate(degraded_restricted_rows),
    )

    degraded_rows = filter_rows(rows, phases={"DEGRADED"})
    degraded_pass_pct, degraded_pass_count, degraded_total = pass_rate(degraded_rows)
    kpi_rows.append({
        "kpi": "degraded_three_tier_policy_correctness",
        "description": "Requests matching the three-tier degraded policy: full, limited and deny",
        "requests": degraded_total,
        "metric_type": "pass_rate_pct",
        "value": f"{degraded_pass_pct:.2f}",
    })

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
            "INTER_ISLAND_FALLBACK",
            "NORMAL_RESTORED",
        },
        actors=RESPONDER_ACTORS,
        services=CRITICAL_SERVICES,
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
    degraded_limit_out = os.path.join(args.outdir, "integrated_degraded_limit_summary.csv")
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
        "p95_success_latency_ms",
        "max_latency_ms",
    ])

    write_csv(expectation_out, expectation_summary, [
        "phase",
        "actor",
        "service",
        "expected",
        "expected_tier",
        "total_requests",
        "success_count",
        "blocked_count",
        "pass_count",
        "scored_requests",
        "pass_rate_pct",
        "avg_success_latency_ms",
        "p95_success_latency_ms",
        "max_latency_ms",
    ])

    write_csv(degraded_limit_out, degraded_limit_summary, [
        "phase",
        "actor",
        "service",
        "expected",
        "expected_tier",
        "meter_expected",
        "total_requests",
        "success_count",
        "blocked_count",
        "pass_count",
        "scored_requests",
        "pass_rate_pct",
        "success_rate_pct",
        "block_rate_pct",
        "avg_success_latency_ms",
        "p95_success_latency_ms",
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
            f"{r['phase']:22s} "
            f"n={r['total_requests']:4d} "
            f"success={r['success_rate_pct']:>6s}% "
            f"blocked={r['block_rate_pct']:>6s}% "
            f"avg_latency={r['avg_success_latency_ms']:>7s} ms "
            f"p95={r['p95_success_latency_ms']:>7s} ms "
            f"duration={r['duration_s']:>7s}s"
        )

    print("")
    print("=== Degraded three-tier summary ===")
    for r in degraded_limit_summary:
        print(
            f"{r['actor']:24s} {r['service']:20s} "
            f"tier={r['expected_tier']:8s} "
            f"expected={r['expected']:7s} "
            f"pass={str(r['pass_rate_pct']):>6s}% "
            f"n={r['total_requests']}"
        )

    print("")
    print("=== KPI summary ===")
    for r in kpi_rows:
        print(
            f"{r['kpi']:42s} "
            f"{r['metric_type']:24s} "
            f"value={r['value']:>7s} "
            f"n={r['requests']}"
        )

    print("")
    print("[saved]", phase_out)
    print("[saved]", expectation_out)
    print("[saved]", degraded_limit_out)
    print("[saved]", kpi_out)


if __name__ == "__main__":
    main()
