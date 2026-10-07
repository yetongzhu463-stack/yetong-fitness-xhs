#!/usr/bin/env python3
"""Regression tests for registering a new YETONG capability without editing the router."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_RELATIVE = "yetong/references/capability-registry.json"
MODULE_PATH = PROJECT_ROOT / "yetong/scripts/validate_registry.py"
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

    def test_current_modules_have_short_ids_and_service_lines(self) -> None:
        enabled = validator.validate(self.root, REGISTRY_RELATIVE)
        self.assertEqual(set(enabled), {
            "yetong-dna", "yetong-topic", "yetong-copy", "yetong-review",
            "yetong-title", "yetong-cover", "yetong-promo", "yetong-update",
        })
        lines = {item["id"]: item for item in self.registry["service_lines"]}
        self.assertEqual(set(lines), {"content", "moments", "performance"})
        self.assertEqual(lines["content"]["status"], "active")
        self.assertEqual(lines["moments"]["status"], "active")
        self.assertEqual(lines["performance"]["status"], "planned")
        for item in self.registry["capabilities"]:
            self.assertIn(item["service_line"], {"shared", "content", "moments"})
            self.assertIn(f"${item['id']}", item["menu_trigger"])
        self.assertEqual(self.registry["capabilities"][0]["service_line"], "shared")
        update = next(item for item in self.registry["capabilities"] if item["id"] == "yetong-update")
        self.assertEqual(update["service_line"], "shared")
        self.assertEqual(update["profile_requirement"], "none")
        self.assertIsNone(update["profile_check"])

    def test_course_promo_has_separate_inputs_and_profile_gate(self) -> None:
        promo = next(item for item in self.registry["capabilities"] if item["id"] == "yetong-promo")
        self.assertEqual(promo["service_line"], "moments")
        self.assertEqual(promo["profile_requirement"], "active")
        self.assertEqual(promo["profile_check"], "yetong-promo/scripts/check_profile.py")
        self.assertEqual(set(promo["required_any_of"]), {
            "product_brief", "existing_promo_plan", "existing_moments_draft",
        })
        self.assertEqual(set(promo["produces"]), {
            "product_positioning", "moments_campaign_plan", "moments_copy_recommendations",
        })
        self.assertIn(promo["profile_check"], promo["package_files"])
        self.assertTrue(any("小红书" in example for example in promo["avoid_when"]))

    def test_active_moments_line_cannot_lose_only_specialist(self) -> None:
        promo = next(item for item in self.registry["capabilities"] if item["id"] == "yetong-promo")
        promo["enabled"] = False
        self.save_registry()
        with self.assertRaisesRegex(ValueError, "moments.*没有启用"):
            validator.validate(self.root, REGISTRY_RELATIVE)

    def test_future_module_registers_without_router_edit(self) -> None:
        identifier = "yetong-risk"
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
            "service_line": "content",
            "menu_label": "发布风险检查",
            "menu_trigger": f"使用 ${identifier} 检查这篇内容的发布风险。",
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

    def test_disabled_module_may_be_absent_from_runtime(self) -> None:
        item = next(value for value in self.registry["capabilities"] if value["id"] == "yetong-cover")
        item["enabled"] = False
        shutil.rmtree(self.root / item["id"])
        self.save_registry()
        self.assertNotIn(item["id"], validator.validate(self.root, REGISTRY_RELATIVE))

    def test_disabled_profile_producer_cannot_leave_no_interview(self) -> None:
        item = next(value for value in self.registry["capabilities"] if value["id"] == "yetong-dna")
        item["enabled"] = False
        self.save_registry()
        with self.assertRaisesRegex(ValueError, "active_profile"):
            validator.validate(self.root, REGISTRY_RELATIVE)

    def test_missing_profile_gate_rejected(self) -> None:
        self.registry["capabilities"][1]["profile_check"] = None
        self.save_registry()
        with self.assertRaisesRegex(ValueError, "预检脚本"):
            validator.validate(self.root, REGISTRY_RELATIVE)

    def test_planned_service_line_cannot_claim_enabled_skill(self) -> None:
        self.registry["capabilities"][1]["service_line"] = "performance"
        self.save_registry()
        with self.assertRaisesRegex(ValueError, "规划中"):
            validator.validate(self.root, REGISTRY_RELATIVE)

    def test_future_moments_module_activates_its_service_line(self) -> None:
        # Preserve the planned -> active contract with a different future module.
        next(item for item in self.registry["capabilities"] if item["id"] == "yetong-promo")["enabled"] = False
        self.registry["service_lines"][1]["status"] = "planned"
        identifier = "yetong-moments"
        entry = f"{identifier}/SKILL.md"
        skill_path = self.root / entry
        skill_path.parent.mkdir(parents=True)
        skill_path.write_text(
            f"---\nname: {identifier}\ndescription: 根据本人档案规划面向本地会员的朋友圈内容。\n---\n\n# 朋友圈内容\n",
            encoding="utf-8",
        )
        gate = f"{identifier}/scripts/check_profile.py"
        gate_path = self.root / gate
        gate_path.parent.mkdir(parents=True)
        gate_path.write_text("# synthetic gate for registry validation\n", encoding="utf-8")
        self.registry["service_lines"][1]["status"] = "active"
        self.registry["capabilities"].append({
            "id": identifier,
            "service_line": "moments",
            "menu_label": "朋友圈内容",
            "menu_trigger": f"使用 ${identifier} 规划本周朋友圈内容。",
            "entry": entry,
            "package_files": [entry, gate],
            "purpose": "根据本人档案规划面向本地会员的朋友圈内容",
            "use_when": ["已有档案，要安排朋友圈内容"],
            "avoid_when": ["只要小红书选题"],
            "profile_requirement": "active",
            "required_any_of": [],
            "produces": ["moments_plan"],
            "offer_fit": "本地线下健身会员服务",
            "profile_check": gate,
            "priority": 60,
            "enabled": True,
        })
        self.save_registry()
        self.assertIn(identifier, validator.validate(self.root, REGISTRY_RELATIVE))

    def test_menu_rejects_incomplete_install(self) -> None:
        for relative in ("yetong/SKILL.md", "yetong/agents/openai.yaml"):
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PROJECT_ROOT / relative, destination)
        entry = self.root / "yetong-topic/SKILL.md"
        entry.rename(entry.with_name("SKILL.md.missing"))
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "yetong/scripts/show_menu.py"), "--root", str(self.root)],
            capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("安装校验未通过", result.stdout)
        self.assertIn("yetong-topic", result.stdout)
        self.assertNotIn("安装校验通过：", result.stdout)

    def test_private_or_unlisted_file_rejected(self) -> None:
        self.registry["capabilities"][1]["package_files"].append(
            "yetong-topic/evals/private-notes.md"
        )
        self.save_registry()
        with self.assertRaisesRegex(ValueError, "不安全"):
            validator.validate(self.root, REGISTRY_RELATIVE)


if __name__ == "__main__":
    unittest.main()
