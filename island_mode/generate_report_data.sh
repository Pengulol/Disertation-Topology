#!/bin/bash

set -u



MODE="benchmark"
METRICS="/mnt/shared/results/integrated_metrics.csv"
BASE="/mnt/shared/results/demo_run"
OUTDIR=""
AUDIT="/tmp/island_audit.log"

while [ $# -gt 0 ]; do
    case "$1" in
        --mode)
            MODE="$2"
            shift 2
            ;;
        --metrics)
            METRICS="$2"
            shift 2
            ;;
        --base)
            BASE="$2"
            shift 2
            ;;
        --outdir)
            OUTDIR="$2"
            shift 2
            ;;
        --audit)
            AUDIT="$2"
            shift 2
            ;;
        *)
            echo "[report] unknown argument: $1"
            exit 2
            ;;
    esac
done

ISLAND_DIR="/mnt/shared/island_mode"
DEMO_DIR="/mnt/shared/demo"

RUNTIME_DIR="$ISLAND_DIR/runtime"

KNOWLEDGE="$RUNTIME_DIR/outage_knowledge.json"
HISTORY="$RUNTIME_DIR/path_history.json"
SHADOW_PLAN="$RUNTIME_DIR/shadow_repair_plan.json"
MESH_TRUST="$RUNTIME_DIR/mesh_trust_state.json"

run() {
    echo "+ $*"
    "$@"
    rc=$?

    if [ "$rc" -ne 0 ]; then
        echo "[report][warn] command failed rc=$rc: $*" >&2
    fi

    return 0
}

echo "=== Generate Zero-Trust Island Mode report data ==="
echo "[report] mode=$MODE"

if [ "$MODE" = "benchmark" ]; then
    if [ -z "$OUTDIR" ]; then
        OUTDIR="/mnt/shared/results"
    fi

    mkdir -p "$OUTDIR"

    echo "[report] metrics=$METRICS"
    echo "[report] outdir=$OUTDIR"
    echo "[report] audit=$AUDIT"

    if [ ! -f "$METRICS" ]; then
        echo "[report][error] missing metrics file: $METRICS"
        exit 1
    fi

    echo ""
    echo "=== Metric analysis ==="
    run python3 "$ISLAND_DIR/analyze_integrated_metrics.py" \
        --input "$METRICS" \
        --outdir "$OUTDIR"

    run python3 "$ISLAND_DIR/analyze_latency.py" \
        --input "$METRICS" \
        --outdir "$OUTDIR"

    echo ""
    echo "=== Update outage learning knowledge ==="
    run python3 "$ISLAND_DIR/outage_learning_agent.py" \
        update \
        --metrics "$METRICS"

    KPI="$OUTDIR/integrated_kpi_summary.csv"
    AUDIT_INPUT="$AUDIT"

elif [ "$MODE" = "demo" ]; then
    if [ -z "$OUTDIR" ]; then
        OUTDIR="$BASE"
    fi

    mkdir -p "$OUTDIR"

    echo "[report] base=$BASE"
    echo "[report] outdir=$OUTDIR"

    echo ""
    echo "=== Demo aggregation ==="
    run python3 "$DEMO_DIR/aggregate_demo_results.py" \
        --base "$BASE" \
        --outdir "$OUTDIR"

    KPI="$OUTDIR/demo_kpi_aggregate.csv"

    if [ ! -f "$KPI" ]; then
        echo "[report][error] missing demo KPI aggregate: $KPI"
        exit 1
    fi

    AUDIT_INPUT="$OUTDIR/demo_combined_audit.log"

    echo ""
    echo "=== Combine demo audit logs ==="
    rm -f "$AUDIT_INPUT"
    touch "$AUDIT_INPUT"

    for f in "$BASE"/pass*/island_audit.log; do
        if [ -f "$f" ]; then
            echo "" >> "$AUDIT_INPUT"
            echo "### $f ###" >> "$AUDIT_INPUT"
            cat "$f" >> "$AUDIT_INPUT"
        fi
    done

    if [ ! -s "$AUDIT_INPUT" ] && [ -f "/tmp/island_audit.log" ]; then
        cat /tmp/island_audit.log > "$AUDIT_INPUT"
    fi

    echo "[report] combined audit saved: $AUDIT_INPUT"

else
    echo "[report][error] invalid mode: $MODE"
    exit 2
fi

echo ""
echo "=== DLiSA-inspired adaptation knowledge report ==="
run python3 "$ISLAND_DIR/adaptation_knowledge_report.py" \
    --knowledge "$KNOWLEDGE" \
    --history "$HISTORY" \
    --shadow-plan "$SHADOW_PLAN" \
    --audit "$AUDIT_INPUT" \
    --outdir "$OUTDIR"

echo ""
echo "=== Hexa-X-II / LoTAF-inspired trust assessment ==="
run python3 "$ISLAND_DIR/lotaf_report.py" \
    --kpi "$KPI" \
    --audit "$AUDIT_INPUT" \
    --mesh-trust "$MESH_TRUST" \
    --knowledge "$KNOWLEDGE" \
    --outdir "$OUTDIR"

echo ""
echo "=== Degeneracy-aware resilience report ==="
run python3 "$ISLAND_DIR/degeneracy_report.py" \
    --kpi "$KPI" \
    --audit "$AUDIT_INPUT" \
    --knowledge "$KNOWLEDGE" \
    --outdir "$OUTDIR"

echo ""
echo "=== Final report file list ==="
find "$OUTDIR" -maxdepth 1 -type f | sort > "$OUTDIR/final_report_files.txt"
cat "$OUTDIR/final_report_files.txt"

echo ""
echo "[report] saved file list: $OUTDIR/final_report_files.txt"
echo "=== End report data generation ==="
