from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from local_clip_ai.resources import ResourceMonitor
from local_clip_ai.storage import JobDatabase


class ResourceController(QObject):
    snapshotChanged = Signal()
    policyChanged = Signal()
    resumeRequested = Signal()

    def __init__(self, database: JobDatabase):
        super().__init__()
        self._database = database
        self._monitor = ResourceMonitor()
        self._snapshot: dict[str, Any] = {}
        self._thermal_status = "Monitoring"
        self._gpu_pause_temperature = float(
            database.get_setting("thermal.gpu_pause_c", 90)
        )
        self._cpu_pause_temperature = float(
            database.get_setting("thermal.cpu_pause_c", 90)
        )
        self._resume_temperature = float(
            database.get_setting("thermal.resume_c", 82)
        )
        self._grace_seconds = int(database.get_setting("thermal.grace_seconds", 120))
        self._stable_seconds = int(database.get_setting("thermal.stable_seconds", 30))
        self._vram_soft_limit_gib = float(
            database.get_setting("resources.vram_soft_limit_gib", 10.5)
        )
        self._above_since: float | None = None
        self._below_since: float | None = None
        self._thermal_pause_active = False
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    @Property("QVariantMap", notify=snapshotChanged)
    def snapshot(self) -> dict[str, Any]:
        return self._snapshot

    @Property(str, notify=policyChanged)
    def thermalStatus(self) -> str:
        return self._thermal_status

    @Property(float, notify=policyChanged)
    def gpuPauseTemperature(self) -> float:
        return self._gpu_pause_temperature

    @Property(float, notify=policyChanged)
    def cpuPauseTemperature(self) -> float:
        return self._cpu_pause_temperature

    @Property(float, notify=policyChanged)
    def resumeTemperature(self) -> float:
        return self._resume_temperature

    @Property(int, notify=policyChanged)
    def graceSeconds(self) -> int:
        return self._grace_seconds

    @Property(int, notify=policyChanged)
    def stableSeconds(self) -> int:
        return self._stable_seconds

    @Property(float, notify=policyChanged)
    def vramSoftLimitGib(self) -> float:
        return self._vram_soft_limit_gib

    @Slot()
    def refresh(self) -> None:
        try:
            snapshot = self._monitor.sample().to_dict()
        except Exception as error:
            self._thermal_status = f"Monitor error: {error}"
            self.policyChanged.emit()
            return
        snapshot["vram_pressure"] = (
            snapshot.get("app_vram_gib") is not None
            and snapshot["app_vram_gib"] >= self._vram_soft_limit_gib
        )
        self._snapshot = snapshot
        self.snapshotChanged.emit()
        self._apply_thermal_policy(snapshot)

    def _apply_thermal_policy(self, snapshot: dict[str, Any]) -> None:
        now = time.monotonic()
        gpu_temperature = snapshot.get("gpu_temperature_c")
        cpu_temperature = snapshot.get("cpu_temperature_c")
        over_gpu = (
            gpu_temperature is not None
            and gpu_temperature >= self._gpu_pause_temperature
        )
        over_cpu = (
            cpu_temperature is not None
            and cpu_temperature >= self._cpu_pause_temperature
        )
        if over_gpu or over_cpu:
            self._below_since = None
            if self._above_since is None:
                self._above_since = now
            elapsed = now - self._above_since
            remaining = max(0, self._grace_seconds - int(elapsed))
            source = "GPU" if over_gpu else "CPU"
            self._thermal_status = (
                f"{source} is above its limit; pausing in {remaining}s if it stays hot."
            )
            if elapsed >= self._grace_seconds and not self._thermal_pause_active:
                paused = 0
                for job in self._database.list_jobs():
                    if job["status"] == "running" and self._database.request_pause(
                        str(job["id"]),
                        f"{source.lower()}_temperature",
                    ):
                        paused += 1
                self._thermal_pause_active = paused > 0
                if paused:
                    self._thermal_status = (
                        f"Thermal pause requested for {paused} job(s); waiting to cool."
                    )
            self.policyChanged.emit()
            return

        self._above_since = None
        temperatures = [
            value
            for value in (gpu_temperature, cpu_temperature)
            if value is not None
        ]
        cool_enough = not temperatures or max(temperatures) <= self._resume_temperature
        if self._thermal_pause_active and cool_enough:
            if self._below_since is None:
                self._below_since = now
            stable_for = now - self._below_since
            remaining = max(0, self._stable_seconds - int(stable_for))
            self._thermal_status = f"Cooling is stable; resuming in {remaining}s."
            if stable_for >= self._stable_seconds:
                resumed = 0
                for job in self._database.list_jobs():
                    if (
                        job["status"] == "paused"
                        and str(job.get("paused_reason") or "").endswith("_temperature")
                        and self._database.resume_job(str(job["id"]))
                    ):
                        resumed += 1
                self._thermal_pause_active = False
                self._below_since = None
                self._thermal_status = f"Temperatures recovered; resumed {resumed} job(s)."
                if resumed:
                    self.resumeRequested.emit()
        elif not self._thermal_pause_active:
            self._below_since = None
            self._thermal_status = "Temperatures are within configured limits."
        self.policyChanged.emit()

    @Slot(float)
    def setGpuPauseTemperature(self, value: float) -> None:
        self._gpu_pause_temperature = max(50, min(110, value))
        self._database.set_setting("thermal.gpu_pause_c", self._gpu_pause_temperature)
        self.policyChanged.emit()

    @Slot(float)
    def setCpuPauseTemperature(self, value: float) -> None:
        self._cpu_pause_temperature = max(50, min(110, value))
        self._database.set_setting("thermal.cpu_pause_c", self._cpu_pause_temperature)
        self.policyChanged.emit()

    @Slot(float)
    def setResumeTemperature(self, value: float) -> None:
        highest_pause = min(self._gpu_pause_temperature, self._cpu_pause_temperature)
        self._resume_temperature = max(40, min(highest_pause - 1, value))
        self._database.set_setting("thermal.resume_c", self._resume_temperature)
        self.policyChanged.emit()

    @Slot(int)
    def setGraceSeconds(self, value: int) -> None:
        self._grace_seconds = max(10, min(1800, value))
        self._database.set_setting("thermal.grace_seconds", self._grace_seconds)
        self.policyChanged.emit()

    @Slot(float)
    def setVramSoftLimitGib(self, value: float) -> None:
        self._vram_soft_limit_gib = max(1, min(64, value))
        self._database.set_setting(
            "resources.vram_soft_limit_gib",
            self._vram_soft_limit_gib,
        )
        self.policyChanged.emit()
