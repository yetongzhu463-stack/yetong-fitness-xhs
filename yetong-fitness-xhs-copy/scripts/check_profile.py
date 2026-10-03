#!/usr/bin/env python3
"""Check an explicitly supplied person-dna.md before personalized copywriting.

This prints no profile content and does not verify individual claims or consent.
"""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path


FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
PROFILE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REQUIRED_HEADINGS = (
    "身份与当前业务",
    "本地城市、服务半径与场馆",
    "本地客群底色与痛点",
    "产品与成交路径",
    "表达指纹",
    "公开权限与禁区",
    "内容 DNA 摘要",
)
# A confirmed starter profile may have only "语气待校准"; copy must stay a trial draft.
CONTENT_HEADINGS = tuple(heading for heading in REQUIRED_HEADINGS if heading != "表达指纹")


def parse_fields(block: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip("\"'")
    return fields


def main() -> int:
    parser = argparse.ArgumentParser(description="Check person DNA activation for copywriting")
    parser.add_argument("profile", type=Path)
    args = parser.parse_args()

    if not args.profile.is_file():
        print("invalid: profile file missing")
        return 3
    try:
        content = args.profile.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        print("invalid: profile file unreadable")
        return 3

    match = FRONTMATTER.match(content)
    if match is None:
        print("invalid: frontmatter missing")
        return 3
    fields = parse_fields(match.group(1))
    if (
        fields.get("schema_version") != "2"
        or not PROFILE_ID.fullmatch(fields.get("profile_id", ""))
        or not fields.get("display_name", "").strip()
    ):
        print("invalid: unsupported profile schema")
        return 3
    status = fields.get("status", "")
    if status != "active":
        print(f"inactive: status={status or 'missing'}")
        return 2

    headings = list(re.finditer(r"^##\s+(.+?)\s*$", content, re.MULTILINE))
    sections: dict[str, str] = {}
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(content)
        sections[heading.group(1).strip()] = content[heading.end():end].strip()
    if any(heading not in sections for heading in REQUIRED_HEADINGS) or any(
        len(re.sub(r"\s+", "", sections.get(heading, ""))) < 12
        for heading in CONTENT_HEADINGS
    ):
        print("invalid: required profile sections missing or too short")
        return 3
    try:
        date.fromisoformat(fields.get("confirmed_at", ""))
    except ValueError:
        print("invalid: active profile confirmation date missing")
        return 3

    print("active: profile structure ready; verify facts, consent and voice samples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
