from __future__ import annotations

import unittest

from local_clip_ai.resources import ResourceMonitor


class ResourceMonitorTests(unittest.TestCase):
    def test_snapshot_includes_process_tree_and_hardware_fields(self) -> None:
        monitor = ResourceMonitor()

        snapshot = monitor.sample()

        self.assertGreater(snapshot.logical_cores, 0)
        self.assertGreater(snapshot.system_ram_total_gib, 1)
        self.assertGreaterEqual(snapshot.app_ram_gib, 0)
        self.assertGreaterEqual(snapshot.system_cpu_percent, 0)
