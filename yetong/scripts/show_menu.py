#!/usr/bin/env python3
"""Verify an installed YETONG skill set and print its live three-line menu."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from validate_registry import DEFAULT_REGISTRY, DEFAULT_ROOT, safe_file, skill_name, validate


def show(root: Path) -> int:
    root = root.resolve()
    try:
        entry = safe_file(root, "yetong/SKILL.md")
        if skill_name(entry) != "yetong":
            raise ValueError("主入口目录与 SKILL.md 名称不一致")
        safe_file(root, "yetong/agents/openai.yaml")
        enabled = validate(root, DEFAULT_REGISTRY)
        registry = json.loads(safe_file(root, DEFAULT_REGISTRY).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"安装校验未通过：{exc}")
        try:
            partial = json.loads(safe_file(root, DEFAULT_REGISTRY).read_text(encoding="utf-8"))
            for item in partial.get("capabilities", []):
                if not isinstance(item, dict) or not item.get("enabled"):
                    continue
                missing = []
                for relative in item.get("package_files", []):
                    try:
                        safe_file(root, relative)
                    except (OSError, ValueError):
                        missing.append(relative)
                if missing:
                    print(f"- {item.get('id', '未命名模块')}｜未安装完整：{', '.join(missing)}")
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            pass
        print("不要把介绍文档当作安装成功；请重新安装整组 Skill，再检查缺失的文件。")
        return 1

    capabilities = [item for item in registry["capabilities"] if item["enabled"]]
    print(f"安装校验通过：{len(enabled) + 1}/{len(enabled) + 1} 个 YETONG Skill")
    print("YETONG｜面向教练所在地的线下健身会员")

    for line in registry["service_lines"]:
        status = "已可用" if line["status"] == "active" else "规划中"
        print(f"\n{line['label']}｜{status}")
        print(line["description"])
        if line["id"] == "content":
            print("基础能力（未来三条服务线共用）：")
            print("- yetong｜总入口：识别需求与材料状态，交给已安装的专项技能。")
            print("  试着说：使用 $yetong，展示全部技能；或告诉我今天该先做什么。")
            for item in capabilities:
                if item["service_line"] == "shared":
                    print(f"- {item['id']}｜{item['menu_label']}：{item['purpose']}。")
                    print(f"  试着说：{item['menu_trigger']}")
        line_modules = [item for item in capabilities if item["service_line"] == line["id"]]
        if not line_modules:
            print("- 目前没有已交付的专项 Skill，不能调用。")
        for item in line_modules:
            print(f"- {item['id']}｜{item['menu_label']}：{item['purpose']}。")
            print(f"  试着说：{item['menu_trigger']}")

    print("\n第一次使用：先用 yetong-dna 建立并确认自己的私人档案；已有已激活档案时，交接路径后直接说出需求。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="核验并展示 YETONG 已安装技能与规划服务线")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="安装后的 Skills 根目录")
    return show(parser.parse_args().root)


if __name__ == "__main__":
    raise SystemExit(main())
