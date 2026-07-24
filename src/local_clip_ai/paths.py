from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DATA_DIR_ENVIRONMENT_VARIABLE = "LOCAL_CLIP_AI_DATA_DIR"


@dataclass(frozen=True, slots=True)
class AppPaths:
    root: Path
    database: Path
    artifacts: Path
    downloads: Path
    exports: Path
    logs: Path
    models: Path
    temporary: Path
    tools: Path

    @classmethod
    def from_root(cls, root: Path | str) -> AppPaths:
        resolved_root = Path(root).expanduser().resolve()
        return cls(
            root=resolved_root,
            database=resolved_root / "jobs.sqlite3",
            artifacts=resolved_root / "artifacts",
            downloads=resolved_root / "downloads",
            exports=resolved_root / "exports",
            logs=resolved_root / "logs",
            models=resolved_root / "models",
            temporary=resolved_root / "temp",
            tools=resolved_root / "tools",
        )

    @classmethod
    def default(cls, override: Path | str | None = None) -> AppPaths:
        if override is not None:
            return cls.from_root(override)

        configured_root = os.environ.get(DATA_DIR_ENVIRONMENT_VARIABLE)
        if configured_root:
            return cls.from_root(configured_root)

        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return cls.from_root(Path(local_app_data) / "LocalClipAI")

        return cls.from_root(Path.home() / ".local-clip-ai")

    def ensure_directories(self) -> None:
        for directory in (
            self.root,
            self.artifacts,
            self.downloads,
            self.exports,
            self.logs,
            self.models,
            self.temporary,
            self.tools,
        ):
            directory.mkdir(parents=True, exist_ok=True)
