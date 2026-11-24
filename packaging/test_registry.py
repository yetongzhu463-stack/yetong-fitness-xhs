#!/usr/bin/env python3
"""Regression tests for registering a new YETONG capability without editing the router."""

from __future__ import annotations

import importlib.util
import hashlib
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

    def prepare_complete_menu(self) -> None:
        for relative in sorted(validator.CORE_RUNTIME_FILES | {validator.DEFAULT_MANIFEST}):
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PROJECT_ROOT / relative, destination)

    def menu(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(PROJECT_ROOT / "yetong/scripts/show_menu.py"), "--root", str(self.root)],
            capture_output=True, text=True, check=False,
        )

    def catalog(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", "-S", str(PROJECT_ROOT / "yetong/scripts/list_skills.py"), "--root", str(self.root)],
            capture_output=True, text=True, check=False,
        )

    def refresh_manifest(self) -> None:
        release = self.root / validator.DEFAULT_MANIFEST
        manifest = json.loads(release.read_text(encoding="utf-8"))
        enabled = [item for item in self.registry["capabilities"] if item["enabled"]]
        expected = set(validator.CORE_RUNTIME_FILES)
        for item in enabled:
            expected.update(item["package_files"])
        hashes = {name: hashlib.sha256((self.root / name).read_bytes()).hexdigest() for name in sorted(expected)}
        manifest["skills"] = ["yetong", *[item["id"] for item in enabled]]
        manifest["files_sha256"] = hashes
        manifest["source_fingerprint"] = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode("utf-8")).hexdigest()
        release.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    def test_current_modules_have_short_ids_and_service_lines(self) -> None:
        enabled = validator.validate(self.root, REGISTRY_RELATIVE)
        self.assertEqual(set(enabled), {
            "yetong-dna", "yetong-topic", "yetong-copy", "yetong-review",
            "yetong-title", "yetong-fengmian-iuiu", "yetong-promo", "yetong-timer", "yetong-update", "yetong-remix", "yetong-stasis-angle", "yetong-zhishiku", "yetong-xiezuo-huoren",
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
            f"---\nname: {identifier}\ndescription: 检查本地健身内容草稿的发布风险。\n"
            "metadata:\n  yetong-handoff: |\n"
            "    - 已有草稿要检查发布风险 → 风险报告与修改建议\n"
            "    - 不交出：整篇写稿与自动发布\n---\n\n# 发布风险检查\n",
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
        self.prepare_complete_menu()
        self.save_registry()
        self.refresh_manifest()
        result = self.catalog()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = {row["name"]: row for row in json.loads(result.stdout)}
        self.assertIn(identifier, rows)
        self.assertIn("风险报告与修改建议", rows[identifier]["handoff"])
        self.assertEqual(rows[identifier]["entry"], str(skill_path.resolve()))

    def test_duplicate_module_rejected(self) -> None:
        self.registry["capabilities"].append(dict(self.registry["capabilities"][0]))
        self.save_registry()
        with self.assertRaisesRegex(ValueError, "重复"):
            validator.validate(self.root, REGISTRY_RELATIVE)

    def test_invalid_field_types_report_a_validation_error_not_traceback(self) -> None:
        mutations = (
            ("service_lines", "id"), ("service_lines", "status"),
            ("capabilities", "service_line"), ("capabilities", "profile_requirement"),
        )
        for section, field in mutations:
            with self.subTest(section=section, field=field):
                saved = self.registry[section][0][field]
                self.registry[section][0][field] = []
                self.save_registry()
                with self.assertRaises(ValueError):
                    validator.validate(self.root, REGISTRY_RELATIVE)
                result = self.menu()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("运行文件校验未通过", result.stdout)
                self.assertNotIn("Traceback", result.stderr)
                self.registry[section][0][field] = saved
                self.save_registry()

    def test_disabled_module_may_be_absent_from_runtime(self) -> None:
        item = next(value for value in self.registry["capabilities"] if value["id"] == "yetong-fengmian-iuiu")
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
        topic = next(item for item in self.registry["capabilities"] if item["id"] == "yetong-topic")
        topic["profile_check"] = None
        self.save_registry()
        with self.assertRaisesRegex(ValueError, "预检脚本"):
            validator.validate(self.root, REGISTRY_RELATIVE)

    def test_planned_service_line_cannot_claim_enabled_skill(self) -> None:
        topic = next(item for item in self.registry["capabilities"] if item["id"] == "yetong-topic")
        topic["service_line"] = "performance"
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
            f"---\nname: {identifier}\ndescription: 根据本人档案规划面向本地会员的朋友圈内容。\n"
            "metadata:\n  yetong-handoff: |\n"
            "    - 本人档案已激活，要安排朋友圈 → 朋友圈内容计划\n"
            "    - 不交出：小红书笔记\n---\n\n# 朋友圈内容\n",
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
        self.prepare_complete_menu()
        entry = self.root / "yetong-topic/SKILL.md"
        entry.rename(entry.with_name("SKILL.md.missing"))
        result = self.menu()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("运行文件校验未通过", result.stdout)
        self.assertIn("yetong-topic", result.stdout)
        self.assertNotIn("运行文件校验通过：", result.stdout)

    def test_complete_menu_distinguishes_files_host_and_planned_scope(self) -> None:
        self.prepare_complete_menu()
        result = self.menu()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("运行文件校验通过：14/14", result.stdout)
        self.assertIn(str(self.root.resolve()), result.stdout)
        self.assertIn("宿主当前发现／实际调用：本脚本未核验", result.stdout)
        self.assertIn("跨会话持久保存：本脚本未核验", result.stdout)
        self.assertIn("规划中（非安装缺失）", result.stdout)
        self.assertIn("不属于本次安装项", result.stdout)
        self.assertIn("已给素材的日常短文可用写作感", result.stdout)
        self.assertIn("长期排期和业绩管理仍未覆盖", result.stdout)
        self.assertNotIn("yetong-performance", result.stdout)
        self.assertNotIn("未安装完整", result.stdout)

    def test_menu_checks_required_router_resources(self) -> None:
        self.prepare_complete_menu()
        for relative in ("yetong/references/routing-contract.md", validator.DEFAULT_MANIFEST):
            with self.subTest(relative=relative):
                source = self.root / relative
                saved = source.read_bytes()
                source.unlink()
                result = self.menu()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(relative, result.stdout)
                self.assertNotIn("运行文件校验通过：", result.stdout)
                source.write_bytes(saved)

    def test_menu_rejects_tampered_runtime_and_manifest_members(self) -> None:
        self.prepare_complete_menu()
        entry = self.root / "yetong-topic/SKILL.md"
        original = entry.read_bytes()
        entry.write_bytes(original + b"\nchanged locally\n")
        result = self.menu()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("运行文件哈希不匹配：yetong-topic/SKILL.md", result.stdout)
        entry.write_bytes(original)
        release = self.root / validator.DEFAULT_MANIFEST
        manifest = json.loads(release.read_text(encoding="utf-8"))
        manifest["skills"].append("yetong-performance")
        release.write_text(json.dumps(manifest), encoding="utf-8")
        result = self.menu()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("技能成员不一致", result.stdout)

    def test_menu_does_not_reinstall_for_registry_errors(self) -> None:
        self.prepare_complete_menu()
        self.registry["capabilities"].append(dict(self.registry["capabilities"][0]))
        self.save_registry()
        result = self.menu()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("重复", result.stdout)
        self.assertNotIn("请重新安装整组", result.stdout)

    def assert_invalid_menu_shape_is_reported(self) -> None:
        result = self.menu()
        self.assertEqual(result.returncode, 1)
        self.assertIn("运行文件校验未通过", result.stdout)
        self.assertIn("请按上面的具体文件或登记错误处理", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_menu_handles_non_object_registry_without_secondary_error(self) -> None:
        self.prepare_complete_menu()
        for value in ([], None, "damaged registry"):
            with self.subTest(value=value):
                (self.root / REGISTRY_RELATIVE).write_text(json.dumps(value), encoding="utf-8")
                self.assert_invalid_menu_shape_is_reported()

    def test_menu_handles_non_list_capabilities_without_secondary_error(self) -> None:
        self.prepare_complete_menu()
        for value in (None, "damaged capabilities", {}):
            with self.subTest(value=value):
                self.registry["capabilities"] = value
                self.save_registry()
                self.assert_invalid_menu_shape_is_reported()

    def test_menu_handles_invalid_package_files_without_secondary_error(self) -> None:
        self.prepare_complete_menu()
        for value in (None, "damaged files", [None], {}):
            with self.subTest(value=value):
                self.registry["capabilities"][0]["package_files"] = value
                self.save_registry()
                self.assert_invalid_menu_shape_is_reported()

    def test_unsafe_relative_paths_are_rejected(self) -> None:
        for relative in ("", ".", "yetong//SKILL.md", "yetong/./SKILL.md", "yetong\\SKILL.md", "yetong/\x00SKILL.md"):
            with self.subTest(relative=relative):
                with self.assertRaises(ValueError):
                    validator.safe_relative(relative)

    def test_private_or_unlisted_file_rejected(self) -> None:
        topic = next(item for item in self.registry["capabilities"] if item["id"] == "yetong-topic")
        topic["package_files"].append(
            "yetong-topic/evals/private-notes.md"
        )
        self.save_registry()
        with self.assertRaisesRegex(ValueError, "不安全"):
            validator.validate(self.root, REGISTRY_RELATIVE)

    def test_catalog_reads_current_skill_metadata_and_profile_contract(self) -> None:
        self.prepare_complete_menu()
        # The candidate must come from the installed header, not cached registry prose.
        path = self.root / "yetong-topic/SKILL.md"
        text = path.read_text(encoding="utf-8")
        text = text.replace("description: 为健身教练生成", "description: 为当前测试教练生成", 1)
        path.write_text(text, encoding="utf-8")
        self.refresh_manifest()
        result = self.catalog()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = json.loads(result.stdout)
        self.assertEqual({row["name"] for row in rows}, set(validator.validate(self.root, REGISTRY_RELATIVE)))
        self.assertNotIn("yetong", {row["name"] for row in rows})
        topic = next(row for row in rows if row["name"] == "yetong-topic")
        self.assertTrue(topic["description"].startswith("为当前测试教练生成"))
        self.assertEqual(topic["handoff"], validator.skill_handoff(path))
        self.assertEqual(topic["profile_requirement"], "active")
        self.assertEqual(topic["source"], str(path.parent.resolve()))
        self.assertEqual(topic["profile_check"], str((self.root / "yetong-topic/scripts/check_profile.py").resolve()))

    def test_event_angle_is_a_verified_candidate_without_profile_dependency(self) -> None:
        self.prepare_complete_menu()
        result = self.catalog()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = {row["name"]: row for row in json.loads(result.stdout)}
        event = rows["yetong-stasis-angle"]
        self.assertEqual(event["profile_requirement"], "none")
        self.assertIsNone(event["profile_check"])
        self.assertEqual(set(event["required_any_of"]), {"selected_event", "event_materials"})
        self.assertIn("没有合格候选", event["handoff"])
        self.assertIn("不擅自用附带素材生产选题", event["handoff"])
        self.assertEqual(event["handoff"], validator.skill_handoff(self.root / "yetong-stasis-angle/SKILL.md"))
        # Registering event analysis must preserve downstream personalization gates.
        for identifier in ("yetong-copy", "yetong-topic", "yetong-title"):
            self.assertEqual(rows[identifier]["profile_requirement"], "active")

    def test_new_shared_modules_and_cover_are_verified_without_dna(self) -> None:
        self.prepare_complete_menu()
        result = self.catalog()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = {row["name"]: row for row in json.loads(result.stdout)}
        self.assertNotIn("yetong-cover", rows)
        for identifier in ("yetong-fengmian-iuiu", "yetong-zhishiku", "yetong-xiezuo-huoren"):
            with self.subTest(identifier=identifier):
                row = rows[identifier]
                self.assertEqual(row["profile_requirement"], "none")
                self.assertIsNone(row["profile_check"])
                self.assertTrue(row["required_any_of"])
                self.assertEqual(row["handoff"], validator.skill_handoff(self.root / identifier / "SKILL.md"))
        self.assertIn("exact_text_overlay", rows["yetong-fengmian-iuiu"]["produces"])
        self.assertIn("knowledge_root", rows["yetong-zhishiku"]["required_any_of"])
        self.assertEqual(rows["yetong-xiezuo-huoren"]["service_line"], "shared")
        for identifier in ("yetong-copy", "yetong-topic", "yetong-title", "yetong-promo"):
            self.assertEqual(rows[identifier]["profile_requirement"], "active")

    def test_enabled_module_without_handoff_is_not_a_dispatch_candidate(self) -> None:
        path = self.root / "yetong-topic/SKILL.md"
        original = path.read_text(encoding="utf-8")
        header, body = original.split("\n---\n", 1)
        header = header.split("\nmetadata:", 1)[0]
        path.write_text(header + "\n---\n" + body, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "yetong-handoff"):
            validator.validate(self.root, REGISTRY_RELATIVE)
        result = self.catalog()
        self.assertEqual(result.returncode, 1)
        self.assertIn("yetong-handoff", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_handoff_requires_input_output_rows_and_a_final_exclusion(self) -> None:
        path = self.root / "yetong-topic/SKILL.md"
        prefix = "---\nname: yetong-topic\ndescription: 测试接手契约。\nmetadata:\n"
        cases = (
            "  yetong-handoff: |\n    - 有输入但没有交付\n    - 不交出：自动发布\n",
            "  yetong-handoff: |\n    - 已有草稿 → 诊断结果\n",
            "  yetong-handoff: |\n    - 已有草稿 → 诊断结果\n    - 不交出：\n",
            "  yetong-handoff: >\n    - 已有草稿 → 诊断结果\n    - 不交出：自动发布\n",
            "  yetong-handoff: |\n    - 不交出：自动发布\n    - 已有草稿 → 诊断结果\n    - 不交出：完整改稿\n",
            "  yetong-handoff: |\n    - 已有草稿 → 诊断结果\n    - 不交出：自动发布\n"
            "  yetong-handoff: |\n    - 已有题 → 文案\n    - 不交出：标题\n",
        )
        for block in cases:
            with self.subTest(block=block):
                path.write_text(prefix + block + "---\n\n# 测试\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    validator.skill_handoff(path)

    def test_handoff_in_body_or_another_metadata_key_is_not_accepted(self) -> None:
        path = self.root / "yetong-topic/SKILL.md"
        for content in (
            "---\nname: yetong-topic\ndescription: 测试。\n---\n\nmetadata:\n  yetong-handoff: |\n    - 有输入 → 有输出\n    - 不交出：自动发布\n",
            "---\nname: yetong-topic\ndescription: 测试。\nmetadata:\n  dbs-handoff: |\n    - 有输入 → 有输出\n    - 不交出：自动发布\n---\n",
        ):
            with self.subTest(content=content):
                path.write_text(content, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "yetong-handoff"):
                    validator.skill_handoff(path)

    def test_catalog_ignores_unregistered_and_disabled_directories(self) -> None:
        self.prepare_complete_menu()
        item = next(item for item in self.registry["capabilities"] if item["id"] == "yetong-fengmian-iuiu")
        item["enabled"] = False
        shutil.rmtree(self.root / item["id"])
        unregistered = self.root / "yetong-unregistered"
        unregistered.mkdir()
        (unregistered / "SKILL.md").write_text("not a valid skill", encoding="utf-8")
        self.save_registry()
        self.refresh_manifest()
        result = self.catalog()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        names = {row["name"] for row in json.loads(result.stdout)}
        self.assertNotIn("yetong-fengmian-iuiu", names)
        self.assertNotIn("yetong-unregistered", names)

    def test_catalog_rejects_changed_metadata_until_manifest_is_updated(self) -> None:
        self.prepare_complete_menu()
        path = self.root / "yetong-topic/SKILL.md"
        path.write_text(path.read_text(encoding="utf-8").replace("未指定默认 8 个", "未指定默认 6 个", 1), encoding="utf-8")
        result = self.catalog()
        self.assertEqual(result.returncode, 1)
        self.assertIn("运行文件哈希不匹配：yetong-topic/SKILL.md", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_description_literal_and_folded_headers_are_read_without_dependencies(self) -> None:
        path = self.root / "yetong-topic/SKILL.md"
        for marker, expected in (("|", "第一行\n第二行"), (">", "第一行 第二行")):
            with self.subTest(marker=marker):
                path.write_text(f"---\nname: yetong-topic\ndescription: {marker}\n  第一行\n  第二行\n---\n", encoding="utf-8")
                self.assertEqual(validator.skill_description(path), expected)


if __name__ == "__main__":
    unittest.main()
