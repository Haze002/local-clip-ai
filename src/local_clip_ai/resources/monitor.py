from __future__ import annotations

import os
import platform
from contextlib import suppress
from dataclasses import asdict, dataclass
from typing import Any

import psutil


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    system_cpu_percent: float
    app_cpu_percent: float
    cpu_current_mhz: float | None
    cpu_max_mhz: float | None
    physical_cores: int
    logical_cores: int
    cpu_temperature_c: float | None
    system_ram_used_gib: float
    system_ram_total_gib: float
    app_ram_gib: float
    app_read_mib: float
    app_write_mib: float
    gpu_name: str | None
    gpu_percent: float | None
    gpu_temperature_c: float | None
    gpu_clock_mhz: int | None
    gpu_memory_clock_mhz: int | None
    gpu_power_watts: float | None
    gpu_power_limit_watts: float | None
    gpu_vram_used_gib: float | None
    gpu_vram_total_gib: float | None
    app_vram_gib: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _gib(value: int | float) -> float:
    return float(value) / (1024**3)


def _mib(value: int | float) -> float:
    return float(value) / (1024**2)


def _cpu_temperature() -> float | None:
    if not hasattr(psutil, "sensors_temperatures"):
        return None
    try:
        sensors = psutil.sensors_temperatures(fahrenheit=False)
    except (AttributeError, OSError):
        return None
    preferred_names = ("k10temp", "coretemp", "cpu_thermal", "acpitz")
    for name in preferred_names:
        for entry in sensors.get(name, []):
            if entry.current is not None:
                return float(entry.current)
    for entries in sensors.values():
        for entry in entries:
            if entry.current is not None:
                return float(entry.current)
    return None


class ResourceMonitor:
    def __init__(self, process_id: int | None = None):
        self.process = psutil.Process(process_id or os.getpid())
        self.process.cpu_percent(None)
        self._nvml: Any = None
        self._gpu_handle: Any = None
        self._initialize_nvml()

    def _initialize_nvml(self) -> None:
        try:
            import pynvml

            pynvml.nvmlInit()
            self._nvml = pynvml
            self._gpu_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        except Exception:
            self._nvml = None
            self._gpu_handle = None

    def _processes(self) -> list[psutil.Process]:
        processes = [self.process]
        with suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            processes.extend(self.process.children(recursive=True))
        return processes

    @staticmethod
    def _safe_process_value(process: psutil.Process, getter: str) -> Any:
        try:
            return getattr(process, getter)()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    def _gpu_values(self, process_ids: set[int]) -> dict[str, Any]:
        if self._nvml is None or self._gpu_handle is None:
            return {}
        nvml = self._nvml
        handle = self._gpu_handle

        def optional(call: Any, default: Any = None) -> Any:
            try:
                return call()
            except nvml.NVMLError:
                return default

        memory = optional(lambda: nvml.nvmlDeviceGetMemoryInfo(handle))
        utilization = optional(lambda: nvml.nvmlDeviceGetUtilizationRates(handle))
        app_vram = 0
        seen_pids: set[int] = set()
        for getter_name in (
            "nvmlDeviceGetComputeRunningProcesses",
            "nvmlDeviceGetGraphicsRunningProcesses",
        ):
            getter = getattr(nvml, getter_name, None)
            if getter is None:
                continue
            for process in optional(lambda getter=getter: getter(handle), []):
                if process.pid in process_ids and process.pid not in seen_pids:
                    used = getattr(process, "usedGpuMemory", 0)
                    if isinstance(used, int) and used > 0:
                        app_vram += used
                    seen_pids.add(process.pid)
        name = optional(lambda: nvml.nvmlDeviceGetName(handle))
        if isinstance(name, bytes):
            name = name.decode(errors="replace")
        return {
            "gpu_name": str(name) if name else None,
            "gpu_percent": float(utilization.gpu) if utilization else None,
            "gpu_temperature_c": optional(
                lambda: float(
                    nvml.nvmlDeviceGetTemperature(
                        handle,
                        nvml.NVML_TEMPERATURE_GPU,
                    )
                )
            ),
            "gpu_clock_mhz": optional(
                lambda: int(nvml.nvmlDeviceGetClockInfo(handle, nvml.NVML_CLOCK_GRAPHICS))
            ),
            "gpu_memory_clock_mhz": optional(
                lambda: int(nvml.nvmlDeviceGetClockInfo(handle, nvml.NVML_CLOCK_MEM))
            ),
            "gpu_power_watts": optional(
                lambda: float(nvml.nvmlDeviceGetPowerUsage(handle)) / 1000
            ),
            "gpu_power_limit_watts": optional(
                lambda: float(nvml.nvmlDeviceGetEnforcedPowerLimit(handle)) / 1000
            ),
            "gpu_vram_used_gib": _gib(memory.used) if memory else None,
            "gpu_vram_total_gib": _gib(memory.total) if memory else None,
            "app_vram_gib": _gib(app_vram),
        }

    def sample(self) -> ResourceSnapshot:
        processes = self._processes()
        app_cpu = 0.0
        app_ram = 0
        read_bytes = 0
        write_bytes = 0
        process_ids = set()
        for process in processes:
            process_ids.add(process.pid)
            cpu = self._safe_process_value(process, "cpu_percent")
            memory = self._safe_process_value(process, "memory_info")
            io = self._safe_process_value(process, "io_counters")
            app_cpu += float(cpu or 0)
            app_ram += int(memory.rss if memory else 0)
            read_bytes += int(io.read_bytes if io else 0)
            write_bytes += int(io.write_bytes if io else 0)
        memory = psutil.virtual_memory()
        frequency = psutil.cpu_freq()
        gpu = self._gpu_values(process_ids)
        return ResourceSnapshot(
            system_cpu_percent=float(psutil.cpu_percent(None)),
            app_cpu_percent=app_cpu,
            cpu_current_mhz=float(frequency.current) if frequency else None,
            cpu_max_mhz=float(frequency.max) if frequency else None,
            physical_cores=psutil.cpu_count(logical=False) or 0,
            logical_cores=psutil.cpu_count(logical=True) or 0,
            cpu_temperature_c=_cpu_temperature(),
            system_ram_used_gib=_gib(memory.used),
            system_ram_total_gib=_gib(memory.total),
            app_ram_gib=_gib(app_ram),
            app_read_mib=_mib(read_bytes),
            app_write_mib=_mib(write_bytes),
            gpu_name=gpu.get("gpu_name"),
            gpu_percent=gpu.get("gpu_percent"),
            gpu_temperature_c=gpu.get("gpu_temperature_c"),
            gpu_clock_mhz=gpu.get("gpu_clock_mhz"),
            gpu_memory_clock_mhz=gpu.get("gpu_memory_clock_mhz"),
            gpu_power_watts=gpu.get("gpu_power_watts"),
            gpu_power_limit_watts=gpu.get("gpu_power_limit_watts"),
            gpu_vram_used_gib=gpu.get("gpu_vram_used_gib"),
            gpu_vram_total_gib=gpu.get("gpu_vram_total_gib"),
            app_vram_gib=gpu.get("app_vram_gib"),
        )

    @property
    def platform_summary(self) -> str:
        return f"{platform.system()} {platform.release()}"
