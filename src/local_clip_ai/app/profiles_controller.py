from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from local_clip_ai.config import ContentProfile, default_content_profile
from local_clip_ai.storage import JobDatabase


class ProfilesController(QObject):
    changed = Signal()

    def __init__(self, database: JobDatabase):
        super().__init__()
        self._database = database
        self._notice = ""
        self._content: dict[str, Any] = {}
        self.refresh()

    @Property(str, notify=changed)
    def notice(self) -> str:
        return self._notice

    @Property(str, notify=changed)
    def preference(self) -> str:
        return str(self._content.get("preference", ""))

    @Property(str, notify=changed)
    def language(self) -> str:
        return str(self._content.get("language", "auto"))

    @Property(int, notify=changed)
    def targetMinSeconds(self) -> int:
        return int(self._content.get("target_min_seconds", 20))

    @Property(int, notify=changed)
    def targetMaxSeconds(self) -> int:
        return int(self._content.get("target_max_seconds", 60))

    @Property(int, notify=changed)
    def maxCandidates(self) -> int:
        return int(self._content.get("max_candidates", 50))

    @Property(int, notify=changed)
    def autoPreselectCount(self) -> int:
        return int(self._content.get("auto_preselect_count", 10))

    @Slot()
    def refresh(self) -> None:
        profile = self._database.default_profile("content")
        self._content = (
            dict(profile["config"]) if profile else default_content_profile().to_dict()
        )
        self.changed.emit()

    @Slot(str, str, int, int, int, int)
    def saveContentProfile(
        self,
        preference: str,
        language: str,
        target_min_seconds: int,
        target_max_seconds: int,
        max_candidates: int,
        auto_preselect_count: int,
    ) -> None:
        try:
            profile = ContentProfile(
                preference=preference.strip() or default_content_profile().preference,
                language=language,
                target_min_seconds=target_min_seconds,
                target_max_seconds=target_max_seconds,
                setup_context_seconds=float(
                    self._content.get("setup_context_seconds", 4)
                ),
                payoff_context_seconds=float(
                    self._content.get("payoff_context_seconds", 3)
                ),
                max_candidates=max_candidates,
                auto_preselect_count=auto_preselect_count,
            )
        except ValueError as error:
            self._notice = str(error)
            self.changed.emit()
            return
        self._database.upsert_profile(
            "content",
            "Default",
            profile.to_dict(),
            is_default=True,
        )
        self._content = profile.to_dict()
        self._notice = "Default content profile saved."
        self.changed.emit()
