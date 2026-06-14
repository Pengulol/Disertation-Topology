
import argparse
import csv
import json
import math
from datetime import datetime
from pathlib import Path


Q_LIST = [0.0, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50]


def read_text(path):
    p = Path(path)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def load_json(path):
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def dissimilarity(a, b):

    keys = sorted(set(a.keys()) | set(b.keys()))
    if not keys:
        return 0.0

    diff = 0
    for key in keys:
        if a.get(key) != b.get(key):
            diff += 1

    return diff / len(keys)


def indicator(dij, delta):
    return 1.0 if dij > delta else 0.0


def fss(elements, delta):

    active = [e for e in elements if e.get("active", True)]
    n = len(active)

    if n < 2:
        return 0.0

    total = n * (n - 1)
    acc = 0.0

    for i, ei in enumerate(active):
        for j, ej in enumerate(active):
            if i == j:
                continue

            dij = dissimilarity(ei["signature"], ej["signature"])
            acc += indicator(dij, delta)

    return acc / total


def fss_star_none_weight(elements, delta):

    active = [e for e in elements if e.get("active", True)]
    n = len(active)

    if n < 2:
        return 0.0

    total = n * (n - 1)
    acc = 0.0

    for i, ei in enumerate(active):
        for j, ej in enumerate(active):
            if i == j:
                continue

            dij = dissimilarity(ei["signature"], ej["signature"])
            acc += indicator(dij, delta) * dij

    return acc / total


def distinct_representatives(elements, delta):

    active = [e for e in elements if e.get("active", True)]
    reps = []

    for elem in active:
        if not reps:
            reps.append(elem)
            continue

        if all(dissimilarity(elem["signature"], r["signature"]) > delta for r in reps):
            reps.append(elem)

    return reps


def entropy(probabilities):
    h = 0.0
    for p in probabilities:
        if p <= 0:
            continue
        h -= p * math.log(p)
    return h


def layer_entropy(elements, all_functions):

    active = [e for e in elements if e.get("active", True)]

    if not active or not all_functions:
        return 0.0

    counts = []
    for fn in all_functions:
        count = sum(1 for e in active if fn in e.get("functions", []))
        counts.append(count)

    total = sum(counts)
    if total <= 0:
        return 0.0

    probs = [c / total for c in counts if c > 0]
    h = entropy(probs)

    if len(all_functions) <= 1:
        return 0.0

    return h / math.log(len(all_functions))


def mldi(layer_elements, delta):

    taus = []
    rows = []

    for layer, elements in layer_elements.items():
        total = len(elements)
        reps = distinct_representatives(elements, delta)
        tau = len(reps) / total if total else 0.0
        taus.append(tau)

        rows.append({
            "layer": layer,
            "total_elements": total,
            "admissible_distinct_elements": len(reps),
            "tau": tau,
        })

    value = sum(taus) / len(taus) if taus else 0.0
    return value, rows


def mldi_star(layer_elements):

    all_functions = sorted({
        fn
        for elements in layer_elements.values()
        for elem in elements
        for fn in elem.get("functions", [])
    })

    values = []
    rows = []

    for layer, elements in layer_elements.items():
        h_norm = layer_entropy(elements, all_functions)
        values.append(h_norm)

        rows.append({
            "layer": layer,
            "entropy_normalized": h_norm,
        })

    value = sum(values) / len(values) if values else 0.0
    return value, rows


def remove_top_fraction(elements, q):
    n = len(elements)
    remove_count = int(math.ceil(n * q))

    ranked = sorted(elements, key=lambda e: e.get("importance", 0.0), reverse=True)
    removed_names = {e["name"] for e in ranked[:remove_count]}

    new_elements = []
    for elem in elements:
        copied = dict(elem)
        if copied["name"] in removed_names:
            copied["active"] = False
        new_elements.append(copied)

    return new_elements, removed_names


def remove_top_fraction_layers(layer_elements, q):
    all_items = []

    for layer, elements in layer_elements.items():
        for elem in elements:
            all_items.append((layer, elem))

    remove_count = int(math.ceil(len(all_items) * q))
    ranked = sorted(all_items, key=lambda x: x[1].get("importance", 0.0), reverse=True)
    removed_names = {elem["name"] for _, elem in ranked[:remove_count]}

    new_layers = {}
    for layer, elements in layer_elements.items():
        new_layers[layer] = []
        for elem in elements:
            copied = dict(elem)
            if copied["name"] in removed_names:
                copied["active"] = False
            new_layers[layer].append(copied)

    return new_layers, removed_names


def build_models(audit, knowledge):

    has_mesh = "MESH,REPAIR" in audit
    has_trust = "quarantine-node" in audit and "ap5->ap3" in audit
    has_inter_island = "inter-island" in audit or "s6-s7-up" in audit
    has_policy_cache = "compiled-policy-cached" in audit
    has_watch = "WATCH" in audit or "entered-by-watch" in audit
    has_learning = bool(knowledge.get("paths", {}))

    function_sets = {
        "critical_service_support": [
            {
                "name": "primary_edge_path",
                "active": True,
                "importance": 0.95,
                "signature": {
                    "layer": "L1",
                    "mechanism": "primary_backhaul",
                    "control": "normal_l2",
                    "failure_domain": "core_backhaul",
                    "trust_mode": "default",
                },
            },
            {
                "name": "local_mec_critical_service",
                "active": True,
                "importance": 0.90,
                "signature": {
                    "layer": "L3",
                    "mechanism": "local_mec",
                    "control": "local_policy",
                    "failure_domain": "edge_compute",
                    "trust_mode": "allowlisted_critical",
                },
            },
            {
                "name": "ap_mesh_fallback",
                "active": has_mesh,
                "importance": 0.75,
                "signature": {
                    "layer": "L1",
                    "mechanism": "ap_mesh",
                    "control": "sdn_mesh_controller",
                    "failure_domain": "access_path",
                    "trust_mode": "local_repair",
                },
            },
            {
                "name": "trust_aware_mesh_fallback",
                "active": has_trust,
                "importance": 0.70,
                "signature": {
                    "layer": "L1",
                    "mechanism": "ap_mesh",
                    "control": "trust_aware_routing",
                    "failure_domain": "relay_trust",
                    "trust_mode": "quarantine_avoidance",
                },
            },
            {
                "name": "inter_island_fallback",
                "active": has_inter_island,
                "importance": 0.65,
                "signature": {
                    "layer": "L1",
                    "mechanism": "inter_island_link",
                    "control": "fallback_link_enablement",
                    "failure_domain": "island_boundary",
                    "trust_mode": "zt_extended",
                },
            },
        ],
        "zero_trust_policy_support": [
            {
                "name": "local_pdp",
                "active": True,
                "importance": 0.95,
                "signature": {
                    "layer": "L2",
                    "mechanism": "local_pdp",
                    "control": "policy_decision",
                    "failure_domain": "edge_control",
                    "trust_mode": "identity_policy",
                },
            },
            {
                "name": "policy_cache",
                "active": has_policy_cache,
                "importance": 0.85,
                "signature": {
                    "layer": "L2",
                    "mechanism": "compiled_policy_cache",
                    "control": "fallback_decision",
                    "failure_domain": "central_pdp_loss",
                    "trust_mode": "fail_closed",
                },
            },
            {
                "name": "ovs_pep_rules",
                "active": True,
                "importance": 0.90,
                "signature": {
                    "layer": "L2",
                    "mechanism": "ovs_flows",
                    "control": "policy_enforcement",
                    "failure_domain": "data_plane",
                    "trust_mode": "deny_by_default",
                },
            },
            {
                "name": "identity_cache",
                "active": True,
                "importance": 0.80,
                "signature": {
                    "layer": "L2",
                    "mechanism": "cached_identity",
                    "control": "local_identity_check",
                    "failure_domain": "central_identity_loss",
                    "trust_mode": "cached_identity",
                },
            },
        ],
        "recovery_orchestration_support": [
            {
                "name": "watch_agent",
                "active": has_watch,
                "importance": 0.80,
                "signature": {
                    "layer": "L2",
                    "mechanism": "monitoring_agent",
                    "control": "state_detection",
                    "failure_domain": "core_link",
                    "trust_mode": "state_driven",
                },
            },
            {
                "name": "edge_mode_controller",
                "active": True,
                "importance": 0.90,
                "signature": {
                    "layer": "L2",
                    "mechanism": "state_controller",
                    "control": "mode_transition",
                    "failure_domain": "policy_state",
                    "trust_mode": "zt_state_machine",
                },
            },
            {
                "name": "sdn_mesh_controller",
                "active": has_mesh,
                "importance": 0.75,
                "signature": {
                    "layer": "L2",
                    "mechanism": "sdn_mesh",
                    "control": "path_repair",
                    "failure_domain": "access_path",
                    "trust_mode": "local_repair",
                },
            },
            {
                "name": "outage_learning_agent",
                "active": has_learning,
                "importance": 0.55,
                "signature": {
                    "layer": "L2",
                    "mechanism": "learning_feedback",
                    "control": "cost_adjustment",
                    "failure_domain": "repeated_outage",
                    "trust_mode": "evidence_based",
                },
            },
        ],
    }

    layer_elements = {
        "L1_connectivity": [
            {
                "name": "core_backhaul",
                "active": True,
                "importance": 0.95,
                "functions": ["normal_connectivity", "recovery"],
                "signature": {"type": "wired_core", "domain": "core", "controller": "normal_l2"},
            },
            {
                "name": "primary_access_paths",
                "active": True,
                "importance": 0.85,
                "functions": ["normal_connectivity", "critical_service"],
                "signature": {"type": "access_backhaul", "domain": "edge", "controller": "normal_l2"},
            },
            {
                "name": "ap_mesh_fallback",
                "active": has_mesh,
                "importance": 0.75,
                "functions": ["critical_service", "mesh_recovery"],
                "signature": {"type": "wireless_mesh", "domain": "edge", "controller": "sdn_mesh"},
            },
            {
                "name": "trust_aware_mesh_path",
                "active": has_trust,
                "importance": 0.70,
                "functions": ["critical_service", "mesh_recovery", "trust_assurance"],
                "signature": {"type": "wireless_mesh", "domain": "edge", "controller": "trust_aware_sdn"},
            },
            {
                "name": "inter_island_link",
                "active": has_inter_island,
                "importance": 0.65,
                "functions": ["critical_service", "inter_island"],
                "signature": {"type": "fallback_link", "domain": "inter_island", "controller": "sdn_mesh"},
            },
        ],
        "L2_control_security": [
            {
                "name": "local_pdp",
                "active": True,
                "importance": 0.95,
                "functions": ["identity", "policy", "critical_service"],
                "signature": {"type": "pdp", "domain": "edge", "mode": "local"},
            },
            {
                "name": "compiled_policy_cache",
                "active": has_policy_cache,
                "importance": 0.85,
                "functions": ["policy", "recovery"],
                "signature": {"type": "cache", "domain": "edge", "mode": "fail_closed"},
            },
            {
                "name": "ovs_pep",
                "active": True,
                "importance": 0.90,
                "functions": ["policy", "access_control", "trust_assurance"],
                "signature": {"type": "pep", "domain": "data_plane", "mode": "ovs"},
            },
            {
                "name": "watch_agent",
                "active": has_watch,
                "importance": 0.75,
                "functions": ["recovery", "state_detection"],
                "signature": {"type": "monitor", "domain": "edge", "mode": "state_watch"},
            },
            {
                "name": "mesh_controller",
                "active": has_mesh,
                "importance": 0.75,
                "functions": ["mesh_recovery", "trust_assurance"],
                "signature": {"type": "controller", "domain": "edge", "mode": "mesh_repair"},
            },
        ],
        "L3_service_application": [
            {
                "name": "critical_service",
                "active": True,
                "importance": 0.95,
                "functions": ["critical_service"],
                "signature": {"type": "mec_service", "class": "critical", "exposure": "allowlisted"},
            },
            {
                "name": "alert_service",
                "active": True,
                "importance": 0.90,
                "functions": ["critical_service"],
                "signature": {"type": "mec_service", "class": "critical_alert", "exposure": "allowlisted"},
            },
            {
                "name": "noncritical_service_blocking",
                "active": True,
                "importance": 0.65,
                "functions": ["graceful_degradation", "access_control"],
                "signature": {"type": "policy_behavior", "class": "noncritical", "exposure": "blocked_in_island"},
            },
            {
                "name": "central_control_blocking",
                "active": True,
                "importance": 0.65,
                "functions": ["graceful_degradation", "identity"],
                "signature": {"type": "policy_behavior", "class": "central_control", "exposure": "blocked_in_island"},
            },
            {
                "name": "inter_island_responder_service",
                "active": has_inter_island,
                "importance": 0.60,
                "functions": ["critical_service", "inter_island"],
                "signature": {"type": "mec_service_access", "class": "critical", "exposure": "second_island"},
            },
        ],
    }

    return function_sets, layer_elements


def write_csv(path, fieldnames, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(
        description="Paper-faithful degeneracy assessment for Zero-Trust Island Mode."
    )
    parser.add_argument("--kpi", default="/mnt/shared/results/integrated_kpi_summary.csv")
    parser.add_argument("--audit", default="/tmp/island_audit.log")
    parser.add_argument("--knowledge", default="/mnt/shared/island_mode/runtime/outage_knowledge.json")
    parser.add_argument("--outdir", default="/mnt/shared/results")
    parser.add_argument("--delta", type=float, default=0.5)
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    audit = read_text(args.audit)
    knowledge = load_json(args.knowledge)

    function_sets, layer_elements = build_models(audit, knowledge)

    fss_rows = []
    for fn, elements in function_sets.items():
        active = sum(1 for e in elements if e.get("active", True))
        n = len(elements)
        fss_value = fss(elements, args.delta)
        fss_star_value = fss_star_none_weight(elements, args.delta)

        fss_rows.append({
            "function": fn,
            "active_elements": active,
            "total_elements": n,
            "FSS": round(fss_value, 4),
            "FSS_percent": round(fss_value * 100, 2),
            "FSS_star_none_weight": round(fss_star_value, 4),
            "FSS_star_none_weight_percent": round(fss_star_value * 100, 2),
        })

    mldi_value, mldi_layer_rows = mldi(layer_elements, args.delta)
    mldi_star_value, entropy_layer_rows = mldi_star(layer_elements)
    entropy_by_layer = {r["layer"]: r["entropy_normalized"] for r in entropy_layer_rows}

    layer_rows = []
    for row in mldi_layer_rows:
        h = entropy_by_layer.get(row["layer"], 0.0)
        layer_rows.append({
            "layer": row["layer"],
            "total_elements": row["total_elements"],
            "admissible_distinct_elements": row["admissible_distinct_elements"],
            "tau": round(row["tau"], 4),
            "tau_percent": round(row["tau"] * 100, 2),
            "entropy_normalized": round(h, 4),
            "entropy_percent": round(h * 100, 2),
        })

    summary_rows = [
        {
            "metric": "MLDI",
            "value": round(mldi_value, 4),
            "percent": round(mldi_value * 100, 2),
            "definition": "mean layer-wise degeneracy ratio tau_l = |D_l| / |E_l|",
        },
        {
            "metric": "MLDI_star",
            "value": round(mldi_star_value, 4),
            "percent": round(mldi_star_value * 100, 2),
            "definition": "mean normalized layer entropy H(l) / log(m)",
        },
    ]

    removal_rows = []
    for q in Q_LIST:
        for fn, elements in function_sets.items():
            removed_elements, removed = remove_top_fraction(elements, q)
            removal_rows.append({
                "removal_fraction_q": q,
                "scope": fn,
                "removed_elements": ";".join(sorted(removed)),
                "FSS": round(fss(removed_elements, args.delta), 4),
                "FSS_star_none_weight": round(fss_star_none_weight(removed_elements, args.delta), 4),
                "MLDI": "",
                "MLDI_star": "",
            })

        removed_layers, removed = remove_top_fraction_layers(layer_elements, q)
        mldi_q, _ = mldi(removed_layers, args.delta)
        mldi_star_q, _ = mldi_star(removed_layers)
        removal_rows.append({
            "removal_fraction_q": q,
            "scope": "cross_layer",
            "removed_elements": ";".join(sorted(removed)),
            "FSS": "",
            "FSS_star_none_weight": "",
            "MLDI": round(mldi_q, 4),
            "MLDI_star": round(mldi_star_q, 4),
        })

    fss_path = outdir / "paper_fss_by_function.csv"
    layer_path = outdir / "paper_mldi_by_layer.csv"
    summary_path = outdir / "paper_degeneracy_summary.csv"
    removal_path = outdir / "paper_targeted_removal_curve.csv"
    report_path = outdir / "paper_degeneracy_report.json"

    write_csv(fss_path, [
        "function",
        "active_elements",
        "total_elements",
        "FSS",
        "FSS_percent",
        "FSS_star_none_weight",
        "FSS_star_none_weight_percent",
    ], fss_rows)

    write_csv(layer_path, [
        "layer",
        "total_elements",
        "admissible_distinct_elements",
        "tau",
        "tau_percent",
        "entropy_normalized",
        "entropy_percent",
    ], layer_rows)

    write_csv(summary_path, [
        "metric",
        "value",
        "percent",
        "definition",
    ], summary_rows)

    write_csv(removal_path, [
        "removal_fraction_q",
        "scope",
        "removed_elements",
        "FSS",
        "FSS_star_none_weight",
        "MLDI",
        "MLDI_star",
    ], removal_rows)

    report = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "model": "paper-faithful degeneracy assessment",
        "scope": "Zero-Trust Island Mode for 6G Edge",
        "delta": args.delta,
        "implemented_metrics": [
            "FSS",
            "FSS_star with None node weighting, C_i=1, L_i=0, w_i=1",
            "MLDI",
            "MLDI_star",
            "targeted removals",
        ],
        "out_of_scope": {
            "ARQ": "not computed because the prototype does not evaluate multiple alternative algorithm implementations for the same task"
        },
        "source_files": {
            "audit": str(args.audit),
            "knowledge": str(args.knowledge),
            "kpi_argument_accepted_for_workflow_compatibility": str(args.kpi),
        },
        "fss_by_function": fss_rows,
        "mldi_summary": summary_rows,
        "mldi_by_layer": layer_rows,
        "targeted_removal_curve": removal_rows,
    }

    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("=== Paper-faithful degeneracy assessment ===")
    print("\nFSS / FSS* by function:")
    for row in fss_rows:
        print(
            f"{row['function']:<32} "
            f"FSS={row['FSS']:.4f} "
            f"FSS*={row['FSS_star_none_weight']:.4f}"
        )

    print("\nMLDI:")
    print(f"MLDI      = {mldi_value:.4f}")
    print(f"MLDI_star = {mldi_star_value:.4f}")

    print("\n[saved]", fss_path)
    print("[saved]", layer_path)
    print("[saved]", summary_path)
    print("[saved]", removal_path)
    print("[saved]", report_path)


if __name__ == "__main__":
    main()
