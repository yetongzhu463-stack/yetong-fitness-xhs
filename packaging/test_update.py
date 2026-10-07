#!/usr/bin/env python3
"""Exercise update transactions in disposable directories, without network or global writes."""

from __future__ import annotations

import gzip
import importlib.util
import io
import json
import sys
import tarfile
import tempfile
import unittest
from contextlib import nullcontext
from http.client import IncompleteRead
from pathlib import Path
from urllib.error import HTTPError, URLError
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("yetong_updater_tested", ROOT / "yetong-update/scripts/update_bundle.py")
assert SPEC is not None and SPEC.loader is not None
updater = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = updater
SPEC.loader.exec_module(updater)
REVISION = "a" * 40
API_URL = f"https://api.github.com/repos/{updater.REPOSITORY}/commits/{updater.BRANCH}"
BRANCH_URL = f"https://codeload.github.com/{updater.REPOSITORY}/tar.gz/refs/heads/{updater.BRANCH}"
PINNED_URL = f"https://codeload.github.com/{updater.REPOSITORY}/tar.gz/{REVISION}"


def current_payloads() -> dict[str, bytes]:
    registry = json.loads((ROOT / updater.REGISTRY).read_text(encoding="utf-8"))
    paths = set(updater.LEGACY_CORE)
    for item in registry["capabilities"]:
        if item["enabled"]:
            paths.update(item["package_files"])
    return {name: (ROOT / name).read_bytes() for name in sorted(paths) if name != updater.MANIFEST}


def snapshot(payloads: dict[str, bytes], version: str, *, validate: bool = True) -> object:
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
    if validate:
        updater.validate_payloads(manifest, payloads)
    return updater.Snapshot(REVISION, manifest, manifest_bytes, dict(payloads))


def install(root: Path, source: object) -> None:
    for name, data in {**source.payloads, updater.MANIFEST: source.manifest_bytes}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def archived(source: object, extra: tuple[str, str] | None = None, *, prefix: str | None = None, pax_headers: dict[str, str] | None = None) -> bytes:
    stream = io.BytesIO()
    prefix = prefix or f"yetong-fitness-xhs-{REVISION}"
    with tarfile.open(fileobj=stream, mode="w:gz", format=tarfile.PAX_FORMAT, pax_headers=pax_headers) as output:
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


def revision_probe(metadata: bytes, *, size: int | None = None) -> bytes:
    header = tarfile.TarInfo("pax_global_header")
    header.type = tarfile.XGLTYPE
    header.size = len(metadata) if size is None else size
    return gzip.compress(header.tobuf(format=tarfile.USTAR_FORMAT) + metadata)


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

    def branch_archive(self, revision: str = REVISION) -> bytes:
        return archived(self.old, prefix="yetong-fitness-xhs-main", pax_headers={"comment": revision})

    def test_api_success_fetches_only_an_immutable_snapshot(self) -> None:
        with patch.object(updater, "read_url", side_effect=[json.dumps({"sha": REVISION}).encode(), archived(self.new)]) as read:
            result = updater.fetch_snapshot()
        self.assertEqual(result.revision, REVISION)
        self.assertEqual(result.payloads, self.new.payloads)
        self.assertEqual([call.args[0] for call in read.call_args_list], [API_URL, PINNED_URL])

    def test_api_rate_limit_403_falls_back_without_git_and_refetches_sha(self) -> None:
        rate_limit = HTTPError(API_URL, 403, "Forbidden", {"X-RateLimit-Remaining": "0"}, io.BytesIO(b'{"message":"API rate limit exceeded"}'))
        with patch.object(updater, "read_url", side_effect=[rate_limit, self.branch_archive(), archived(self.new)]) as read, patch.object(updater.subprocess, "run", side_effect=FileNotFoundError("no git")) as process:
            result = updater.fetch_snapshot()
        self.assertEqual(result.revision, REVISION)
        # The probe deliberately has old content; only the refetched SHA is used.
        self.assertEqual(result.payloads, self.new.payloads)
        self.assertEqual([call.args[0] for call in read.call_args_list], [API_URL, BRANCH_URL, PINNED_URL])
        process.assert_not_called()

    def test_incomplete_api_response_falls_back_to_verified_snapshot(self) -> None:
        broken = Mock()
        broken.read.side_effect = IncompleteRead(b"partial API", 100)
        branch = Mock()
        branch.read.return_value = self.branch_archive()
        pinned = Mock()
        pinned.read.return_value = archived(self.new)
        with patch.object(updater, "trusted_https_context", return_value=Mock()), patch.object(updater.urllib.request, "urlopen", side_effect=[nullcontext(broken), nullcontext(branch), nullcontext(pinned)]) as open_url:
            result = updater.fetch_snapshot()
        self.assertEqual(result.revision, REVISION)
        self.assertEqual(result.payloads, self.new.payloads)
        self.assertEqual([call.args[0].full_url for call in open_url.call_args_list], [API_URL, BRANCH_URL, PINNED_URL])

    def test_incomplete_probe_or_pinned_response_stops_before_writes(self) -> None:
        for failed_source in ("官方分支快照", "官方固定提交快照"):
            broken = Mock()
            broken.read.side_effect = IncompleteRead(b"partial archive", 100)
            forbidden = HTTPError(API_URL, 403, "Forbidden", {}, None)
            responses = [forbidden]
            if failed_source == "官方固定提交快照":
                branch = Mock()
                branch.read.return_value = self.branch_archive()
                responses.append(nullcontext(branch))
            responses.append(nullcontext(broken))
            before = self.file_map()
            with self.subTest(source=failed_source), patch.object(updater, "trusted_https_context", return_value=Mock()), patch.object(updater.urllib.request, "urlopen", side_effect=responses), patch.object(sys, "argv", ["update_bundle.py", "apply", "--target", str(self.target)]), patch.object(updater, "apply_snapshot") as apply, patch.object(sys, "stderr", new_callable=io.StringIO) as errors:
                self.assertEqual(updater.main(), 1)
                self.assertIn("更新未完成", errors.getvalue())
                self.assertIn(failed_source, errors.getvalue())
                self.assertIn("IncompleteRead", errors.getvalue())
                apply.assert_not_called()
            self.assertEqual(before, self.file_map())
            self.assertFalse((self.target / ".yetong-update.lock").exists())
            self.assertFalse((self.parent / ".yetong-update-backups").exists())

    def test_non_rate_limit_403_has_official_fallback_and_neutral_failure(self) -> None:
        forbidden = HTTPError(API_URL, 403, "Forbidden", {"X-RateLimit-Remaining": "42"}, io.BytesIO(b'{"message":"Resource not accessible by integration"}'))
        with patch.object(updater, "read_url", side_effect=[forbidden, self.branch_archive(), archived(self.new)]):
            self.assertEqual(updater.fetch_snapshot().revision, REVISION)
        forbidden = HTTPError(API_URL, 403, "Forbidden", {}, io.BytesIO(b'{"message":"Forbidden"}'))
        with patch.object(updater, "read_url", side_effect=[forbidden, URLError("official archive blocked")]):
            with self.assertRaises(updater.UpdateError) as failure:
                updater.fetch_snapshot()
        message = str(failure.exception)
        self.assertIn("GitHub API：HTTP Error 403", message)
        self.assertIn("官方分支快照", message)
        self.assertIn("official archive blocked", message)
        self.assertNotIn("限流", message)

    def test_malformed_api_revision_uses_independently_validated_probe(self) -> None:
        for value in (None, 42, REVISION + "0", "../main", "A" * 40, "b" * 39):
            with self.subTest(value=value), patch.object(updater, "read_url", side_effect=[json.dumps({"sha": value}).encode(), self.branch_archive(), archived(self.new)]) as read:
                self.assertEqual(updater.fetch_snapshot().revision, REVISION)
                self.assertEqual(read.call_args_list[-1].args[0], PINNED_URL)

    def test_probe_requires_unique_strict_commit_metadata(self) -> None:
        probes = [
            archived(self.new, prefix="yetong-fitness-xhs-main"),
            archived(self.new, pax_headers={"other": REVISION}),
            *(self.branch_archive(value) for value in ("", "None", "42", "['sha']", "A" * 40, "b" * 39, "b" * 41, "../main")),
            archived(self.new, pax_headers={"comment": "a" * 2048}),
            revision_probe(b"52 comment=" + REVISION.encode() + b"\n52 comment=" + REVISION.encode() + b"\n"),
            revision_probe(b"99999999999999999999 comment=bad\n"),
            revision_probe(b"52 comment=" + REVISION.encode(), size=52),
            b"not a gzip archive",
            b"\x1f\x8b\x08\x00" + b"\x00" * 6 + b"\x07",  # Invalid DEFLATE block.
            b"x" * (updater.MAX_DOWNLOAD + 1),
        ]
        for probe in probes:
            with self.subTest(probe_size=len(probe)), patch.object(updater, "read_url", side_effect=[URLError("API unavailable"), probe]) as read:
                with self.assertRaises(updater.UpdateError):
                    updater.fetch_snapshot()
                self.assertEqual(read.call_count, 2)
        self.assertEqual(updater.archive_revision(self.branch_archive()), REVISION)

    def test_branch_change_cannot_install_a_different_revision(self) -> None:
        before = self.file_map()
        mismatches = [
            archived(self.new, prefix=f"yetong-fitness-xhs-{'b' * 40}"),
            archived(self.new, pax_headers={"comment": "b" * 40}),
        ]
        for changed_archive in mismatches:
            with self.subTest(archive_size=len(changed_archive)), patch.object(updater, "read_url", side_effect=[URLError("API unavailable"), self.branch_archive(), changed_archive]) as read:
                with self.assertRaisesRegex(updater.UpdateError, "固定提交不一致"):
                    updater.fetch_snapshot()
            self.assertEqual(read.call_args_list[-1].args[0], PINNED_URL)
        self.assertEqual(before, self.file_map())

    def test_official_sources_fail_without_any_installation_write(self) -> None:
        failures = (
            [URLError("API offline"), URLError("archive offline")],
            [HTTPError(API_URL, 403, "Forbidden", {}, None), HTTPError(BRANCH_URL, 403, "Forbidden", {}, None)],
            [URLError("API offline"), self.branch_archive(), URLError("pinned archive offline")],
            [json.dumps({"sha": REVISION}).encode(), b"invalid pinned archive"],
        )
        for responses in failures:
            before = self.file_map()
            with self.subTest(responses=len(responses)), patch.object(updater, "read_url", side_effect=responses), patch.object(sys, "argv", ["update_bundle.py", "apply", "--target", str(self.target)]), patch.object(updater, "apply_snapshot") as apply, patch.object(sys, "stderr", new_callable=io.StringIO) as errors:
                self.assertEqual(updater.main(), 1)
                self.assertIn("更新未完成", errors.getvalue())
                apply.assert_not_called()
            self.assertEqual(before, self.file_map())
            self.assertFalse((self.target / ".yetong-update.lock").exists())
            self.assertFalse((self.parent / ".yetong-update-backups").exists())

    def test_invalid_remote_registry_field_types_stop_before_writes(self) -> None:
        cases = (
            ("service_lines", "id", []),
            ("service_lines", "status", []),
            ("capabilities", "profile_requirement", []),
            ("capabilities", "service_line", {}),
            ("capabilities", "produces", None),
            ("capabilities", "produces", "active_profile"),
            ("capabilities", "produces", [None]),
        )
        for section, key, value in cases:
            payloads = dict(self.new.payloads)
            registry = json.loads(payloads[updater.REGISTRY])
            registry[section][0][key] = value
            payloads[updater.REGISTRY] = json.dumps(registry).encode()
            damaged = snapshot(payloads, "damaged-registry", validate=False)
            before = self.file_map()
            with self.subTest(section=section, field=key, value=value), patch.object(updater, "read_url", side_effect=[json.dumps({"sha": REVISION}).encode(), archived(damaged)]), patch.object(sys, "argv", ["update_bundle.py", "apply", "--target", str(self.target)]), patch.object(updater, "apply_snapshot") as apply, patch.object(sys, "stderr", new_callable=io.StringIO) as errors:
                self.assertEqual(updater.main(), 1)
                self.assertIn("更新未完成", errors.getvalue())
                self.assertIn("官方固定提交快照", errors.getvalue())
                apply.assert_not_called()
            self.assertEqual(before, self.file_map())
            self.assertFalse((self.target / ".yetong-update.lock").exists())
            self.assertFalse((self.parent / ".yetong-update-backups").exists())

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

    def test_large_pax_metadata_and_compressed_bomb_stop_before_tar_parse(self) -> None:
        payloads = (
            archived(self.new, pax_headers={"comment": REVISION, "unused": "x" * (updater.MAX_EXPANDED + 1)}),
            gzip.compress(b"x" * (updater.MAX_EXPANDED + 1)),
        )
        for data in payloads:
            with self.subTest(compressed_bytes=len(data)), patch.object(updater.tarfile, "open") as parse_tar:
                self.assertLess(len(data), updater.MAX_DOWNLOAD)
                with self.assertRaisesRegex(updater.UpdateError, "解压后超过"):
                    updater.snapshot_from_archive(data, REVISION)
                parse_tar.assert_not_called()

    def test_truncated_or_corrupt_gzip_snapshot_is_rejected(self) -> None:
        data = archived(self.new, pax_headers={"comment": REVISION})
        bad_checksum = data[:-8] + bytes((data[-8] ^ 0xFF,)) + data[-7:]
        for broken in (data[:len(data) // 2], data[:-8], bad_checksum):
            with self.subTest(compressed_bytes=len(broken)):
                with self.assertRaisesRegex(updater.UpdateError, "不是完整 tar.gz"):
                    updater.snapshot_from_archive(broken, REVISION)
        self.assertEqual(updater.snapshot_from_archive(data, REVISION).payloads, self.new.payloads)

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

    def test_populated_default_tls_trust_is_unchanged(self) -> None:
        context = Mock()
        context.cert_store_stats.return_value = {"x509_ca": 120}
        with patch.object(updater.ssl, "create_default_context", return_value=context):
            self.assertIs(updater.trusted_https_context(), context)
        context.load_verify_locations.assert_not_called()

    def test_empty_default_tls_uses_existing_verified_system_bundle(self) -> None:
        context = Mock()
        context.cert_store_stats.side_effect = [{"x509_ca": 0}, {"x509_ca": 120}]
        with patch.object(updater.ssl, "create_default_context", return_value=context), patch.dict(updater.os.environ, {}, clear=True), patch.object(updater.Path, "is_file", return_value=True):
            self.assertIs(updater.trusted_https_context(), context)
        context.load_verify_locations.assert_called_once_with(cafile="/etc/ssl/cert.pem")

    def test_explicit_tls_configuration_is_honored(self) -> None:
        context = Mock()
        context.cert_store_stats.return_value = {"x509_ca": 0}
        with patch.object(updater.ssl, "create_default_context", return_value=context), patch.dict(updater.os.environ, {"SSL_CERT_DIR": "configured-ca-directory"}, clear=True):
            self.assertIs(updater.trusted_https_context(), context)
        context.load_verify_locations.assert_not_called()

    def test_no_tls_trust_returns_actionable_error(self) -> None:
        context = Mock()
        context.cert_store_stats.return_value = {"x509_ca": 0}
        with patch.object(updater.ssl, "create_default_context", return_value=context), patch.dict(updater.os.environ, {}, clear=True), patch.object(updater.Path, "is_file", return_value=False):
            with self.assertRaisesRegex(updater.UpdateError, "不会关闭证书校验"):
                updater.trusted_https_context()


if __name__ == "__main__":
    unittest.main()
