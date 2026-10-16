#!/usr/bin/env python3
"""Mechanically mirror one public rule into each packaged skill; no private data."""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "yetong-topic/references/local-title-contract.md"
MIRROR_IDS = ("yetong", "yetong-dna", "yetong-copy", "yetong-review", "yetong-title", "yetong-cover", "yetong-promo", "yetong-timer", "yetong-remix")


def sync(*, check: bool) -> int:
    if SOURCE.is_symlink() or not SOURCE.is_file():
        raise ValueError("地区标题真源缺失或不是普通文件")
    content = SOURCE.read_bytes()
    if b"/Users/" in content or b"private-profiles/" in content:
        raise ValueError("地区标题真源包含私人路径")
    mismatches = []
    for identifier in MIRROR_IDS:
        target = ROOT / identifier / "references/local-title-contract.md"
        if target.is_symlink() or not target.parent.is_dir() or ROOT not in target.resolve().parents:
            raise ValueError(f"不安全地区规则副本：{identifier}")
        if not target.is_file() or target.read_bytes() != content:
            mismatches.append(identifier)
            if not check:
                target.write_bytes(content)
    if check and mismatches:
        print("地区标题副本未同步：" + "、".join(mismatches))
        return 1
    print(f"地区标题真源与 {len(MIRROR_IDS)} 份运行副本一致" + ("（只读校验）" if check else "（机械同步）"))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    return sync(check=parser.parse_args().check)


if __name__ == "__main__":
    raise SystemExit(main())
