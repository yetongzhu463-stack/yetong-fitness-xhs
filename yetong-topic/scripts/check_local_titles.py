#!/usr/bin/env python3
"""Check explicit titles against a region already verified from the coach's DNA.

This read-only check does not infer geography, read profiles, or rewrite titles.
"""

from __future__ import annotations

import argparse
import sys


UNKNOWN_REGIONS = {"未知", "待确认", "尚未提供", "未提供", "服务地区", "〔服务地区〕"}


def check_titles(region: str, titles: list[str]) -> list[str]:
    problems: list[str] = []
    if not region or region != region.strip() or len(region) > 40 or any(char in region for char in "\n\r\x00") or region in UNKNOWN_REGIONS:
        return ["地区必须是已核对的服务地区短称，不能空白或使用未知／占位值"]
    if not titles:
        return ["没有提供需要检查的实际标题"]
    for number, title in enumerate(titles, 1):
        if not isinstance(title, str) or not title.strip():
            problems.append(f"第 {number} 条标题为空或不是文字")
        elif not title.strip().startswith((region, f"在{region}")):
            problems.append(f"第 {number} 条标题前部未带所选地区「{region}」")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="逐个检查标题前部是否带已选 DNA 服务地区；不核实档案事实")
    parser.add_argument("--region", required=True, help="已从本人 active DNA 核对的地区短称")
    parser.add_argument("--title", action="append", required=True, help="实际标题文字，可重复传入；不含内部分类或标题字段标签")
    args = parser.parse_args()
    problems = check_titles(args.region, args.title)
    if problems:
        for problem in problems:
            print(f"地区标题检查未通过：{problem}", file=sys.stderr)
        return 2
    print(f"地区标题文字检查通过：{len(args.title)} 条｜地区：{args.region}；DNA 与权限仍须另行核对")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
