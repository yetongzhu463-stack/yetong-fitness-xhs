#!/usr/bin/env python3
"""Read dispatch contracts from registered skills in this verified YETONG instance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from validate_registry import (
    DEFAULT_REGISTRY, DEFAULT_ROOT, safe_file, skill_description, skill_handoff,
    validate, validate_runtime,
)


def list_skills(root: Path) -> list[dict]:
    root = root.resolve()
    enabled = validate(root, DEFAULT_REGISTRY)
    validate_runtime(root, enabled)
    registry = json.loads(safe_file(root, DEFAULT_REGISTRY).read_text(encoding="utf-8"))
    result = []
    for item in registry["capabilities"]:
        if not item["enabled"]:
            continue
        entry = safe_file(root, item["entry"])
        result.append({
            "name": item["id"],
            "description": skill_description(entry),
            "handoff": skill_handoff(entry),
            "source": str(entry.parent),
            "entry": str(entry),
            "service_line": item["service_line"],
            "profile_requirement": item["profile_requirement"],
            "required_any_of": item["required_any_of"],
            "produces": item["produces"],
            "profile_check": str(safe_file(root, item["profile_check"])) if item["profile_check"] else None,
        })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="读取当前安装的 YETONG 子技能与接手字段")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="当前这一套 Skills 的根目录")
    args = parser.parse_args()
    try:
        result = list_skills(args.root)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"候选读取未通过：{exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
