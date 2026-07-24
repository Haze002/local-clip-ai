from __future__ import annotations

import csv
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from io import StringIO

from local_clip_ai.diagnostics.models import (
    CheckStatus,
    DiagnosticCheck,
    DiagnosticReport,
)
from local_clip_ai.paths import AppPaths


def _safe_probe(
    name: str,
    probe: Callable[[], DiagnosticCheck],
) -> DiagnosticCheck:
    try:
        return probe()
    except Exception as error:  # A diagnostic should report a failure, not crash the app.
        return DiagnosticCheck(
            name=name,
            status=CheckStatus.FAIL,
            summary=f"Probe failed: {type(error).__name__}",
            details={"error": str(error)},
        )


def _check_python() -> DiagnosticCheck:
    version = platform.python_version()
    supported = sys.version_info[:2] == (3, 12)
    return DiagnosticCheck(
        name="Python runtime",
        status=CheckStatus.PASS if supported else CheckStatus.FAIL,
        summary=f"Python {version}" + ("" if supported else " (Python 3.12 required)"),
        details={
            "version": version,
            "executable": sys.executable,
            "architecture": platform.architecture()[0],
        },
    )


def _check_windows() -> DiagnosticCheck:
    is_windows = platform.system() == "Windows"
    return DiagnosticCheck(
        name="Operating system",
        status=CheckStatus.PASS if is_windows else CheckStatus.WARN,
        summary=platform.platform(),
        details={
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
        },
    )


def _processor_name() -> str:
    if platform.system() == "Windows":
        try:
            import winreg

            key_path = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                if value:
                    return str(value).strip()
        except OSError:
            pass
    return platform.processor() or "Unknown processor"


def _check_cpu() -> DiagnosticCheck:
    logical_cores = os.cpu_count() or 0
    physical_cores: int | None = None
    current_percent: float | None = None
    try:
        import psutil

        physical_cores = psutil.cpu_count(logical=False)
        current_percent = psutil.cpu_percent(interval=0.1)
    except ImportError:
        pass

    processor = _processor_name()
    details = {
        "name": processor,
        "physical_cores": physical_cores,
        "logical_cores": logical_cores,
        "current_utilization_percent": current_percent,
    }
    core_text = (
        f"{physical_cores} cores / {logical_cores} threads"
        if physical_cores
        else f"{logical_cores} logical processors"
    )
    return DiagnosticCheck(
        name="Processor",
        status=CheckStatus.PASS if logical_cores else CheckStatus.WARN,
        summary=f"{processor} · {core_text}",
        details=details,
    )


def _memory_values() -> tuple[int, int, float]:
    try:
        import psutil

        memory = psutil.virtual_memory()
        return int(memory.total), int(memory.available), float(memory.percent)
    except ImportError:
        pass

    if platform.system() == "Windows":
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise ctypes.WinError()
        return (
            int(status.total_physical),
            int(status.available_physical),
            float(status.memory_load),
        )

    raise RuntimeError("Memory information is unavailable")


def _gib(value: int) -> float:
    return round(value / (1024**3), 2)


def _check_memory() -> DiagnosticCheck:
    total, available, percent = _memory_values()
    total_gib = _gib(total)
    available_gib = _gib(available)
    return DiagnosticCheck(
        name="System memory",
        status=CheckStatus.PASS if total_gib >= 16 else CheckStatus.WARN,
        summary=f"{total_gib:.2f} GiB total · {available_gib:.2f} GiB available",
        details={
            "total_bytes": total,
            "available_bytes": available,
            "used_percent": percent,
        },
    )


NVIDIA_QUERY_FIELDS = (
    "index",
    "name",
    "driver_version",
    "memory.total",
    "memory.used",
    "utilization.gpu",
    "temperature.gpu",
    "power.draw",
    "power.limit",
    "clocks.current.graphics",
)


def parse_nvidia_smi_row(output: str) -> dict[str, str]:
    rows = list(csv.reader(StringIO(output.strip())))
    if not rows:
        raise ValueError("nvidia-smi returned no GPU rows")
    values = [value.strip() for value in rows[0]]
    if len(values) != len(NVIDIA_QUERY_FIELDS):
        raise ValueError(
            f"Expected {len(NVIDIA_QUERY_FIELDS)} NVIDIA fields, received {len(values)}"
        )
    return dict(zip(NVIDIA_QUERY_FIELDS, values, strict=True))


def _check_nvidia_gpu() -> DiagnosticCheck:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return DiagnosticCheck(
            name="NVIDIA GPU",
            status=CheckStatus.FAIL,
            summary="nvidia-smi was not found",
            details={"required": "Current NVIDIA display driver"},
        )

    query = ",".join(NVIDIA_QUERY_FIELDS)
    completed = subprocess.run(
        [
            executable,
            f"--query-gpu={query}",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if completed.returncode != 0:
        return DiagnosticCheck(
            name="NVIDIA GPU",
            status=CheckStatus.FAIL,
            summary="nvidia-smi could not query the GPU",
            details={"error": completed.stderr.strip()},
        )

    details = parse_nvidia_smi_row(completed.stdout)
    return DiagnosticCheck(
        name="NVIDIA GPU",
        status=CheckStatus.PASS,
        summary=(
            f"{details['name']} · {details['memory.total']} MiB VRAM · "
            f"{details['temperature.gpu']} °C"
        ),
        details=details,
    )


def _tool_version(executable: str) -> str:
    completed = subprocess.run(
        [executable, "-version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = completed.stdout or completed.stderr
    return output.splitlines()[0].strip() if output else "Version unavailable"


def _check_ffmpeg(paths: AppPaths) -> DiagnosticCheck:
    from local_clip_ai.tools import find_ffmpeg

    ffmpeg, ffprobe = find_ffmpeg(paths)
    if not ffmpeg or not ffprobe:
        missing = [name for name, value in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)) if not value]
        return DiagnosticCheck(
            name="FFmpeg",
            status=CheckStatus.FAIL,
            summary=f"Missing required executable(s): {', '.join(missing)}; run install-tools",
            details={"ffmpeg": ffmpeg, "ffprobe": ffprobe},
        )

    return DiagnosticCheck(
        name="FFmpeg",
        status=CheckStatus.PASS,
        summary=_tool_version(ffmpeg),
        details={
            "ffmpeg": str(ffmpeg.resolve()),
            "ffprobe": str(ffprobe.resolve()),
        },
    )


def _check_local_ai() -> DiagnosticCheck:
    try:
        from local_clip_ai.analysis.transcription import (
            configure_nvidia_dll_directories,
        )

        dll_directories = configure_nvidia_dll_directories()
        import ctranslate2
        import faster_whisper
    except ImportError as error:
        return DiagnosticCheck(
            name="Local AI runtime",
            status=CheckStatus.FAIL,
            summary=f"Missing transcription dependency: {error.name}",
            details={"error": str(error)},
        )
    cuda_devices = ctranslate2.get_cuda_device_count()
    return DiagnosticCheck(
        name="Local AI runtime",
        status=CheckStatus.PASS if cuda_devices else CheckStatus.WARN,
        summary=(
            f"faster-whisper {faster_whisper.__version__} / "
            f"CTranslate2 {ctranslate2.__version__} / "
            f"{cuda_devices} CUDA device(s)"
        ),
        details={
            "cuda_device_count": cuda_devices,
            "cuda_compute_types": (
                sorted(ctranslate2.get_supported_compute_types("cuda"))
                if cuda_devices
                else []
            ),
            "nvidia_dll_directories": [str(path) for path in dll_directories],
        },
    )


def _check_sqlite() -> DiagnosticCheck:
    parts = tuple(int(part) for part in sqlite3.sqlite_version.split("."))
    supported = parts >= (3, 35, 0)
    return DiagnosticCheck(
        name="SQLite",
        status=CheckStatus.PASS if supported else CheckStatus.FAIL,
        summary=f"SQLite {sqlite3.sqlite_version}",
        details={"module_version": sqlite3.version},
    )


def _check_storage(paths: AppPaths) -> DiagnosticCheck:
    paths.ensure_directories()
    with tempfile.NamedTemporaryFile(dir=paths.root, prefix="write-test-", delete=True):
        pass
    usage = shutil.disk_usage(paths.root)
    free_gib = _gib(usage.free)
    status = CheckStatus.PASS if free_gib >= 20 else CheckStatus.WARN
    return DiagnosticCheck(
        name="Runtime storage",
        status=status,
        summary=f"{free_gib:.2f} GiB free at {paths.root}",
        details={
            "root": str(paths.root),
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
        },
    )


def collect_diagnostics(paths: AppPaths) -> DiagnosticReport:
    started_at = datetime.now(UTC)
    checks = (
        _safe_probe("Python runtime", _check_python),
        _safe_probe("Operating system", _check_windows),
        _safe_probe("Processor", _check_cpu),
        _safe_probe("System memory", _check_memory),
        _safe_probe("NVIDIA GPU", _check_nvidia_gpu),
        _safe_probe("Local AI runtime", _check_local_ai),
        _safe_probe("FFmpeg", lambda: _check_ffmpeg(paths)),
        _safe_probe("SQLite", _check_sqlite),
        _safe_probe("Runtime storage", lambda: _check_storage(paths)),
    )
    return DiagnosticReport(
        checks=checks,
        started_at=started_at,
        completed_at=datetime.now(UTC),
    )
