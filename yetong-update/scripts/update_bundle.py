#!/usr/bin/env python3
"""Update one installed YETONG instance from its pinned public GitHub snapshot."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote


REPOSITORY = "yetongzhu463-stack/yetong-fitness-xhs"
BRANCH = "main"
MANIFEST = "yetong/references/release-manifest.json"
REGISTRY = "yetong/references/capability-registry.json"
DEFAULT_TARGET = Path(__file__).resolve().parents[2]
MAX_DOWNLOAD = 8 * 1024 * 1024
MAX_EXPANDED = 24 * 1024 * 1024
MAX_FILE = 3 * 1024 * 1024
MAX_ENTRIES = 1000
SLUG = re.compile(r"^yetong(?:-[a-z0-9]+)*$")
SHA = re.compile(r"^[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")
LINK = re.compile(r"\]\(([^)]+)\)")
LEGACY_CORE = {
    "yetong/SKILL.md", "yetong/agents/openai.yaml", "yetong/references/LICENSE",
    "yetong/references/routing-contract.md", REGISTRY,
    "yetong/scripts/show_menu.py", "yetong/scripts/validate_registry.py",
}


class UpdateError(Exception):
    """A rejected package or installation; no unsupported success claim."""


@dataclass
class Snapshot:
    revision: str
    manifest: dict
    manifest_bytes: bytes
    payloads: dict[str, bytes]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def relative_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise UpdateError("发布路径为空或包含非法字符")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise UpdateError(f"拒绝不安全路径：{value}")
    return path


def parse_manifest(data: bytes) -> dict:
    try:
        manifest = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise UpdateError("发布清单不是有效 UTF-8 JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise UpdateError("发布清单 schema_version 必须为 1")
    if manifest.get("repository") != REPOSITORY or manifest.get("branch") != BRANCH:
        raise UpdateError("发布清单仓库或分支不匹配固定更新源")
    if manifest.get("entry_skill") != "yetong" or not isinstance(manifest.get("version"), str) or not manifest["version"].strip():
        raise UpdateError("发布清单缺少正确主入口或版本")
    skills = manifest.get("skills")
    if not isinstance(skills, list) or not skills or skills[0] != "yetong":
        raise UpdateError("发布清单缺少主入口技能组")
    if any(not isinstance(item, str) or not SLUG.fullmatch(item) for item in skills) or len(skills) != len(set(skills)):
        raise UpdateError("发布清单技能名非法或重复")
    hashes = manifest.get("files_sha256")
    if not isinstance(hashes, dict) or not hashes or len(hashes) > MAX_ENTRIES:
        raise UpdateError("发布清单文件列表无效")
    for name, digest in hashes.items():
        path = relative_path(name)
        if len(path.parts) < 2 or path.parts[0] not in skills or name == MANIFEST:
            raise UpdateError(f"发布文件不在声明的技能目录或清单自引用：{name}")
        if not isinstance(digest, str) or not SHA.fullmatch(digest):
            raise UpdateError(f"文件 SHA-256 无效：{name}")
    for identifier in skills:
        if f"{identifier}/SKILL.md" not in hashes:
            raise UpdateError(f"发布清单遗漏技能入口：{identifier}")
    if not LEGACY_CORE.issubset(hashes):
        raise UpdateError("发布清单遗漏必要主入口运行文件")
    fingerprint = sha256(json.dumps(hashes, sort_keys=True).encode("utf-8"))
    if manifest.get("source_fingerprint") != fingerprint:
        raise UpdateError("发布清单内容指纹不匹配")
    return manifest


def skill_name(content: bytes) -> str:
    try:
        text = content.decode("utf-8")
    except UnicodeError as exc:
        raise UpdateError("Skill 入口不是 UTF-8") from exc
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        raise UpdateError("Skill 缺少 frontmatter")
    for line in match.group(1).splitlines():
        if line.startswith("name:"):
            return line.partition(":")[2].strip().strip("\"'")
    raise UpdateError("Skill 缺少 name")


def validate_payloads(manifest: dict, payloads: dict[str, bytes]) -> None:
    hashes = manifest["files_sha256"]
    if set(payloads) != set(hashes):
        raise UpdateError("快照运行文件与发布清单不一致")
    for name, content in payloads.items():
        if len(content) > MAX_FILE or sha256(content) != hashes[name]:
            raise UpdateError(f"运行文件过大或哈希错误：{name}")
    for identifier in manifest["skills"]:
        if skill_name(payloads[f"{identifier}/SKILL.md"]) != identifier:
            raise UpdateError(f"目录与 Skill 名称不一致：{identifier}")
    try:
        registry = json.loads(payloads[REGISTRY].decode("utf-8"))
    except (KeyError, UnicodeError, json.JSONDecodeError) as exc:
        raise UpdateError("缺少有效能力登记表") from exc
    if not isinstance(registry, dict) or registry.get("schema_version") != 2:
        raise UpdateError("能力登记表 schema_version 无效")
    capabilities = registry.get("capabilities")
    if not isinstance(capabilities, list):
        raise UpdateError("能力登记表缺少 capabilities")
    lines = registry.get("service_lines")
    if not isinstance(lines, list) or len(lines) != 3 or any(not isinstance(line, dict) for line in lines):
        raise UpdateError("能力登记表缺少三条服务线")
    statuses = {line.get("id"): line.get("status") for line in lines}
    if set(statuses) != {"content", "moments", "performance"} or any(status not in {"active", "planned"} for status in statuses.values()):
        raise UpdateError("能力登记表服务线状态无效")
    enabled: list[str] = []
    seen: set[str] = set()
    profile_producers = 0
    for item in capabilities:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not SLUG.fullmatch(item["id"]) or item["id"] in seen:
            raise UpdateError("能力登记表模块名无效或重复")
        identifier = item["id"]
        seen.add(identifier)
        if type(item.get("enabled")) is not bool:
            raise UpdateError(f"能力启用状态无效：{identifier}")
        entry = item.get("entry")
        files = item.get("package_files")
        if entry != f"{identifier}/SKILL.md" or not isinstance(files, list) or any(not isinstance(name, str) for name in files) or entry not in files or len(files) != len(set(files)):
            raise UpdateError(f"能力入口或文件列表无效：{identifier}")
        for name in files:
            if relative_path(name).parts[0] != identifier or (item["enabled"] and name not in hashes):
                raise UpdateError(f"能力文件未发布或越界：{name}")
        requirement = item.get("profile_requirement")
        if requirement not in {"none", "optional", "active"}:
            raise UpdateError(f"人物门槛无效：{identifier}")
        if requirement in {"active", "optional"}:
            gate = item.get("profile_check")
            if not isinstance(gate, str) or not gate.startswith(f"{identifier}/scripts/") or gate not in files:
                raise UpdateError(f"能力遗漏人物档案检查脚本：{identifier}")
        elif item.get("profile_check") is not None:
            raise UpdateError(f"无需人物门槛的能力声明了检查脚本：{identifier}")
        service_line = item.get("service_line")
        if service_line != "shared" and service_line not in statuses:
            raise UpdateError(f"能力声明了未登记服务线：{identifier}")
        if item["enabled"]:
            if service_line != "shared" and statuses[service_line] != "active":
                raise UpdateError(f"规划中服务线不能启用模块：{identifier}")
            enabled.append(identifier)
            if "active_profile" in item.get("produces", []):
                profile_producers += 1
                if requirement != "none":
                    raise UpdateError("人物建档能力不能要求已激活档案")
    if profile_producers != 1:
        raise UpdateError("能力登记表必须有一个启用的建档能力")
    if set(enabled) != set(manifest["skills"]) - {"yetong"}:
        raise UpdateError("发布清单与能力登记表成员不一致")
    for name, content in payloads.items():
        if not name.endswith(".md"):
            continue
        try:
            text = content.decode("utf-8")
        except UnicodeError as exc:
            raise UpdateError(f"Markdown 文件不是 UTF-8：{name}") from exc
        for raw in LINK.findall(text):
            target = unquote(raw.split("#", 1)[0].strip().strip("<>"))
            if not target or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                continue
            if target.startswith("/") or "\\" in target:
                raise UpdateError(f"运行文档含非法本地引用：{name}")
            joined = PurePosixPath(name).parent / target
            normalized: list[str] = []
            for part in joined.parts:
                if part == "..":
                    if not normalized:
                        raise UpdateError(f"运行文档引用越界：{name}")
                    normalized.pop()
                elif part != ".":
                    normalized.append(part)
            if "/".join(normalized) not in hashes and "/".join(normalized) != MANIFEST:
                raise UpdateError(f"运行文档引用未发布文件：{name} -> {target}")


def read_url(url: str, limit: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "YETONG-Skill-Updater/1", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise UpdateError("远端响应超过允许大小")
    return data


def snapshot_from_archive(data: bytes, revision: str) -> Snapshot:
    if not REVISION.fullmatch(revision) or len(data) > MAX_DOWNLOAD:
        raise UpdateError("快照提交号无效或下载过大")
    prefix = f"{REPOSITORY.rsplit('/', 1)[1]}-{revision}"
    extracted: dict[str, bytes] = {}
    count = 0
    expanded = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r|gz") as archive:
            for member in archive:
                count += 1
                if count > MAX_ENTRIES:
                    raise UpdateError("快照目录项过多")
                name = member.name.rstrip("/")
                path = relative_path(name)
                if path.parts[0] != prefix:
                    raise UpdateError("快照目录与固定提交不一致")
                if not member.isdir() and not member.isfile():
                    raise UpdateError(f"快照包含链接或特殊文件：{name}")
                if member.isdir():
                    continue
                if len(path.parts) < 2 or member.size < 0 or member.size > MAX_FILE:
                    raise UpdateError("快照文件路径或大小无效")
                expanded += member.size
                if expanded > MAX_EXPANDED:
                    raise UpdateError("快照解压后超过允许大小")
                relative = "/".join(path.parts[1:])
                if relative in extracted:
                    raise UpdateError(f"快照包含重复文件：{relative}")
                source = archive.extractfile(member)
                if source is None:
                    raise UpdateError(f"无法读取快照文件：{relative}")
                content = source.read(MAX_FILE + 1)
                if len(content) != member.size:
                    raise UpdateError(f"快照文件截断：{relative}")
                extracted[relative] = content
    except (tarfile.TarError, EOFError) as exc:
        raise UpdateError("远端快照不是完整 tar.gz") from exc
    manifest_bytes = extracted.get(MANIFEST)
    if manifest_bytes is None:
        raise UpdateError("远端尚未发布更新清单；请先用宿主原安装方式重新安装")
    manifest = parse_manifest(manifest_bytes)
    missing = set(manifest["files_sha256"]) - extracted.keys()
    if missing:
        raise UpdateError(f"远端快照缺少声明文件：{sorted(missing)}")
    payloads = {name: extracted[name] for name in manifest["files_sha256"]}
    validate_payloads(manifest, payloads)
    return Snapshot(revision, manifest, manifest_bytes, payloads)


def fetch_snapshot() -> Snapshot:
    try:
        response = json.loads(read_url(f"https://api.github.com/repos/{REPOSITORY}/commits/{BRANCH}", 256 * 1024))
        revision = response.get("sha", "") if isinstance(response, dict) else ""
        if not isinstance(revision, str) or not REVISION.fullmatch(revision):
            raise UpdateError("GitHub 没有返回有效提交号")
        data = read_url(f"https://codeload.github.com/{REPOSITORY}/tar.gz/{revision}", MAX_DOWNLOAD)
        return snapshot_from_archive(data, revision)
    except (OSError, ValueError) as exc:
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError(f"无法取得官方更新快照：{exc}") from exc


def installation_root(target: Path) -> Path:
    target = target.expanduser().resolve()
    if not target.is_dir():
        raise UpdateError("目标不是已存在的 Skills 安装目录")
    if (target / ".git").exists():
        raise UpdateError("目标是维护者源码工作区；请使用实际安装后的 Skills 目录")
    if any(part in {".codex-plugin", "plugins"} for part in target.parts):
        raise UpdateError("目标属于宿主插件目录；请通过宿主插件更新入口处理")
    return target


def safe_target(root: Path, name: str) -> Path:
    relative = relative_path(name)
    candidate = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise UpdateError(f"安装目标包含链接，未写入：{name}")
        if current.exists() and current != candidate and not current.is_dir():
            raise UpdateError(f"安装路径父级不是目录：{name}")
    if root not in candidate.resolve().parents:
        raise UpdateError(f"安装目标越出本实例：{name}")
    if candidate.exists() and not candidate.is_file():
        raise UpdateError(f"安装目标不是普通文件：{name}")
    return candidate


def old_ownership(root: Path) -> tuple[set[str], set[str], str | None]:
    manifest_file = safe_target(root, MANIFEST)
    if manifest_file.exists():
        manifest = parse_manifest(manifest_file.read_bytes())
        for identifier in manifest["skills"]:
            entry = safe_target(root, f"{identifier}/SKILL.md")
            if entry.exists():
                try:
                    existing_name = skill_name(entry.read_bytes())
                except UpdateError:
                    # A missing or damaged managed entry can be repaired by its manifest.
                    continue
                if existing_name != identifier:
                    raise UpdateError(f"既有目录被其他名称的技能占用，未覆盖：{identifier}")
        return set(manifest["files_sha256"]) | {MANIFEST}, set(manifest["skills"]), manifest["version"]
    entry = safe_target(root, "yetong/SKILL.md")
    registry_file = safe_target(root, REGISTRY)
    if not entry.is_file() or skill_name(entry.read_bytes()) != "yetong" or not registry_file.is_file():
        raise UpdateError("未识别为本包的既有安装；请先完整安装 YETONG")
    try:
        registry = json.loads(registry_file.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise UpdateError("旧版登记表损坏，无法安全确认文件归属") from exc
    if not isinstance(registry, dict) or registry.get("schema_version") != 2 or not isinstance(registry.get("capabilities"), list):
        raise UpdateError("旧版登记表无效，无法安全确认文件归属")
    owned = set(LEGACY_CORE)
    modules = {"yetong"}
    for item in registry["capabilities"]:
        if not isinstance(item, dict) or type(item.get("enabled")) is not bool:
            raise UpdateError("旧版登记项无效")
        if not item["enabled"]:
            continue
        identifier = item.get("id")
        if not isinstance(identifier, str) or not SLUG.fullmatch(identifier) or identifier in modules:
            raise UpdateError("旧版模块名无效或重复")
        files = item.get("package_files")
        if not isinstance(files, list) or any(not isinstance(name, str) for name in files) or item.get("entry") != f"{identifier}/SKILL.md" or item["entry"] not in files:
            raise UpdateError("旧版模块文件归属不清")
        existing_entry = safe_target(root, item["entry"])
        if existing_entry.exists() and skill_name(existing_entry.read_bytes()) != identifier:
            raise UpdateError(f"旧版目录已被其他技能占用：{identifier}")
        for name in files:
            if relative_path(name).parts[0] != identifier:
                raise UpdateError("旧登记表列出其他模块文件")
            safe_target(root, name)
            owned.add(name)
        modules.add(identifier)
    return owned, modules, None


def plan_update(root: Path, snapshot: Snapshot) -> dict:
    root = installation_root(root)
    if parse_manifest(snapshot.manifest_bytes) != snapshot.manifest:
        raise UpdateError("快照清单字节与已解析内容不一致")
    validate_payloads(snapshot.manifest, snapshot.payloads)
    owned, old_modules, old_version = old_ownership(root)
    desired = {**snapshot.payloads, MANIFEST: snapshot.manifest_bytes}
    changes: list[str] = []
    for identifier in snapshot.manifest["skills"]:
        directory = root / identifier
        if directory.is_symlink():
            raise UpdateError(f"模块链接指向其他安装位置，请以其共同真实目录更新：{identifier}")
        if directory.exists() and (not directory.is_dir() or identifier not in old_modules):
            raise UpdateError(f"新增模块与未知目录冲突，未覆盖：{identifier}")
    for name, data in desired.items():
        path = safe_target(root, name)
        if path.exists() and name not in owned:
            raise UpdateError(f"新运行文件与未知文件冲突，未覆盖：{name}")
        if not path.exists() or path.read_bytes() != data:
            changes.append(name)
    if not changes:
        status = "up_to_date"
    elif old_version == snapshot.manifest["version"]:
        status = "repair_needed"
    else:
        status = "update_available"
    return {
        "status": status, "root": str(root), "current_version": old_version or "legacy",
        "version": snapshot.manifest["version"], "revision": snapshot.revision,
        "source_fingerprint": snapshot.manifest["source_fingerprint"], "changes": changes,
        "new_skills": sorted(set(snapshot.manifest["skills"]) - old_modules),
        "obsolete_skills_preserved": sorted(old_modules - set(snapshot.manifest["skills"])),
    }


def verify_install(root: Path, snapshot: Snapshot) -> None:
    root = installation_root(root)
    actual: dict[str, bytes] = {}
    for name in snapshot.payloads:
        path = safe_target(root, name)
        if not path.is_file():
            raise UpdateError(f"更新后缺少文件：{name}")
        actual[name] = path.read_bytes()
    validate_payloads(snapshot.manifest, actual)
    if safe_target(root, MANIFEST).read_bytes() != snapshot.manifest_bytes:
        raise UpdateError("更新后发布清单不一致")
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    for script in ("validate_registry.py", "show_menu.py"):
        result = subprocess.run(
            [sys.executable, str(root / "yetong/scripts" / script), "--root", str(root)],
            capture_output=True, text=True, check=False, timeout=30, env=environment,
        )
        if result.returncode != 0:
            raise UpdateError(f"更新后 {script} 校验失败：{(result.stdout + result.stderr)[-1200:]}")


def atomic_write(destination: Path, data: bytes, mode: int = 0o644) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".yetong-file-", dir=destination.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def apply_snapshot(target: Path, snapshot: Snapshot) -> dict:
    root = installation_root(target)
    lock = root / ".yetong-update.lock"
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise UpdateError("另一更新正在执行，或上次中断留下更新锁；确认没有运行任务后再处理锁目录") from exc
    backup: Path | None = None
    created_directories: list[Path] = []
    touched: list[str] = []
    original: dict[str, bool] = {}
    desired = {**snapshot.payloads, MANIFEST: snapshot.manifest_bytes}
    try:
        plan = plan_update(root, snapshot)
        if not plan["changes"]:
            verify_install(root, snapshot)
            plan["verified"] = True
            return plan
        backup_parent = root.parent / ".yetong-update-backups"
        if backup_parent.is_symlink():
            raise UpdateError("更新备份目录不能是链接")
        backup_parent.mkdir(mode=0o700, exist_ok=True)
        backup = Path(tempfile.mkdtemp(prefix="transaction-", dir=backup_parent))
        for name in plan["changes"]:
            path = safe_target(root, name)
            original[name] = path.exists()
            if path.exists():
                saved = backup / "files" / name
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, saved)
        (backup / "transaction.json").write_text(
            json.dumps({"root": str(root), "revision": snapshot.revision, "original": original}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        for name in plan["changes"]:
            path = safe_target(root, name)
            missing: list[Path] = []
            parent = path.parent
            while parent != root and not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for directory in reversed(missing):
                directory.mkdir()
                created_directories.append(directory)
            mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
            touched.append(name)
            atomic_write(path, desired[name], mode)
        verify_install(root, snapshot)
        plan["status"] = "updated"
        plan["verified"] = True
        plan["backup"] = str(backup)
        return plan
    except BaseException as exc:
        rollback_errors: list[str] = []
        if backup is not None:
            for name in reversed(touched):
                try:
                    path = safe_target(root, name)
                    if original[name]:
                        saved = backup / "files" / name
                        atomic_write(path, saved.read_bytes(), stat.S_IMODE(saved.stat().st_mode))
                    elif path.exists():
                        path.unlink()
                except (OSError, UpdateError) as rollback_exc:
                    rollback_errors.append(f"{name}: {rollback_exc}")
            for directory in reversed(created_directories):
                try:
                    directory.rmdir()
                except OSError:
                    pass
        if rollback_errors:
            raise UpdateError(f"更新失败且部分恢复未完成：{rollback_errors}；旧文件备份：{backup}") from exc
        if backup is not None:
            raise UpdateError(f"更新失败，已恢复本次触碰的旧文件：{exc}；备份：{backup}") from exc
        raise
    finally:
        lock.rmdir()


def main() -> int:
    parser = argparse.ArgumentParser(description="检查或更新当前安装实例的 YETONG 技能")
    parser.add_argument("action", choices=("check", "apply"))
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET, help="真实 Skills 安装根目录；默认定位当前脚本实例")
    args = parser.parse_args()
    try:
        root = installation_root(args.target)
        snapshot = fetch_snapshot()
        result = apply_snapshot(root, snapshot) if args.action == "apply" else plan_update(root, snapshot)
        if args.action == "check" and result["status"] == "up_to_date":
            verify_install(root, snapshot)
            result["verified"] = True
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, UpdateError, subprocess.TimeoutExpired) as exc:
        print(f"更新未完成：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
