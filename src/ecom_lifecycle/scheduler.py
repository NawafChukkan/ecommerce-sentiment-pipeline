from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime

from .config import load_settings


def parse_args() -> argparse.Namespace:
    settings = load_settings()
    parser = argparse.ArgumentParser(description="Run scheduled pipeline refresh cycles.")
    parser.add_argument("--interval-minutes", type=int, default=settings.refresh_interval_minutes)
    parser.add_argument("--profile", default=settings.refresh_profile)
    parser.add_argument("--local-only", action="store_true", default=settings.refresh_local_only)
    parser.add_argument("--replace", action="store_true", default=True)
    return parser.parse_args()


def run_command(args: list[str]) -> None:
    print(f"[{datetime.utcnow().isoformat()}] Running: {' '.join(args)}")
    subprocess.run(args, check=True)


def main() -> None:
    args = parse_args()
    base_cmd = [sys.executable, "-m"]
    seed_cmd = base_cmd + ["src.ecom_lifecycle.generate_seed", "--profile", args.profile]
    pipeline_cmd = base_cmd + ["src.ecom_lifecycle.spark.jobs.pipeline"]

    if args.replace:
        seed_cmd.append("--replace")
        pipeline_cmd.append("--replace-output")
    if args.local_only:
        seed_cmd.append("--local-only")
        pipeline_cmd.append("--local-only")

    while True:
        run_command(seed_cmd)
        run_command(pipeline_cmd)
        print(f"[{datetime.utcnow().isoformat()}] Refresh complete. Sleeping {args.interval_minutes} minutes.")
        time.sleep(max(args.interval_minutes, 1) * 60)


if __name__ == "__main__":
    main()
