from __future__ import annotations

from dataclasses import dataclass


def parse_timecode(value: str | float | int) -> float:
    if isinstance(value, int | float):
        seconds = float(value)
    else:
        parts = value.strip().split(":")
        if not 1 <= len(parts) <= 3:
            raise ValueError(f"Invalid timecode: {value!r}")
        try:
            numbers = [float(part) for part in parts]
        except ValueError as error:
            raise ValueError(f"Invalid timecode: {value!r}") from error
        seconds = 0.0
        for number in numbers:
            seconds = seconds * 60 + number
    if seconds < 0:
        raise ValueError("Timecodes cannot be negative")
    return seconds


def format_timecode(seconds: float) -> str:
    if seconds < 0:
        raise ValueError("Timecodes cannot be negative")
    whole_seconds = int(seconds)
    milliseconds = round((seconds - whole_seconds) * 1000)
    if milliseconds == 1000:
        whole_seconds += 1
        milliseconds = 0
    hours, remainder = divmod(whole_seconds, 3600)
    minutes, final_seconds = divmod(remainder, 60)
    base = f"{hours:02d}:{minutes:02d}:{final_seconds:02d}"
    return f"{base}.{milliseconds:03d}" if milliseconds else base


@dataclass(frozen=True, slots=True)
class TimeRange:
    start: float
    end: float

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError("Range start cannot be negative")
        if self.end <= self.start:
            raise ValueError("Range end must be after its start")

    @classmethod
    def from_timecodes(cls, start: str, end: str) -> TimeRange:
        return cls(parse_timecode(start), parse_timecode(end))

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict[str, float | str]:
        return {
            "start_seconds": self.start,
            "end_seconds": self.end,
            "duration_seconds": self.duration,
            "start_timecode": format_timecode(self.start),
            "end_timecode": format_timecode(self.end),
        }
