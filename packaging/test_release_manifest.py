"""Prevent a stale update manifest from passing packaging or remote-install QA."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("yetong_bundle", ROOT / "packaging/build_bundle.py")
assert SPEC is not None and SPEC.loader is not None
bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle)


class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _, sources = bundle.registered_files()
        cls.payloads = bundle.collect(sources)

    def test_current_manifest_matches_runtime(self) -> None:
        bundle.validate_release(self.payloads)

    def test_changed_runtime_rejects_stale_manifest(self) -> None:
        changed = dict(self.payloads)
        name = bundle.archive_name("yetong-dna/SKILL.md")
        changed[name] += b"\nchanged runtime\n"
        with self.assertRaisesRegex(ValueError, "发布清单与运行文件不一致"):
            bundle.validate_release(changed)

    def test_missing_runtime_rejects_stale_manifest(self) -> None:
        changed = dict(self.payloads)
        del changed[bundle.archive_name("yetong-update/SKILL.md")]
        with self.assertRaisesRegex(ValueError, "发布清单与运行文件不一致"):
            bundle.validate_release(changed)


if __name__ == "__main__":
    unittest.main()
