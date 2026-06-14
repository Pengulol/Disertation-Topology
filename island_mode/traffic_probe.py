#!/usr/bin/env python3
import argparse
import csv
import os
import subprocess
import time


def read_phase(path):
    try:
        with open(path, "r") as f:
            return f.read().strip() or "UNKNOWN"
    except FileNotFoundError:
        return "UNKNOWN"


def get_start_time(path):
    try:
        with open(path, "r") as f:
            return float(f.read().strip())
    except Exception:
        start = time.time()
        try:
            with open(path, "w") as f:
                f.write(str(start))
        except Exception:
            pass
        return start


def ensure_header(path):
    if not os.path.exists(path):
        with open(path, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "t_rel_s",
                "phase",
                "actor",
                "service",
                "url",
                "result",
                "http_code",
                "latency_ms",
                "error"
            ])


def write_row(path, row):
    with open(path, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(row)


def fmt_timeout(value):
    value = float(value)
    if value.is_integer():
        return str(int(value))
    return f"{value:g}"


def clean_error(text):
    return (text or "").replace("\n", " | ").replace("\r", " ").strip()


def probe(url, timeout):
    start = time.time()

    connect_timeout = fmt_timeout(timeout)
    max_time = fmt_timeout(float(timeout) + 1)

    cmd = [
        "curl",
        "-sS",
        "-o", "/dev/null",
        "-w", "%{http_code}",
        "--connect-timeout", connect_timeout,
        "--max-time", max_time,
        url
    ]

    try:
        p = subprocess.run(cmd, capture_output=True, text=True)
        latency_ms = int((time.time() - start) * 1000)
        http_code = (p.stdout or "").strip()

        if p.returncode == 0 and http_code.startswith(("2", "3")):
            return "success", http_code, latency_ms, ""

        return "blocked", http_code or "000", latency_ms, clean_error(p.stderr)

    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        return "error", "000", latency_ms, str(e)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--actor", required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", default="/mnt/shared/results/integrated_metrics.csv")
    parser.add_argument("--phase-file", default="/tmp/island_phase")
    parser.add_argument("--start-file", default="/tmp/traffic_probe_start")
    parser.add_argument("--stop-file", default="/tmp/traffic_probe.stop")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=2.0)
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    ensure_header(args.out)

    global_start = get_start_time(args.start_file)

    while not os.path.exists(args.stop_file):
        phase = read_phase(args.phase_file)
        result, http_code, latency_ms, error = probe(args.url, args.timeout)

        t_rel = time.time() - global_start

        write_row(args.out, [
            f"{t_rel:.3f}",
            phase,
            args.actor,
            args.service,
            args.url,
            result,
            http_code,
            latency_ms,
            error
        ])

        time.sleep(args.interval)


if __name__ == "__main__":
    main()
