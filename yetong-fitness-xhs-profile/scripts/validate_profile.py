#!/usr/bin/env python3
"""Validate the observable structure of one person-dna.md profile."""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path


FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PROFILE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ALLOWED_STATUS = {"draft", "pending_confirmation", "active", "needs_review"}
REQUIRED_KEYS = {
    "schema_version",
    "profile_id",
    "display_name",
    "profile_version",
    "status",
    "updated_at",
    "confirmed_at",
}
REQUIRED_HEADINGS = (
    "身份与当前业务",
    "本地城市、服务半径与场馆",
    "本地客群底色与痛点",
    "产品与成交路径",
    "成长经历与职业时间线",
    "专业优势与可信证据",
    "会员案例与故事资产",
    "价值观、立场与选择标准",
    "人物关系与生活场景",
    "表达指纹",
    "公开权限与禁区",
    "待确认信息与矛盾",
    "内容 DNA 摘要",
)
CRITICAL_ACTIVE_HEADINGS = {
    "身份与当前业务",
    "本地城市、服务半径与场馆",
    "本地客群底色与痛点",
    "产品与成交路径",
    "公开权限与禁区",
    "内容 DNA 摘要",
}
UNFINISHED = (
    "TO" + "DO",
    "FIX" + "ME",
    "<待" + "填写>",
    "[待" + "填写]",
)


def parse_frontmatter(block: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def section_bodies(text: str) -> dict[str, str]:
    matches = list(re.finditer(r"^##\s+(.+?)\s*$", text, re.MULTILINE))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(1).strip()] = text[start:end].strip()
    return sections


def valid_date(value: str) -> bool:
    if not DATE_PATTERN.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="校验人物 DNA 档案")
    parser.add_argument("profile", help="person-dna.md 路径")
    args = parser.parse_args()

    path = Path(args.profile).expanduser().resolve()
    errors: list[str] = []
    if not path.is_file():
        print(f"ERROR：档案不存在：{path}")
        return 1

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        print("ERROR：档案必须使用 UTF-8 编码")
        return 1

    match = FRONTMATTER.match(text)
    if match is None:
        print("ERROR：缺少合法 YAML frontmatter")
        return 1

    fields = parse_frontmatter(match.group(1))
    missing_keys = sorted(REQUIRED_KEYS - fields.keys())
    if missing_keys:
        errors.append(f"缺少字段：{', '.join(missing_keys)}")

    if fields.get("schema_version") != "2":
        errors.append("schema_version 当前必须为 2")
    if not PROFILE_ID_PATTERN.fullmatch(fields.get("profile_id", "")):
        errors.append("profile_id 只能使用小写英文、数字和连字符")
    if not fields.get("display_name", "").strip():
        errors.append("display_name 不能为空")
    try:
        if int(fields.get("profile_version", "0")) < 1:
            raise ValueError
    except ValueError:
        errors.append("profile_version 必须是大于等于 1 的整数")

    status = fields.get("status", "")
    if status not in ALLOWED_STATUS:
        errors.append(f"status 必须是：{', '.join(sorted(ALLOWED_STATUS))}")
    if not valid_date(fields.get("updated_at", "")):
        errors.append("updated_at 必须是有效的 YYYY-MM-DD 日期")

    confirmed_at = fields.get("confirmed_at", "")
    if status == "active" and not valid_date(confirmed_at):
        errors.append("active 档案必须填写有效的 confirmed_at 日期")
    if status != "active" and confirmed_at and not valid_date(confirmed_at):
        errors.append("confirmed_at 非空时必须是有效的 YYYY-MM-DD 日期")

    sections = section_bodies(text)
    missing_headings = [heading for heading in REQUIRED_HEADINGS if heading not in sections]
    if missing_headings:
        errors.append(f"缺少章节：{', '.join(missing_headings)}")

    if status == "active":
        for heading in sorted(CRITICAL_ACTIVE_HEADINGS):
            body = sections.get(heading, "")
            if len(re.sub(r"\s+", "", body)) < 12:
                errors.append(f"active 档案的关键章节内容不足：{heading}")

    for marker in UNFINISHED:
        if marker in text:
            errors.append(f"存在未完成占位符：{marker}")

    for error in errors:
        print(f"ERROR：{error}")
    if errors:
        print(f"校验失败：{len(errors)} 个错误")
        return 1

    print(f"校验通过：{path}（status={status}，profile_id={fields.get('profile_id')}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
