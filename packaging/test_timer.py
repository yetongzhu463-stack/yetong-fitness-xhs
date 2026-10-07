"""Check timer registration, real gate behavior and allowlisted isolation.

These tests do not validate model decisions or prove native scheduling works.
"""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "yetong-timer/scripts/check_profile.py"
REGISTRY = ROOT / "yetong/references/capability-registry.json"


class TimerTests(unittest.TestCase):
    def test_registered_timer_has_own_gate_and_content_line(self):
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        timer = next(item for item in registry["capabilities"] if item["id"] == "yetong-timer")
        self.assertEqual(timer["service_line"], "content")
        self.assertEqual(timer["profile_requirement"], "active")
        self.assertEqual(timer["required_any_of"], [])
        self.assertEqual(timer["profile_check"], "yetong-timer/scripts/check_profile.py")
        self.assertEqual(set(timer["produces"]), {"daily_hotspot_topics", "scheduled_topic_task_status"})
        self.assertEqual(len(timer["package_files"]), 6)

    def test_resources_and_private_eval_are_separated(self):
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        timer = next(item for item in registry["capabilities"] if item["id"] == "yetong-timer")
        for relative in timer["package_files"]:
            with self.subTest(resource=relative):
                resource = ROOT / relative
                self.assertTrue(resource.is_file())
                self.assertNotIn("evals", resource.parts)
                self.assertNotIn("private-profiles", resource.parts)
                self.assertNotIn(b"/Users/", resource.read_bytes())
        self.assertEqual((ROOT / "LICENSE").read_bytes(), (ROOT / "yetong-timer/references/LICENSE").read_bytes())

    def test_missing_profile_fails_without_leaking_content(self):
        with tempfile.TemporaryDirectory(prefix="yetong-timer-gate-") as directory:
            result = subprocess.run([sys.executable, str(GATE), str(Path(directory) / "absent.md")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 3)
            self.assertEqual(result.stdout.strip(), "invalid: profile file missing")

    def test_active_with_incomplete_sections_is_not_usable(self):
        with tempfile.TemporaryDirectory(prefix="yetong-timer-gate-") as directory:
            path = Path(directory) / "person-dna.md"
            path.write_text("---\nschema_version: 2\nprofile_id: synthetic\ndisplay_name: 测试\nstatus: active\nconfirmed_at: 2026-10-07\n---\n\n# 未完成的合成档案\n", encoding="utf-8")
            result = subprocess.run([sys.executable, str(GATE), str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 3)
            self.assertEqual(result.stdout.strip(), "invalid: required profile sections missing or too short")


if __name__ == "__main__":
    unittest.main()
