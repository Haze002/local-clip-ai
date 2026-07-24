from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from local_clip_ai import __version__
from local_clip_ai.diagnostics import collect_diagnostics
from local_clip_ai.diagnostics.models import CheckStatus, DiagnosticReport
from local_clip_ai.paths import AppPaths
from local_clip_ai.storage import JobDatabase


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-clip-ai",
        description="Local Clip AI development and diagnostics utility.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Override the runtime data directory.",
    )
    subparsers = parser.add_subparsers(dest="command")

    diagnose = subparsers.add_parser("diagnose", help="Probe this PC and required tools.")
    diagnose.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    diagnose.add_argument(
        "--strict",
        action="store_true",
        help="Return a non-zero exit code when a required check fails.",
    )

    subparsers.add_parser("init-db", help="Initialize the durable local job database.")

    add_job = subparsers.add_parser("add-job", help="Add a source VOD to the development queue.")
    add_job.add_argument("source")
    add_job.add_argument(
        "--mode",
        choices=("quick", "balanced", "deep"),
        default="balanced",
    )

    subparsers.add_parser("jobs", help="List jobs in queue order.")
    return parser


def _print_report(report: DiagnosticReport) -> None:
    print(f"Local Clip AI diagnostics: {report.overall_status.value.upper()}")
    print()
    for check in report.checks:
        marker = {
            CheckStatus.PASS: "PASS",
            CheckStatus.WARN: "WARN",
            CheckStatus.FAIL: "FAIL",
        }[check.status]
        print(f"[{marker}] {check.name}: {check.summary}")
    print()
    print(f"Completed in {report.duration_seconds:.2f} seconds")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    command = arguments.command or "diagnose"
    paths = AppPaths.default(arguments.data_dir)

    if command == "diagnose":
        report = collect_diagnostics(paths)
        if getattr(arguments, "json", False):
            print(report.to_json())
        else:
            _print_report(report)
        if getattr(arguments, "strict", False) and report.overall_status is CheckStatus.FAIL:
            return 1
        return 0

    database = JobDatabase(paths.database)
    database.initialize()

    if command == "init-db":
        print(f"Initialized schema {database.schema_version()} at {paths.database}")
        return 0

    if command == "add-job":
        job_id = database.create_job(arguments.source, analysis_mode=arguments.mode)
        print(f"Queued {job_id}")
        return 0

    if command == "jobs":
        print(json.dumps(database.list_jobs(), indent=2))
        return 0

    parser.error(f"Unsupported command: {command}")
    return 2
