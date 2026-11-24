#!/usr/bin/env python3
"""Read-only, bounded audit of local knowledge navigation. Python 3.9+."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote


VERSION = "1.0.1"
EXCLUDED_PARTS = {
    ".git", "node_modules", ".trash", "__pycache__", ".venv", "venv",
    ".cache", "cache", "dist", "build", "credentials", "browser-data",
    "归档", "历史备份",
}
SENSITIVE_NAME = re.compile(
    r"(^\.env(?:\.|$)|^id_(?:rsa|ed25519)(?:\.|$)|"
    r"(?:^|[-_.])(?:passwords?|credentials?|secrets?)(?:[-_.]|$)|密码|密钥)",
    re.I,
)
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
INLINE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
LINK = re.compile(r"!?\[[^\]\n]*\]\(\s*(<[^>\n]*>|(?:\\.|[^)\n])*)\)")
DEFINITION = re.compile(r"^ {0,3}\[[^\]]+\]:\s*(<[^>]+>|.+?)\s*$")
SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


class AuditError(Exception):
    pass


def within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def excluded(relative: Path) -> bool:
    return any(
        part.lower() in EXCLUDED_PARTS or SENSITIVE_NAME.search(part)
        for part in relative.parts
    )


def destination(value: str) -> str:
    value = value.strip()
    if value.startswith("<") and ">" in value:
        return value[1:value.index(">")]
    # Accept a conventional quoted title, without treating it as a file name.
    value = re.sub(r"\s+[\"'].*[\"']\s*$", "", value)
    return re.sub(r"\\([ ()\[\]#])", r"\1", value)


def outside_fences(text: str):
    opened = None
    for number, line in enumerate(text.splitlines(), 1):
        match = FENCE.match(line)
        if opened is not None:
            if match and match.group(1)[0] == opened[0] and len(match.group(1)) >= opened[1] and not match.group(2).strip():
                opened = None
            continue
        if match:
            opened = (match.group(1)[0], len(match.group(1)))
            continue
        yield number, line


def references(text: str):
    for number, line in outside_fences(text):
        occupied = []
        for match in INLINE.finditer(line):
            occupied.append(match.span())
            yield number, match.group(2), "inline-code"
        # Avoid interpreting Markdown link syntax inside inline code a second time.
        plain = "".join(" " if any(start <= i < end for start, end in occupied) else c for i, c in enumerate(line))
        for match in LINK.finditer(plain):
            yield number, destination(match.group(1)), "markdown-link"
        definition = DEFINITION.match(plain)
        if definition:
            yield number, destination(definition.group(1)), "link-definition"


def resolve_reference(root: Path, document: Path, raw: str, kind: str) -> dict:
    value = raw.strip()
    if kind != "inline-code":
        value = unquote(html.unescape(value))
    if not value or value.startswith("#"):
        return {"status": "skipped", "reason": "anchor-or-empty"}
    if SCHEME.match(value):
        return {"status": "skipped", "reason": "remote-or-foreign-scheme"}
    if any(c in value for c in "{}<>"):
        return {"status": "skipped", "reason": "template"}
    if any(c in value for c in "*?[]"):
        return {"status": "skipped", "reason": "pattern"}
    if re.match(r"^(?:python\d*|node|bash|sh|rg|git|npx)\s", value):
        return {"status": "skipped", "reason": "command"}
    value = value.split("#", 1)[0]
    if not value:
        return {"status": "skipped", "reason": "anchor-or-empty"}
    if kind == "inline-code" and not (
        "/" in value or value.startswith(".") or re.search(r"\.[A-Za-z0-9]{1,12}$", value)
    ):
        return {"status": "skipped", "reason": "not-a-path"}
    candidate = Path(value)
    # Reject lexical exclusions before resolving a link into a different location.
    if excluded(candidate):
        return {"status": "excluded", "reason": "excluded-or-sensitive"}
    try:
        target = (candidate if candidate.is_absolute() else document.parent / candidate).resolve()
    except (OSError, RuntimeError, ValueError) as error:
        return {"status": "unresolved", "reason": type(error).__name__}
    if not within(target, root):
        return {"status": "outside-root", "reason": "root-boundary"}
    relative = target.relative_to(root)
    if excluded(relative):
        return {"status": "excluded", "reason": "excluded-or-sensitive"}
    try:
        exists = target.exists()
    except OSError as error:
        return {"status": "unresolved", "reason": type(error).__name__}
    return {
        "status": "exists" if exists else "missing",
        "target": relative.as_posix() or ".",
        "is_directory": target.is_dir() if exists else False,
    }


def checked_document(root: Path, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or excluded(relative):
        raise AuditError("导航／快照文档必须是根目录内非敏感的相对路径")
    try:
        document = (root / relative).resolve()
    except (OSError, RuntimeError, ValueError) as error:
        raise AuditError("文档路径无法解析") from error
    if not within(document, root) or excluded(document.relative_to(root)):
        raise AuditError("文档越出根目录或属于排除范围")
    if not document.is_file():
        raise AuditError("文档不存在或不是普通文件：" + value)
    return document


def read_document(document: Path):
    try:
        raw = document.read_bytes()
        return raw, raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise AuditError("无法读取 UTF-8 导航／索引：" + document.name) from error


def document_metrics(raw: bytes, text: str) -> dict:
    table_rows = 0
    for _, line in outside_fences(text):
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and not all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            table_rows += 1
    # This deliberately includes table headers; do not call it a business-entry count.
    return {"lines": len(text.splitlines()), "utf8_bytes": len(raw), "table_nonseparator_rows_including_headers": table_rows}


def audit(root: Path, navigation: str, follow_indexes: bool) -> dict:
    first = checked_document(root, navigation)
    documents = []
    hashes = {}
    refs = []
    seen = set()

    def visit(document: Path):
        if document in seen:
            return
        seen.add(document)
        raw, text = read_document(document)
        source = document.relative_to(root).as_posix()
        hashes[source] = hashlib.sha256(raw).hexdigest()
        documents.append({"path": source, **document_metrics(raw, text)})
        for number, value, kind in references(text):
            refs.append({"source": source, "line": number, "raw": value, "kind": kind, **resolve_reference(root, document, value, kind)})

    visit(first)
    if follow_indexes:
        # Freeze the initial list: never recursively walk an index's descendants.
        indexes = sorted({r["target"] for r in refs if r["status"] == "exists" and not r.get("is_directory") and Path(r["target"]).name.lower() == "readme.md"})
        for index in indexes:
            visit(checked_document(root, index))
    skipped = [r for r in refs if r["status"] == "skipped"]
    checked = [r for r in refs if r["status"] != "skipped"]
    counts = Counter(r["target"] for r in checked if r.get("target"))
    findings = []
    for reference in checked:
        if reference["status"] == "missing":
            findings.append({"priority": "立即处理", "type": "missing-reference", **reference})
        elif reference["status"] in {"outside-root", "excluded", "unresolved"}:
            findings.append({"priority": "建议处理", "type": "unchecked-reference", **reference})
    for target, count in sorted(counts.items()):
        if count > 1:
            findings.append({"priority": "建议处理", "type": "repeated-mention", "target": target, "count": count, "note": "重复提及不等于重复业务文件，不能据此自动删除"})
    return {
        "schema_version": 1, "script_version": VERSION, "root": str(root),
        "navigation": first.relative_to(root).as_posix(),
        "coverage": {
            "parser": "inline code, inline Markdown links and reference definitions outside fenced code",
            "followed_local_index_levels": 1 if follow_indexes else 0,
            "not_checked": ["plain-text paths and full CommonMark syntax", "link anchors", "raw business contents and version authority", "whole-library inventory and semantic duplicates"],
        },
        "documents": documents, "document_hashes": hashes,
        "summary": {
            "documents_read": len(documents), "local_reference_mentions": len(checked),
            "unique_local_targets": len(counts),
            "missing_mentions": sum(r["status"] == "missing" for r in checked),
            "unchecked_mentions": sum(r["status"] in {"outside-root", "excluded", "unresolved"} for r in checked),
            "skipped_mentions": len(skipped),
        },
        "references": checked, "skipped": skipped, "findings": findings,
    }


def check_snapshot(root: Path, snapshot_file: str) -> dict:
    snapshot_path = Path(snapshot_file).expanduser()
    if excluded(snapshot_path) or excluded(snapshot_path.resolve()):
        raise AuditError("快照不能来自敏感或排除路径")
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise AuditError("无法读取 JSON 快照") from error
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1 or snapshot.get("root") != str(root):
        raise AuditError("快照版本或根目录不匹配")
    hashes = snapshot.get("document_hashes")
    if not isinstance(hashes, dict) or not hashes:
        raise AuditError("快照缺少非空 document_hashes")
    changes = []
    for relative, expected in hashes.items():
        if not isinstance(relative, str) or not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise AuditError("快照路径或哈希不合法")
        # A missing old document is drift; excluded/outside paths are invalid input.
        lexical = Path(relative)
        target = (root / lexical).resolve()
        if lexical.is_absolute() or excluded(lexical) or not within(target, root) or excluded(target.relative_to(root)):
            raise AuditError("快照包含越界或排除路径")
        if not target.is_file():
            changes.append({"path": relative, "reason": "missing"})
            continue
        raw, _ = read_document(target)
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected:
            changes.append({"path": relative, "reason": "content-changed", "expected": expected, "actual": actual})
    return {"schema_version": 1, "root": str(root), "drift": bool(changes), "changes": changes, "documents_checked": len(hashes)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--navigation", default="SOURCE_OF_TRUTH.md")
    parser.add_argument("--follow-local-indexes", action="store_true")
    parser.add_argument("--check-snapshot")
    parser.add_argument("--fail-on-missing", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = Path(args.root).expanduser().resolve()
        if not root.is_dir():
            raise AuditError("根目录不存在或不是目录")
        if args.check_snapshot:
            result = check_snapshot(root, args.check_snapshot)
            code = 1 if result["drift"] else 0
        else:
            result = audit(root, args.navigation, args.follow_local_indexes)
            code = 1 if args.fail_on_missing and result["summary"]["missing_mentions"] else 0
    except (AuditError, OSError, RuntimeError, ValueError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False) if args.json else "检查失败：" + str(error), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.check_snapshot:
        print("文档发生漂移" if result["drift"] else "记录中的文档未发生漂移")
        for change in result["changes"]:
            print(change["path"] + ": " + change["reason"])
    else:
        print(json.dumps(result["summary"], ensure_ascii=False))
        for finding in result["findings"]:
            print(finding["priority"] + "：" + finding["type"] + " " + finding.get("target", finding.get("raw", "")))
        print("范围限制：不核验业务事实、版本权威、锚点或全库清单；未覆盖格式需人工复核。")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
