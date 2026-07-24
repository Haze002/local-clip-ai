from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from local_clip_ai.app.results_controller import (
    CandidateListModel,
    ResultsController,
    available_output_path,
    job_export_folder,
    safe_path_component,
)
from local_clip_ai.paths import AppPaths
from local_clip_ai.storage import JobDatabase


class ResultsControllerTests(TestCase):
    def setUp(self) -> None:
        self.root = Path(".local-data") / "unit-tests" / str(uuid.uuid4())
        self.paths = AppPaths.from_root(self.root)
        self.paths.ensure_directories()
        self.database = JobDatabase(self.paths.database)
        self.database.initialize()

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def test_export_settings_are_persisted(self) -> None:
        model = CandidateListModel()
        controller = ResultsController(self.paths, self.database, model)
        custom_directory = self.root / "My clips"
        custom_download_directory = self.root / "VOD cache"

        controller.setExportResolution("720p")
        controller.setExportDirectory(str(custom_directory))
        controller.setDownloadDirectory(str(custom_download_directory))
        controller.setAutoExportPreselected(False)

        restored = ResultsController(self.paths, self.database, CandidateListModel())
        self.assertEqual(restored.exportResolution, "720p")
        self.assertEqual(restored.exportDirectory, str(custom_directory.resolve()))
        self.assertEqual(
            restored.downloadDirectory,
            str(custom_download_directory.resolve()),
        )
        self.assertFalse(restored.autoExportPreselected)

    def test_candidates_are_grouped_under_the_vod_title(self) -> None:
        uri = "https://www.twitch.tv/videos/2823263031"
        self.database.upsert_source(
            uri,
            source_kind="twitch",
            provider_id="2823263031",
            title="A Minecraft stream",
            channel="haze002",
        )
        job_id = self.database.create_job(uri, source_kind="twitch")
        self.database.save_candidate(
            job_id,
            start_seconds=10,
            end_seconds=20,
            score=0.9,
            title="A good moment",
            spans=[{"start_seconds": 10, "end_seconds": 20, "score": 0.9}],
        )
        model = CandidateListModel()

        ResultsController(self.paths, self.database, model)

        index = model.index(0)
        self.assertEqual(model.data(index, model.GroupTitleRole), "A Minecraft stream")
        self.assertEqual(model.data(index, model.GroupCountRole), 1)
        self.assertTrue(model.data(index, model.GroupFirstRole))
        self.assertTrue(model.data(index, model.GroupDefaultOpenRole))
        self.assertEqual(model.data(index, model.GroupPreselectedCountRole), 0)

    def test_windows_output_names_are_safe_and_identifiable(self) -> None:
        job = {
            "source_kind": "twitch",
            "source_uri": "https://www.twitch.tv/videos/123",
            "source_provider_id": "123",
            "source_title": 'A stream: "wins" / fails?',
        }

        self.assertEqual(
            job_export_folder(job),
            "A stream wins fails [123]",
        )
        self.assertEqual(safe_path_component("CON", fallback="clip"), "_CON")

    def test_reexport_chooses_a_new_name(self) -> None:
        original = self.root / "clip.mp4"
        original.touch()

        self.assertEqual(
            available_output_path(original),
            self.root / "clip (2).mp4",
        )

    def test_batch_export_runs_only_unexported_auto_selected_candidates(self) -> None:
        job_id = self.database.create_job(
            "https://www.twitch.tv/videos/123",
            source_kind="twitch",
        )
        wanted = [
            self.database.save_candidate(
                job_id,
                start_seconds=start,
                end_seconds=start + 10,
                score=0.9,
                title=f"Candidate {start}",
                spans=[
                    {
                        "start_seconds": start,
                        "end_seconds": start + 10,
                        "score": 0.9,
                    }
                ],
                metadata={"auto_preselected": True},
            )
            for start in (10, 30)
        ]
        self.database.save_candidate(
            job_id,
            start_seconds=50,
            end_seconds=60,
            score=0.8,
            title="Manual candidate",
            spans=[{"start_seconds": 50, "end_seconds": 60, "score": 0.8}],
            metadata={"auto_preselected": False},
        )
        rejected_id = self.database.save_candidate(
            job_id,
            start_seconds=70,
            end_seconds=80,
            score=0.7,
            title="Rejected auto candidate",
            spans=[{"start_seconds": 70, "end_seconds": 80, "score": 0.7}],
            metadata={"auto_preselected": True},
        )
        self.database.set_candidate_review_status(rejected_id, "rejected")
        controller = ResultsController(
            self.paths,
            self.database,
            CandidateListModel(),
        )
        exported: list[str] = []

        class ImmediateThread:
            def __init__(self, *, target: object, args: tuple[str], **_: object):
                self.target = target
                self.args = args

            def start(self) -> None:
                self.target(*self.args)  # type: ignore[operator]

        def finish(candidate_id: str) -> None:
            exported.append(candidate_id)
            controller.exportWorkerFinished.emit(
                str(self.root / f"{candidate_id}.mp4"),
                False,
            )

        with (
            patch(
                "local_clip_ai.app.results_controller.threading.Thread",
                ImmediateThread,
            ),
            patch.object(controller, "_export_candidate", side_effect=finish),
        ):
            controller.exportPreselected(job_id)

        self.assertCountEqual(exported, wanted)
        self.assertFalse(controller.exporting)
        self.assertIn("Exported 2 auto-selected clip(s)", controller.notice)
