from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

from local_clip_ai.app.profiles_controller import ProfilesController
from local_clip_ai.config import default_content_profile
from local_clip_ai.storage import JobDatabase


class ProfilesControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(".local-data") / "unit-tests" / str(uuid.uuid4())
        self.database = JobDatabase(self.root / "jobs.sqlite3")
        self.database.initialize()
        self.database.upsert_profile(
            "content",
            "Default",
            default_content_profile().to_dict(),
            is_default=True,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def test_saved_default_is_persisted_for_new_jobs(self) -> None:
        controller = ProfilesController(self.database)

        controller.saveContentProfile(
            "Funny co-op failures and loud reactions",
            "auto",
            15,
            45,
            20,
            6,
        )

        profile = self.database.default_profile("content")
        self.assertEqual(profile["config"]["target_max_seconds"], 45)
        self.assertEqual(profile["config"]["auto_preselect_count"], 6)
