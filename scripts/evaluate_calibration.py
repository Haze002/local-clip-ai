from __future__ import annotations

import argparse
import json
from pathlib import Path

from local_clip_ai.calibration import evaluate_manifest, load_manifest
from local_clip_ai.paths import AppPaths
from local_clip_ai.storage import JobDatabase


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path(".local-data"))
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("tests/calibration/twitch_known_moments.json"),
    )
    parser.add_argument(
        "--job",
        action="append",
        default=[],
        metavar="VIDEO_ID=JOB_ID",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    job_ids = dict(value.split("=", 1) for value in arguments.job)
    database = JobDatabase(AppPaths.from_root(arguments.data_dir).database)
    report = evaluate_manifest(
        database,
        load_manifest(arguments.manifest),
        job_ids,
    )
    output = json.dumps(report, indent=2) + "\n"
    print(output, end="")
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(output, encoding="utf-8")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
