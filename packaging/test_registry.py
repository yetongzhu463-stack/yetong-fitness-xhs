#!/usr/bin/env python3
"""Regression tests for registering a new YETONG capability without editing the router."""

from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_RELATIVE = "yetong-fitness-xhs/references/capability-registry.json"
MODULE_PATH = PROJECT_ROOT / "yetong-fitness-xhs/scripts/validate_registry.py"
SPEC = importlib.util.spec_from_file_location("yetong_registry_validator", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="yetong-registry-test-")
        self.root = Path(self.temporary.name)
        self.registry = json.loads((PROJECT_ROOT / REGISTRY_RELATIVE).read_text(encoding="utf-8"))
        for item in self.registry["capabilities"]:
            for relative in item["package_files"]:
                destination = self.root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(PROJECT_ROOT / relative, destination)
        self.save_registry()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def save_registry(self) -> None:
        path = self.root / REGISTRY_RELATIVE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.registry, ensure_ascii=False), encoding="utf-8")

    def test_current_three_modules(self) -> None:
        self.assertEqual(len(validator.validate(self.root, REGISTRY_RELATIVE)), 3)

    def test_future_module_registers_without_router_edit(self) -> None:
        identifier = "yetong-fitness-xhs-risk"
        entry = f"{identifier}/SKILL.md"
        skill_path = self.root / entry
        skill_path.parent.mkdir(parents=True)
        skill_path.write_text(
            f"---\nname: {identifier}\ndescription: 检查本地健身内容草稿的发布风险。\n---\n\n# 发布风险检查\n",
            encoding="utf-8",
        )
        gate = f"{identifier}/scripts/check_profile.py"
        gate_path = self.root / gate
        gate_path.parent.mkdir(parents=True)
        gate_path.write_text("# synthetic gate for registry validation\n", encoding="utf-8")
        self.registry["capabilities"].append({
            "id": identifier,
            "entry": entry,
            "package_files": [entry, gate],
            "purpose": "检查已写好的本地健身内容草稿",
            "use_when": ["已有草稿要检查发布风险"],
            "avoid_when": ["还没有草稿且只要选题"],
            "profile_requirement": "optional",
            "required_any_of": ["existing_draft"],
            "produces": ["risk_report"],
            "offer_fit": "已确认的本地线下健身服务",
            "profile_check": gate,
            "priority": 70,
            "enabled": True,
        })
        self.save_registry()
        self.assertIn(identifier, validator.validate(self.root, REGISTRY_RELATIVE))

    def test_duplicate_module_rejected(self) -> None:
        self.registry["capabilities"].append(dict(self.registry["capabilities"][0]))
        self.save_registry()
        with self.assertRaisesRegex(ValueError, "重复"):
            validator.validate(self.root, REGISTRY_RELATIVE)

    def test_missing_profile_gate_rejected(self) -> None:
        self.registry["capabilities"][1]["profile_check"] = None
        self.save_registry()
        with self.assertRaisesRegex(ValueError, "预检脚本"):
            validator.validate(self.root, REGISTRY_RELATIVE)

    def test_private_or_unlisted_file_rejected(self) -> None:
        self.registry["capabilities"][1]["package_files"].append(
            "yetong-fitness-xhs-topic/evals/private-notes.md"
        )
        self.save_registry()
        with self.assertRaisesRegex(ValueError, "不安全"):
            validator.validate(self.root, REGISTRY_RELATIVE)


if __name__ == "__main__":
    unittest.main()
