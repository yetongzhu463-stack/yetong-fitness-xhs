#!/usr/bin/env python3
"""Exercise update transactions in disposable directories, without network or global writes."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("yetong_updater_tested", ROOT / "yetong-update/scripts/update_bundle.py")
assert SPEC is not None and SPEC.loader is not None
updater = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = updater
SPEC.loader.exec_module(updater)
REVISION = "a" * 40


def current_payloads() -> dict[str, bytes]:
    registry = json.loads((ROOT / updater.REGISTRY).read_text(encoding="utf-8"))
    paths = set(updater.LEGACY_CORE)
    for item in registry["capabilities"]:
        if item["enabled"]:
            paths.update(item["package_files"])
    return {name: (ROOT / name).read_bytes() for name in sorted(paths) if name != updater.MANIFEST}


def snapshot(payloads: dict[str, bytes], version: str) -> object:
    registry = json.loads(payloads[updater.REGISTRY])
    skills = ["yetong", *(item["id"] for item in registry["capabilities"] if item["enabled"])]
    hashes = {name: updater.sha256(data) for name, data in sorted(payloads.items())}
    manifest = {
        "schema_version": 1, "repository": updater.REPOSITORY, "branch": updater.BRANCH,
        "version": version, "entry_skill": "yetong", "skills": skills, "files_sha256": hashes,
        "source_fingerprint": updater.sha256(json.dumps(hashes, sort_keys=True).encode("utf-8")),
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    updater.parse_manifest(manifest_bytes)
    updater.validate_payloads(manifest, payloads)
    return updater.Snapshot(REVISION, manifest, manifest_bytes, dict(payloads))


def install(root: Path, source: object) -> None:
    for name, data in {**source.payloads, updater.MANIFEST: source.manifest_bytes}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def archived(source: object, extra: tuple[str, str] | None = None) -> bytes:
    stream = io.BytesIO()
    prefix = f"yetong-fitness-xhs-{REVISION}"
    with tarfile.open(fileobj=stream, mode="w:gz") as output:
        for name, data in {**source.payloads, updater.MANIFEST: source.manifest_bytes}.items():
            info = tarfile.TarInfo(f"{prefix}/{name}")
            info.size = len(data)
            output.addfile(info, io.BytesIO(data))
        if extra is not None:
            name, kind = extra
            info = tarfile.TarInfo(f"{prefix}/{name}")
            if kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = "/tmp/other"
                output.addfile(info)
            else:
                info.size = 1
                output.addfile(info, io.BytesIO(b"x"))
    return stream.getvalue()


def future_payloads(payloads: dict[str, bytes]) -> dict[str, bytes]:
    result = dict(payloads)
    identifier = "yetong-followup"
    entry = f"{identifier}/SKILL.md"
    license_path = f"{identifier}/references/LICENSE"
    result[entry] = f"---\nname: {identifier}\ndescription: Test future registered update member.\n---\n\n# Future member\n".encode()
    result[license_path] = (ROOT / "LICENSE").read_bytes()
    registry = json.loads(result[updater.REGISTRY])
    registry["capabilities"].append({
        "id": identifier, "service_line": "shared", "menu_label": "未来模块", "menu_trigger": f"使用 ${identifier}",
        "entry": entry, "package_files": [entry, license_path], "purpose": "测试新增成员更新", "use_when": ["测试未来模块"],
        "avoid_when": [], "profile_requirement": "none", "required_any_of": [], "produces": ["future_result"],
        "offer_fit": "测试本地会员服务", "profile_check": None, "priority": 20, "enabled": True,
    })
    result[updater.REGISTRY] = (json.dumps(registry, ensure_ascii=False, indent=2) + "\n").encode()
    return result


class UpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="yetong-update-test-")
        self.parent = Path(self.temporary.name)
        self.target = self.parent / "skills"
        self.target.mkdir()
        payloads = current_payloads()
        self.new = snapshot(payloads, "test-new")
        old_payloads = dict(payloads)
        old_payloads["yetong-topic/SKILL.md"] += b"\nold revision\n"
        self.old = snapshot(old_payloads, "test-old")
        install(self.target, self.old)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def file_map(self) -> dict[str, bytes]:
        return {path.relative_to(self.target).as_posix(): path.read_bytes() for path in self.target.rglob("*") if path.is_file()}

    def test_update_preserves_private_extra_and_unrelated_skills(self) -> None:
        private = self.target / "yetong-dna/person-dna.md"
        private.write_text("private confirmed profile", encoding="utf-8")
        unrelated = self.target / "yetong-self-media/SKILL.md"
        unrelated.parent.mkdir()
        unrelated.write_text("unrelated personal skill", encoding="utf-8")
        result = updater.apply_snapshot(self.target, self.new)
        self.assertEqual(result["status"], "updated")
        self.assertTrue(result["verified"])
        self.assertEqual(private.read_text(), "private confirmed profile")
        self.assertEqual(unrelated.read_text(), "unrelated personal skill")
        self.assertTrue((Path(result["backup"]) / "files/yetong-topic/SKILL.md").is_file())
        self.assertFalse((Path(result["backup"]) / "files/yetong-dna/person-dna.md").exists())
        self.assertFalse((self.target / ".yetong-update.lock").exists())

    def test_unchanged_check_and_same_version_corruption_repairs(self) -> None:
        install(self.target, self.new)
        before = self.file_map()
        result = updater.plan_update(self.target, self.new)
        self.assertEqual(result["status"], "up_to_date")
        updater.verify_install(self.target, self.new)
        self.assertEqual(before, self.file_map())
        path = self.target / "yetong-copy/SKILL.md"
        path.write_bytes(b"damaged")
        self.assertEqual(updater.plan_update(self.target, self.new)["status"], "repair_needed")
        result = updater.apply_snapshot(self.target, self.new)
        self.assertTrue(result["verified"])
        self.assertEqual(path.read_bytes(), self.new.payloads["yetong-copy/SKILL.md"])

    def test_corrupted_snapshot_hash_rejected_without_mutation(self) -> None:
        before = self.file_map()
        self.new.payloads["yetong-copy/SKILL.md"] = b"corrupt upstream bytes"
        with self.assertRaisesRegex(updater.UpdateError, "哈希错误"):
            updater.apply_snapshot(self.target, self.new)
        self.assertEqual(before, self.file_map())

    def test_tar_traversal_and_symlink_rejected(self) -> None:
        for extra in (("../escape", "file"), ("yetong/scripts/alias", "symlink")):
            with self.subTest(extra=extra):
                with self.assertRaises(updater.UpdateError):
                    updater.snapshot_from_archive(archived(self.new, extra), REVISION)
        valid = updater.snapshot_from_archive(archived(self.new), REVISION)
        self.assertEqual(valid.manifest["source_fingerprint"], self.new.manifest["source_fingerprint"])

    def test_unknown_file_conflict_is_not_overwritten(self) -> None:
        payloads = dict(self.new.payloads)
        new_file = "yetong-copy/references/new-resource.md"
        payloads[new_file] = b"new official resource"
        future = snapshot(payloads, "test-future")
        existing = self.target / new_file
        existing.write_bytes(b"user-owned resource")
        before = self.file_map()
        with self.assertRaisesRegex(updater.UpdateError, "未知文件冲突"):
            updater.apply_snapshot(self.target, future)
        self.assertEqual(before, self.file_map())

    def test_failed_post_validation_rolls_back_original_files(self) -> None:
        future = snapshot(future_payloads(self.new.payloads), "test-future")
        before = self.file_map()
        with patch.object(updater, "verify_install", side_effect=updater.UpdateError("injected validation failure")):
            with self.assertRaisesRegex(updater.UpdateError, "已恢复"):
                updater.apply_snapshot(self.target, future)
        self.assertEqual(before, self.file_map())
        self.assertFalse((self.target / "yetong-followup").exists())

    def test_failed_file_write_rolls_back(self) -> None:
        before = self.file_map()
        original_write = updater.atomic_write
        calls = 0

        def fail_once(path: Path, content: bytes, mode: int = 0o644) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected write failure")
            original_write(path, content, mode)

        with patch.object(updater, "atomic_write", side_effect=fail_once):
            with self.assertRaisesRegex(updater.UpdateError, "已恢复"):
                updater.apply_snapshot(self.target, self.new)
        self.assertEqual(before, self.file_map())

    def test_new_registered_module_is_installed_dynamically(self) -> None:
        future = snapshot(future_payloads(self.new.payloads), "test-future")
        result = updater.apply_snapshot(self.target, future)
        self.assertEqual(result["new_skills"], ["yetong-followup"])
        self.assertTrue((self.target / "yetong-followup/SKILL.md").is_file())

    def test_unknown_same_name_directory_and_external_symlink_stop(self) -> None:
        future = snapshot(future_payloads(self.new.payloads), "test-future")
        conflict = self.target / "yetong-followup"
        conflict.mkdir()
        (conflict / "notes.md").write_bytes(b"user directory")
        with self.assertRaisesRegex(updater.UpdateError, "未知目录冲突"):
            updater.apply_snapshot(self.target, future)
        external = self.parent / "elsewhere"
        external.mkdir()
        member = self.target / "yetong-topic"
        saved = self.parent / "original-topic"
        member.rename(saved)
        member.symlink_to(external, target_is_directory=True)
        with self.assertRaises(updater.UpdateError):
            updater.plan_update(self.target, self.new)
        self.assertEqual(list(external.iterdir()), [])

    def test_legacy_registry_bootstrap_preserves_extra(self) -> None:
        (self.target / updater.MANIFEST).unlink()
        extra = self.target / "yetong/person-dna.md"
        extra.write_bytes(b"private legacy profile")
        result = updater.apply_snapshot(self.target, self.new)
        self.assertTrue(result["verified"])
        self.assertEqual(extra.read_bytes(), b"private legacy profile")
        self.assertEqual(updater.parse_manifest((self.target / updater.MANIFEST).read_bytes())["version"], "test-new")

    def test_obsolete_module_directory_is_preserved_and_reported(self) -> None:
        previous = snapshot(future_payloads(self.old.payloads), "test-previous")
        install(self.target, previous)
        result = updater.apply_snapshot(self.target, self.new)
        self.assertEqual(result["obsolete_skills_preserved"], ["yetong-followup"])
        self.assertTrue((self.target / "yetong-followup/SKILL.md").exists())

    def test_developer_source_root_is_rejected(self) -> None:
        (self.target / ".git").mkdir()
        with self.assertRaisesRegex(updater.UpdateError, "源码工作区"):
            updater.plan_update(self.target, self.new)

    def test_registered_directory_replaced_with_another_skill_stops(self) -> None:
        replacement = self.target / "yetong-copy/SKILL.md"
        replacement.write_bytes(b"---\nname: unrelated-copy\ndescription: user replacement\n---\n")
        before = self.file_map()
        with self.assertRaisesRegex(updater.UpdateError, "其他名称的技能占用"):
            updater.apply_snapshot(self.target, self.new)
        self.assertEqual(before, self.file_map())


if __name__ == "__main__":
    unittest.main()
