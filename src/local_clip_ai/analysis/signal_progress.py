from __future__ import annotations

import re
from collections.abc import Callable

PTS_TIME = re.compile(r"\bpts_time:(-?\d+(?:\.\d+)?)")
ProgressCallback = Callable[[float], None]
OutputCallback = Callable[[str], None]


def metadata_progress_reporter(
    duration_seconds: float | None,
    on_progress: ProgressCallback | None,
    *,
    minimum_step: float = 0.01,
) -> OutputCallback | None:
    """Convert streamed FFmpeg metadata timestamps into throttled fractions."""
    if on_progress is None or duration_seconds is None or duration_seconds <= 0:
        return None
    if not 0 < minimum_step <= 1:
        raise ValueError("Progress minimum_step must be between zero and one")
    last_reported = -minimum_step

    def report(line: str) -> None:
        nonlocal last_reported
        match = PTS_TIME.search(line)
        if match is None:
            return
        fraction = max(0.0, min(1.0, float(match.group(1)) / duration_seconds))
        if fraction >= 1 or fraction - last_reported >= minimum_step:
            last_reported = fraction
            on_progress(fraction)

    return report
