from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from local_clip_ai import __version__
from local_clip_ai.analysis import transcribe_media
from local_clip_ai.analysis.condensation import CondensedSpan
from local_clip_ai.config import (
    ContentProfile,
    default_analysis_profile,
    default_content_profile,
)
from local_clip_ai.diagnostics import collect_diagnostics
from local_clip_ai.diagnostics.models import CheckStatus, DiagnosticReport
from local_clip_ai.media import TimeRange, export_condensed_clip, parse_timecode
from local_clip_ai.paths import AppPaths
from local_clip_ai.pipeline import PipelineRunner
from local_clip_ai.sources import (
    acquire_twitch_section,
    inspect_twitch_vod,
    parse_twitch_vod_url,
)
from local_clip_ai.storage import JobDatabase
from local_clip_ai.tools import install_portable_tools

UNICODE_SMOKE_TEXT = "Local Clip AI Unicode smoke: naïve café — 日本語 下"


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

    install_tools = subparsers.add_parser(
        "install-tools",
        help="Download verified portable FFmpeg and yt-dlp into the runtime directory.",
    )
    install_tools.add_argument("--force", action="store_true", help="Reinstall existing tools.")

    vod_info = subparsers.add_parser("vod-info", help="Inspect a public Twitch VOD.")
    vod_info.add_argument("url")

    download_section = subparsers.add_parser(
        "download-section",
        help="Download and validate one Twitch VOD timestamp range.",
    )
    download_section.add_argument("url")
    download_section.add_argument("start", help="Start timecode, for example 01:27:00.")
    download_section.add_argument("end", help="End timecode, for example 01:29:30.")
    download_section.add_argument("--audio-only", action="store_true")

    transcribe = subparsers.add_parser(
        "transcribe",
        help="Transcribe a local media file with the selected local analysis profile.",
    )
    transcribe.add_argument("media", type=Path)
    transcribe.add_argument(
        "--mode",
        choices=("quick", "balanced", "deep"),
        default="quick",
    )
    transcribe.add_argument("--language", default="auto")
    transcribe.add_argument("--source-offset", type=float, default=0)
    transcribe.add_argument("--output", type=Path)
    transcribe.add_argument("--clip-start", type=float)
    transcribe.add_argument("--clip-end", type=float)

    export = subparsers.add_parser(
        "export-spans",
        help="Assemble chronological source spans into a shorter MP4.",
    )
    export.add_argument("source", type=Path)
    export.add_argument("output", type=Path)
    export.add_argument(
        "--span",
        nargs=2,
        action="append",
        metavar=("START", "END"),
        required=True,
    )
    export.add_argument("--source-offset", type=float, default=0)
    export.add_argument("--overwrite", action="store_true")

    add_job = subparsers.add_parser("add-job", help="Add a source VOD to the development queue.")
    add_job.add_argument("source")
    add_job.add_argument(
        "--mode",
        choices=("quick", "balanced", "deep"),
        default="balanced",
    )

    subparsers.add_parser("jobs", help="List jobs in queue order.")
    run_job = subparsers.add_parser("run-job", help="Run one queued or interrupted job.")
    run_job.add_argument("job_id")
    rebuild_candidates = subparsers.add_parser(
        "rebuild-candidates",
        help="Rerun local ranking and condensation without repeating earlier stages.",
    )
    rebuild_candidates.add_argument("job_id")
    rebuild_candidates.add_argument("--max-candidates", type=int)
    subparsers.add_parser("run-queue", help="Run all queued or interrupted jobs.")
    subparsers.add_parser("_unicode-smoke", help=argparse.SUPPRESS)
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
    from local_clip_ai.frozen_entry import configure_utf8_standard_streams

    configure_utf8_standard_streams()
    parser = _parser()
    arguments = parser.parse_args(argv)
    command = arguments.command or "diagnose"
    paths = AppPaths.default(arguments.data_dir)

    if command == "_unicode-smoke":
        print(UNICODE_SMOKE_TEXT)
        return 0

    if command == "diagnose":
        report = collect_diagnostics(paths)
        if getattr(arguments, "json", False):
            print(report.to_json())
        else:
            _print_report(report)
        if getattr(arguments, "strict", False) and report.overall_status is CheckStatus.FAIL:
            return 1
        return 0

    if command == "install-tools":
        for install in install_portable_tools(paths, force=arguments.force):
            print(
                f"Installed {install.name} ({install.release}, "
                f"sha256:{install.sha256[:12]}...)"
            )
        return 0

    if command == "vod-info":
        print(json.dumps(inspect_twitch_vod(paths, arguments.url).to_dict(), indent=2))
        return 0

    if command == "download-section":
        source_range = TimeRange(parse_timecode(arguments.start), parse_timecode(arguments.end))
        section = acquire_twitch_section(
            paths,
            arguments.url,
            source_range,
            audio_only=arguments.audio_only,
            on_output=print,
        )
        print(
            json.dumps(
                {
                    "video_id": section.video_id,
                    "path": str(section.path),
                    "duration_seconds": section.probe.duration_seconds,
                    "size_bytes": section.probe.size_bytes,
                    "video_codec": section.probe.video_codec,
                    "audio_codec": section.probe.audio_codec,
                },
                indent=2,
            )
        )
        return 0

    if command == "transcribe":
        profile = default_analysis_profile(arguments.mode)
        clip_range = None
        if arguments.clip_start is not None or arguments.clip_end is not None:
            if arguments.clip_start is None or arguments.clip_end is None:
                parser.error("--clip-start and --clip-end must be provided together")
            clip_range = TimeRange(arguments.clip_start, arguments.clip_end)
        transcript = transcribe_media(
            paths,
            arguments.media,
            profile,
            language=arguments.language,
            source_offset_seconds=arguments.source_offset,
            clip_range=clip_range,
            on_segment=lambda segment: print(
                f"[{segment.start_seconds:.2f}-{segment.end_seconds:.2f}] {segment.text}"
            ),
        )
        destination = arguments.output or (
            paths.root / "transcripts" / f"{arguments.media.stem}_{arguments.mode}.json"
        )
        transcript.save(destination)
        print(
            f"Saved {len(transcript.segments)} segments ({transcript.language}, "
            f"{transcript.device}/{transcript.compute_type}) to {destination.resolve()}"
        )
        return 0

    if command == "export-spans":
        spans = [
            CondensedSpan(
                parse_timecode(start),
                parse_timecode(end),
                1,
                "Manual export span",
            )
            for start, end in arguments.span
        ]
        result = export_condensed_clip(
            paths,
            arguments.source,
            spans,
            arguments.output,
            source_offset_seconds=arguments.source_offset,
            overwrite=arguments.overwrite,
        )
        print(
            f"Exported {result.probe.duration_seconds:.2f}s with {result.encoder} "
            f"to {result.path}"
        )
        return 0

    database = JobDatabase(paths.database)
    database.initialize()

    if command == "init-db":
        print(f"Initialized schema {database.schema_version()} at {paths.database}")
        return 0

    if command == "add-job":
        source = arguments.source
        source_kind = "file"
        if source.lower().startswith(("https://twitch.tv/", "https://www.twitch.tv/")):
            _, source = parse_twitch_vod_url(source)
            source_kind = "twitch"
        job_id = database.create_job(
            source,
            source_kind=source_kind,
            analysis_mode=arguments.mode,
            content_profile=default_content_profile().to_dict(),
            analysis_profile=default_analysis_profile(arguments.mode).to_dict(),
        )
        print(f"Queued {job_id}")
        return 0

    if command == "jobs":
        print(json.dumps(database.list_jobs(), indent=2))
        return 0

    if command == "run-job":
        PipelineRunner(paths, database, on_event=print).run_job(arguments.job_id)
        return 0 if database.get_job(arguments.job_id)["status"] == "completed" else 1

    if command == "rebuild-candidates":
        job = database.get_job(arguments.job_id)
        if job is None:
            parser.error(f"Job does not exist: {arguments.job_id}")
        values = json.loads(str(job["content_profile_json"]))
        if arguments.max_candidates is not None:
            values["max_candidates"] = arguments.max_candidates
        profile = ContentProfile(**values)
        PipelineRunner(paths, database, on_event=print).rebuild_candidates(
            arguments.job_id,
            content_profile=profile.to_dict(),
        )
        return 0

    if command == "run-queue":
        count = PipelineRunner(paths, database, on_event=print).run_all()
        print(f"Processed {count} job(s).")
        return 0

    parser.error(f"Unsupported command: {command}")
    return 2
