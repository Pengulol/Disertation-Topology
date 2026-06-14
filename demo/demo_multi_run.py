import os
import subprocess
import time
from pathlib import Path

BASE_RESULTS = Path("/mnt/shared/results/demo_run")
DRIVER = Path("/mnt/shared/demo/demo_random_driver.py")
KNOWLEDGE = Path("/mnt/shared/island_mode/outage_knowledge.json")

RUNS = int(os.environ.get("DEMO_RUNS", "3"))


def sh(cmd: str) -> int:
    print(f"+ {cmd}")
    return subprocess.run(cmd, shell=True, text=True).returncode


def run_one_pass(index: int) -> None:
    seed = int(time.time()) + index * 97
    pass_dir = BASE_RESULTS / f"pass{index}"

    print("")
    print(f"=== DEMO PASS {index}/{RUNS} ===")
    print(f"[demo] seed={seed}")
    print(f"[demo] output={pass_dir}")

    os.environ["DEMO_SEED"] = str(seed)
    os.environ["DEMO_RESULTS_DIR"] = str(pass_dir)

    # Run one dynamic demo pass inside the current Containernet Python context.
    ns = dict(globals(), net=net)
    exec(DRIVER.read_text(), ns)

    sh(f"cp /tmp/island_audit.log {pass_dir / 'island_audit.log'} 2>/dev/null || true")
    sh(f"cp /tmp/island_topology_events.log {pass_dir / 'island_topology_events.log'} 2>/dev/null || true")

    metrics = pass_dir / "demo_metrics.csv"

    print("")
    print(f"[demo pass {index}] Analyze metrics")
    sh(
        f"python3 /mnt/shared/island_mode/analyze_integrated_metrics.py "
        f"--input {metrics} --outdir {pass_dir}"
    )
    sh(
        f"python3 /mnt/shared/island_mode/analyze_latency.py "
        f"--input {metrics} --outdir {pass_dir}"
    )

    print("")
    print(f"[demo pass {index}] Update outage learning")
    sh(
        f"python3 /mnt/shared/island_mode/outage_learning_agent.py "
        f"update --metrics {metrics}"
    )

    print("")
    print(f"[demo pass {index}] Build adaptation knowledge report")
    sh(
        f"python3 /mnt/shared/island_mode/adaptation_knowledge_report.py "
        f"--outdir {pass_dir}"
    )

    print("")
    print(f"[demo pass {index}] Current learned knowledge")
    sh(f"cat {KNOWLEDGE}")

    print("")
    print(f"[demo pass {index}] Last demo events")
    sh(f"tail -60 {pass_dir / 'demo_events.log'}")


print("=== Dynamic island-mode demo with repeated learning ===")
print(f"[demo] runs={RUNS}")
print("[demo] Each pass uses a different random seed.")
print("[demo] After every pass, outage learning is updated and used by the next pass.")

BASE_RESULTS.mkdir(parents=True, exist_ok=True)

for i in range(1, RUNS + 1):
    run_one_pass(i)

print("")
print("=== Final outage knowledge ===")
sh(f"cat {KNOWLEDGE}")

print("")
print("=== Generate final report data ===")
sh(
    "bash /mnt/shared/island_mode/generate_report_data.sh "
    "--mode demo "
    "--base /mnt/shared/results/demo_run "
    "--outdir /mnt/shared/results/demo_run"
)


print("")
print("=== End dynamic island-mode repeated demo ===")
