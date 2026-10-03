#!/usr/bin/env python3
"""Build and verify a strictly allowlisted local bundle; never publish or install it."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = "yetong-fitness-xhs-bundle"
VERSION = "0.2.0-preview"
REGISTRY_FILE = "yetong-fitness-xhs/references/capability-registry.json"
CORE_FILES = (
    "LICENSE",
    "README.md",
    "packaging/PACKAGE.md",
    "yetong-fitness-xhs/SKILL.md",
    "yetong-fitness-xhs/references/LICENSE",
    "yetong-fitness-xhs/agents/openai.yaml",
    "yetong-fitness-xhs/references/routing-contract.md",
    REGISTRY_FILE,
    "yetong-fitness-xhs/scripts/validate_registry.py",
)
BLOCKED_BYTES = (
    b"/Users/",
    b"private-profiles/",
)
MARKDOWN_LINK = re.compile(r"\]\(([^)]+)\)")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def archive_name(source_name: str) -> str:
    if source_name == "packaging/PACKAGE.md":
        return f"{ARCHIVE_ROOT}/PACKAGE.md"
    return f"{ARCHIVE_ROOT}/{source_name}"


def registered_files() -> tuple[list[str], list[str]]:
    subprocess.run(
        [sys.executable, str(ROOT / "yetong-fitness-xhs/scripts/validate_registry.py")],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    registry = json.loads((ROOT / REGISTRY_FILE).read_text(encoding="utf-8"))
    enabled = [item for item in registry["capabilities"] if item["enabled"]]
    module_ids = [item["id"] for item in enabled]
    source_files = list(CORE_FILES)
    for item in enabled:
        if f"{item['id']}/references/LICENSE" not in item["package_files"]:
            raise ValueError(f"registered skill lacks packaged license: {item['id']}")
        source_files.extend(item["package_files"])
    if len(source_files) != len(set(source_files)):
        raise ValueError("bundle source list contains duplicate paths")
    return module_ids, source_files


def collect(source_files: list[str]) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    for source_name in source_files:
        relative = Path(source_name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe source path: {source_name}")
        source = ROOT / relative
        if source.is_symlink() or not source.is_file() or ROOT not in source.resolve().parents:
            raise ValueError(f"missing or unsafe source file: {source_name}")
        data = source.read_bytes()
        data.decode("utf-8")
        if any(marker in data for marker in BLOCKED_BYTES):
            raise ValueError(f"private path or PDF reference found in: {source_name}")
        payloads[archive_name(source_name)] = data
    root_license = payloads[f"{ARCHIVE_ROOT}/LICENSE"]
    for source_name in source_files:
        if source_name.endswith("/references/LICENSE") and payloads[archive_name(source_name)] != root_license:
            raise ValueError(f"skill license differs from root license: {source_name}")
    included = set(source_files)
    for source_name in source_files:
        if not source_name.endswith(".md"):
            continue
        content = (ROOT / source_name).read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(content):
            target = unquote(raw_target.split("#", 1)[0].strip())
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            if target.startswith("/"):
                raise ValueError(f"absolute Markdown link in: {source_name}")
            referenced = (ROOT / source_name).parent / target
            resolved = referenced.resolve()
            if ROOT not in resolved.parents or not resolved.is_file():
                raise ValueError(f"broken local Markdown link: {source_name} -> {target}")
            relative = resolved.relative_to(ROOT).as_posix()
            if relative not in included:
                raise ValueError(f"unpackaged Markdown reference: {source_name} -> {target}")
    return payloads


def zip_info(name: str) -> ZipInfo:
    info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    return info


def verify(archive: Path, payloads: dict[str, bytes], manifest_data: bytes) -> None:
    expected = dict(payloads)
    expected[f"{ARCHIVE_ROOT}/MANIFEST.json"] = manifest_data
    with ZipFile(archive) as bundle:
        names = bundle.namelist()
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise ValueError("archive contains missing, duplicate or unexpected files")
        for name, content in expected.items():
            if bundle.read(name) != content:
                raise ValueError(f"archive content mismatch: {name}")


def main() -> None:
    module_ids, source_files = registered_files()
    payloads = collect(source_files)
    file_hashes = {name: sha256(data) for name, data in sorted(payloads.items())}
    fingerprint = sha256(json.dumps(file_hashes, sort_keys=True).encode("utf-8"))
    manifest = {
        "bundle": ARCHIVE_ROOT,
        "version": VERSION,
        "entry_skill": "yetong-fitness-xhs",
        "required_skills": ["yetong-fitness-xhs", *module_ids],
        "source_fingerprint": fingerprint,
        "files_sha256": file_hashes,
        "excludes": ["private profiles", "source PDF", "real coach test records", "development evals"],
        "status": "local preview; isolated installation verified; not published",
    }
    manifest_data = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    output_dir = ROOT / "dist"
    output_dir.mkdir(exist_ok=True)
    archive = output_dir / f"{ARCHIVE_ROOT}-{VERSION}-{fingerprint[:12]}.zip"
    if not archive.exists():
        with ZipFile(archive, mode="x") as bundle:
            for name, data in sorted(payloads.items()):
                bundle.writestr(zip_info(name), data)
            bundle.writestr(zip_info(f"{ARCHIVE_ROOT}/MANIFEST.json"), manifest_data)
    verify(archive, payloads, manifest_data)
    print(f"verified: {archive}")
    print(f"files: {len(payloads)} runtime/document files + 1 manifest")
    print(f"fingerprint: {fingerprint}")


if __name__ == "__main__":
    main()
