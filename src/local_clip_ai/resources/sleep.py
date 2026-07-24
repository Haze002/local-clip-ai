from __future__ import annotations

import os
from types import TracebackType

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


class SleepInhibitor:
    """Prevent automatic system sleep only while a pipeline run is active."""

    def __init__(self) -> None:
        self.active = False

    def acquire(self) -> bool:
        if self.active:
            return True
        if os.name != "nt":
            self.active = True
            return True
        import ctypes

        result = ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        )
        if not result:
            raise ctypes.WinError()
        self.active = True
        return True

    def release(self) -> None:
        if not self.active:
            return
        if os.name == "nt":
            import ctypes

            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        self.active = False

    def __enter__(self) -> SleepInhibitor:
        self.acquire()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()
