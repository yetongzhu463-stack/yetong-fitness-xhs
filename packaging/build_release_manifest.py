#!/usr/bin/env python3
"""Generate the public runtime-only release manifest consumed by yetong-update."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_bundle import ROOT, VERSION, registered_files, sha256


MANIFEST = "yetong/references/release-manifest.json"
REPOSITORY = "yetongzhu463-stack/yetong-fitness-xhs"


def generate() -> dict:
    identifiers, sources = registered_files()
    skills = ["yetong", *identifiers]
    hashes = {}
    for relative in sorted(sources):
        path = Path(relative)
        if relative == MANIFEST or path.parts[0] not in skills:
            continue
        source = ROOT / path
        if source.is_symlink() or not source.is_file() or ROOT not in source.resolve().parents:
            raise ValueError(f"unsafe runtime source: {relative}")
        hashes[relative] = sha256(source.read_bytes())
    return {
        "schema_version": 1,
        "repository": REPOSITORY,
        "branch": "main",
        "version": VERSION,
        "entry_skill": "yetong",
        "skills": skills,
        "files_sha256": hashes,
        "source_fingerprint": sha256(json.dumps(hashes, sort_keys=True).encode("utf-8")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="生成或检查 YETONG 公开运行文件更新清单")
    parser.add_argument("--check", action="store_true", help="只检查已生成清单是否匹配源文件")
    args = parser.parse_args()
    output = ROOT / MANIFEST
    content = json.dumps(generate(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.check:
        if not output.is_file() or output.read_text(encoding="utf-8") != content:
            raise SystemExit("发布清单与运行文件不一致；先运行 packaging/build_release_manifest.py")
        print("发布清单校验通过")
    else:
        output.write_text(content, encoding="utf-8")
        print(f"发布清单已生成：{MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
