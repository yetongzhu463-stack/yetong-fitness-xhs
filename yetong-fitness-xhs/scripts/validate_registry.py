#!/usr/bin/env python3
"""Validate the allowlisted capabilities used by the YETONG router."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


DEFAULT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = "yetong-fitness-xhs/references/capability-registry.json"
SLUG = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
FRONTMATTER_NAME = re.compile(r"\A---\s*\n(?P<block>.*?)\n---\s*\n", re.DOTALL)
ALLOWED_PROFILE_REQUIREMENTS = {"none", "optional", "active"}
REQUIRED_KEYS = {
    "id", "entry", "package_files", "purpose", "use_when", "avoid_when", "profile_requirement",
    "required_any_of", "produces", "offer_fit", "profile_check", "priority", "enabled",
}
BLOCKED_PATH_PARTS = {"private-profiles", "tmp", "dist", "evals"}


def safe_file(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or any(part in BLOCKED_PATH_PARTS for part in path.parts):
        raise ValueError(f"不安全的相对路径：{relative}")
    candidate = root / path
    if candidate.is_symlink() or not candidate.is_file() or root not in candidate.resolve().parents:
        raise ValueError(f"文件不存在或越出运行包：{relative}")
    return candidate


def nonempty_strings(value: object, field: str, allow_empty: bool = False) -> None:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise ValueError(f"{field} 必须是{'可为空的' if allow_empty else '非空'}字符串列表")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field} 含空白或非字符串值")


def skill_name(path: Path) -> str:
    content = path.read_text(encoding="utf-8")
    match = FRONTMATTER_NAME.match(content)
    if match is None:
        raise ValueError(f"Skill 缺少 frontmatter：{path}")
    for line in match.group("block").splitlines():
        if line.startswith("name:"):
            return line.partition(":")[2].strip().strip("\"'")
    raise ValueError(f"Skill 缺少 name：{path}")


def validate(root: Path, registry_relative: str) -> list[str]:
    root = root.resolve()
    registry_path = safe_file(root, registry_relative)
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("登记表 schema_version 必须为 1")
    if not isinstance(data.get("scope"), str) or not data["scope"].strip():
        raise ValueError("登记表缺少 scope")
    capabilities = data.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        raise ValueError("登记表 capabilities 必须是非空列表")

    seen: set[str] = set()
    enabled: list[str] = []
    profile_producers = 0
    for index, item in enumerate(capabilities):
        label = f"capabilities[{index}]"
        if not isinstance(item, dict) or set(item) != REQUIRED_KEYS:
            raise ValueError(f"{label} 字段与登记契约不一致")
        identifier = item["id"]
        if not isinstance(identifier, str) or not SLUG.fullmatch(identifier) or identifier in seen:
            raise ValueError(f"{label} id 无效或重复：{identifier}")
        seen.add(identifier)
        entry = item["entry"]
        if not isinstance(entry, str) or entry != f"{identifier}/SKILL.md":
            raise ValueError(f"{identifier} 的 entry 必须指向同名目录的 SKILL.md")
        entry_path = safe_file(root, entry)
        if skill_name(entry_path) != identifier:
            raise ValueError(f"{identifier} 的目录、登记名与 frontmatter name 不一致")
        package_files = item["package_files"]
        nonempty_strings(package_files, f"{identifier}.package_files")
        if len(package_files) != len(set(package_files)) or entry not in package_files:
            raise ValueError(f"{identifier} 的 package_files 重复或遗漏入口")
        for package_file in package_files:
            if not package_file.startswith(f"{identifier}/"):
                raise ValueError(f"{identifier} 的 package_files 含其他模块文件")
            safe_file(root, package_file)
        for field in ("purpose", "offer_fit"):
            if not isinstance(item[field], str) or not item[field].strip():
                raise ValueError(f"{identifier} 的 {field} 不能为空")
        nonempty_strings(item["use_when"], f"{identifier}.use_when")
        nonempty_strings(item["avoid_when"], f"{identifier}.avoid_when", allow_empty=True)
        nonempty_strings(item["required_any_of"], f"{identifier}.required_any_of", allow_empty=True)
        nonempty_strings(item["produces"], f"{identifier}.produces")
        if item["profile_requirement"] not in ALLOWED_PROFILE_REQUIREMENTS:
            raise ValueError(f"{identifier} 的 profile_requirement 无效")
        check = item["profile_check"]
        if item["profile_requirement"] in {"active", "optional"}:
            if not isinstance(check, str) or not check.startswith(f"{identifier}/scripts/"):
                raise ValueError(f"{identifier} 需要自己的激活档案预检脚本")
            safe_file(root, check)
            if check not in package_files:
                raise ValueError(f"{identifier} 的 package_files 遗漏档案预检脚本")
        elif check is not None:
            raise ValueError(f"{identifier} 未要求 active 档案，不应填写 profile_check")
        if type(item["priority"]) is not int or not 0 <= item["priority"] <= 100:
            raise ValueError(f"{identifier} 的 priority 必须在 0—100")
        if type(item["enabled"]) is not bool:
            raise ValueError(f"{identifier} 的 enabled 必须为布尔值")
        if "active_profile" in item["produces"]:
            profile_producers += 1
            if item["profile_requirement"] != "none":
                raise ValueError("建档模块不能要求预先拥有 active 档案")
        if item["enabled"]:
            enabled.append(identifier)
    if profile_producers != 1:
        raise ValueError("登记表必须且只能有一个 active_profile 产出模块")
    return enabled


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 YETONG 主入口能力登记表")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--registry", default=DEFAULT_REGISTRY)
    args = parser.parse_args()
    try:
        enabled = validate(args.root, args.registry)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR：{exc}")
        return 1
    print(f"登记校验通过：{len(enabled)} 个可用模块")
    for identifier in enabled:
        print(f"- {identifier}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
