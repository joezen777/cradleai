#!/usr/bin/env python3
"""Wait for/resume clip analysis, then run the Pegasus chapter pipeline."""

import argparse
import os
import subprocess
import time
from pathlib import Path

from build_pegasus_chapters import individual_run_complete
from build_pegasus_metadata import DEFAULT_METADATA, load_scenes


ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / ".venv" / "bin" / "python"
INDIVIDUAL_RESULTS = ROOT / "output" / "pegasus_metadata.jsonl"


def wait_for_pid(pid: int, poll_seconds: float) -> None:
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(poll_seconds)


def run_until_complete(
    command: list[str],
    completion_check,
    cooldown_seconds: float,
) -> None:
    while not completion_check():
        result = subprocess.run(command, cwd=ROOT)
        if result.returncode == 0 and completion_check():
            return
        if result.returncode not in {0, 2}:
            raise RuntimeError(
                f"Command failed with exit code {result.returncode}: {command}"
            )
        print(
            f"Temporary stop; retrying in {cooldown_seconds:.0f} seconds.",
            flush=True,
        )
        time.sleep(cooldown_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait-pid", type=int)
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--cooldown-seconds", type=float, default=300.0)
    args = parser.parse_args()

    total_scenes = len(load_scenes(DEFAULT_METADATA))
    complete = lambda: individual_run_complete(
        INDIVIDUAL_RESULTS,
        total_scenes,
    )

    if args.wait_pid:
        print(
            f"Waiting for active individual run PID {args.wait_pid}.",
            flush=True,
        )
        wait_for_pid(args.wait_pid, args.poll_seconds)

    run_until_complete(
        [str(PYTHON), str(ROOT / "build_pegasus_metadata.py")],
        complete,
        args.cooldown_seconds,
    )

    # Chapter script is independently resumable. Exit code 2 represents a
    # temporary API/provider failure and is safe to retry after cooldown.
    while True:
        result = subprocess.run(
            [str(PYTHON), str(ROOT / "build_pegasus_chapters.py")],
            cwd=ROOT,
        )
        if result.returncode == 0:
            return 0
        if result.returncode != 2:
            raise RuntimeError(
                f"Chapter pipeline failed with exit code {result.returncode}"
            )
        print(
            f"Chapter API stopped temporarily; retrying in "
            f"{args.cooldown_seconds:.0f} seconds.",
            flush=True,
        )
        time.sleep(args.cooldown_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
