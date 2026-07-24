from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from unittest import TestCase

from local_clip_ai.paths import AppPaths


class PathsTests(TestCase):
    def test_paths_are_rooted_in_selected_directory(self) -> None:
        temporary_path = Path(".local-data") / "unit-tests" / str(uuid.uuid4())
        temporary_path.mkdir(parents=True)
        try:
            paths = AppPaths.from_root(temporary_path)

            paths.ensure_directories()

            self.assertEqual(paths.root, temporary_path.resolve())
            self.assertEqual(paths.database, temporary_path.resolve() / "jobs.sqlite3")
            self.assertTrue(paths.artifacts.is_dir())
            self.assertTrue(paths.models.is_dir())
            self.assertTrue(paths.exports.is_dir())
        finally:
            shutil.rmtree(temporary_path)
