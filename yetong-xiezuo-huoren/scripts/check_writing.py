#!/usr/bin/env python3
"""Read-only writing lint and length checks; semantic truth remains unverified.

Some lexical patterns and metrics are adapted from human-writing 1.2.0.
See the bundled MIT LICENSE and references/provenance.md.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re
import sys

RULES_PATH = Path(__file__).resolve().parents[1] / 'references' / 'style-rules.json'
QUOTES = re.compile(r'“[^”\n]*”|「[^」\n]*」|『[^』\n]*』|"[^"\n]*"')


def han_count(text: str) -> int:
    return len(re.findall(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]', text))


def blank(match: re.Match) -> str:
    return ''.join('\n' if char == '\n' else ' ' for char in match.group())


def mask_non_prose(text: str) -> str:
    patterns = [
        r'\A---\s*\n.*?\n---\s*(?:\n|\Z)',
        r'```.*?```', r'~~~.*?~~~', r'`[^`\n]*`',
        r'(?<=\])\([^\n)]*\)', r'https?://[^\s)>]+', r'<[^>\n]+>',
    ]
    for pattern in patterns:
        text = re.sub(pattern, blank, text, flags=re.DOTALL)
    # Keep offsets intact and remove table alignment syntax from analysis.
    text = re.sub(r'^[ \t]*\|?(?:[ \t]*:?-{3,}:?[ \t]*\|)+[ \t]*(?::?-{3,}:?[ \t]*)?$',
                  blank, text, flags=re.MULTILINE)
    return text


def visible_for_count(text: str) -> str:
    text = re.sub(r'^\s{0,3}#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*(?:>\s*|[-+*]\s+|\d+[.、]\s+)', '', text, flags=re.MULTILINE)
    text = re.sub(r'[*_~]', '', text)
    # A Markdown link destination was masked; keep its visible label.
    return re.sub(r'\[([^\]\n]+)\](?=\s|$)', r'\1', text)


def load_rules() -> dict:
    rules = json.loads(RULES_PATH.read_text(encoding='utf-8'))
    if rules.get('schema_version') != 1:
        raise ValueError('不支持的规则版本')
    for rule in rules['patterns']:
        for pattern in rule['patterns']:
            re.compile(pattern, re.MULTILINE)
    return rules


def term_matches(text: str, terms: list[str]) -> list[tuple[int, str]]:
    occupied = []
    found = []
    for term in sorted(terms, key=len, reverse=True):
        for match in re.finditer(re.escape(term), text):
            start, end = match.span()
            if any(start < old_end and end > old_start for old_start, old_end in occupied):
                continue
            occupied.append((start, end))
            found.append((start, term))
    return sorted(found)


def prose_lines(text: str) -> list[tuple[int, int]]:
    return [match.span() for match in re.finditer(r'[^\n]+', text)
            if han_count(match.group()) >= 4
            and not match.group().strip().startswith(('#', '|', '!['))]


def paragraphs(text: str) -> list[dict]:
    result = []
    cursor = 0
    for block in re.split(r'\n\s*\n', text):
        start = text.find(block, cursor)
        cursor = start + len(block)
        value = block.strip()
        if han_count(value) < 4 or value.startswith(('#', '|', '![')):
            continue
        result.append({'start': start, 'text': value, 'han': han_count(value),
                       'sentences': max(1, len(re.findall(r'[。！？!?]', value)))})
    return result


def analyze(text: str, *, genre: str = 'prose', target: int | None = None,
            tolerance: float = 0.1, count_mode: str = 'nonspace',
            forbidden: list[str] | None = None, style_hints: bool = False) -> dict:
    rules = load_rules()
    if genre not in rules['genres']:
        raise ValueError('未知文体')
    if count_mode not in ('nonspace', 'han'):
        raise ValueError('未知计数口径')
    if target is not None and target <= 0:
        raise ValueError('目标字数必须为正整数')
    if not math.isfinite(tolerance) or not 0 <= tolerance <= 1:
        raise ValueError('容差须为 0～1 的有限数')
    if any(not term.strip() for term in forbidden or []):
        raise ValueError('显式禁项不能为空')
    prose = mask_non_prose(text)
    visible = visible_for_count(prose)
    counts = {'nonspace': sum(not char.isspace() for char in visible), 'han': han_count(visible)}
    if counts['han'] == 0:
        raise ValueError('没有检测到可检查的中文正文')
    findings = []

    def add(rule_id, severity, position, message, excerpt='', occurrences=1):
        findings.append({'rule_id': rule_id, 'severity': severity,
                         'line': prose.count('\n', 0, position) + 1,
                         'column': position - prose.rfind('\n', 0, position),
                         'message': message, 'excerpt': re.sub(r'\s+', ' ', excerpt).strip()[:100],
                         'occurrences': occurrences})

    length = None
    if target is not None:
        lower = math.ceil(target * (1 - tolerance))
        upper = math.floor(target * (1 + tolerance))
        actual = counts[count_mode]
        length = {'target': target, 'tolerance': tolerance, 'count_mode': count_mode,
                  'minimum': lower, 'maximum': upper, 'actual': actual, 'within_range': lower <= actual <= upper}
        if not length['within_range']:
            add('E001', 'error', 0, f'本轮篇幅为 {actual}，配置范围为 {lower}～{upper}；不能用编造或重复补足。')
    for term in forbidden or []:
        hits = list(re.finditer(re.escape(term), prose))
        if hits:
            add('E002', 'error', hits[0].start(), '命中本轮显式配置的禁项。', term, len(hits))

    for rule in rules['terms']:
        if genre not in rule['genres']:
            continue
        hits = term_matches(prose, rule['terms'])
        minimum = rule.get('minimum', 1)
        if rule.get('dynamic_limit') == 'marker':
            minimum = max(2, counts['han'] // 900) + 1
        if len(hits) >= minimum:
            add(rule['id'], rule['severity'], hits[0][0], rule['message'],
                '、'.join(dict.fromkeys(term for _, term in hits)), len(hits))

    lines = prose_lines(prose)
    for rule in rules['patterns']:
        if genre not in rule['genres']:
            continue
        subject = QUOTES.sub(blank, prose) if rule.get('exclude_quotes') else prose
        start, end = 0, len(subject)
        if rule.get('location'):
            if not lines:
                continue
            start, end = lines[0] if rule['location'] == 'opening' else lines[-1]
        matches = [match for pattern in rule['patterns']
                   for match in re.compile(pattern, re.MULTILINE).finditer(subject, start, end)]
        matches.sort(key=lambda match: match.start())
        if matches:
            add(rule['id'], rule['severity'], matches[0].start(), rule['message'],
                matches[0].group(), len(matches))

    shape = rules['shape']
    if genre in shape['genres']:
        sentences = list(re.finditer(r'[^。！？!?\n]+(?:[。！？!?]|$)', prose))
        normalized = [(match.start(), re.sub(r'\s+', '', match.group()).strip('。！？!?'))
                      for match in sentences]
        repeated = Counter(value for _, value in normalized if han_count(value) >= shape['exact_repeat_minimum_han'])
        repeat = next(((position, value, repeated[value]) for position, value in normalized if repeated[value] > 1), None)
        if repeat:
            add('W301', 'review', repeat[0], '出现逐字重复的句子；检查是否有意重复，语义同义重复仍需人工检查。', repeat[1], repeat[2])
        for sentence in sentences:
            clauses = [part.strip() for part in re.split(r'[，、；,;]', sentence.group()) if han_count(part) >= 3]
            streak = 1
            for previous, current in zip(clauses, clauses[1:]):
                streak = streak + 1 if previous[:2] == current[:2] and han_count(current[:2]) == 2 else 1
                if streak >= 3:
                    add('W302', 'review', sentence.start(), '至少三个相邻小句同开头；排比是否有作用需按文体判断。', sentence.group())
                    break
        lengths = [han_count(match.group()) for match in re.finditer(r'[^。！？!?\n]+[。！？!?]', prose)
                   if han_count(match.group()) >= shape['minimum_sentence_han']]
        if len(lengths) >= shape['sentence_cv_minimum']:
            mean = sum(lengths) / len(lengths)
            cv = (sum((value - mean) ** 2 for value in lengths) / len(lengths)) ** 0.5 / mean
            if cv < shape['sentence_cv_threshold']:
                add('W303', 'review', 0, '句长统计接近；只检查节奏，不为改变统计值添句或拆句。', f'CV={cv:.3f}')
        conjunctions = term_matches(prose, shape['conjunctions'])
        if counts['han'] >= shape['conjunction_minimum_han'] and len(conjunctions) * 1000 / counts['han'] > shape['conjunction_per_thousand']:
            add('W304', 'review', conjunctions[0][0], '连词较密，检查它们是否承担实际关系，不追求固定删除比例。', occurrences=len(conjunctions))
        heavy = [match for match in sentences if han_count(match.group()) >= shape['heavy_de_han']
                 and match.group().count('的') >= shape['heavy_de_count']]
        if len(heavy) > max(1, counts['han'] // 1500):
            add('W305', 'review', heavy[0].start(), '多个长句含较多“的”，检查主干是否来得太晚。', heavy[0].group(), len(heavy))
        left = [match for pattern in shape['left_patterns'] for match in re.finditer(pattern, prose, re.MULTILINE)]
        if len(left) > max(2, counts['han'] // 1200):
            add('W306', 'review', left[0].start(), '长前置成分较多，先检查做事的人和动作。', left[0].group(), len(left))
        blocks = paragraphs(prose)
        # Short social pieces and dialogue need not follow long-prose paragraph shapes.
        if genre in ('prose', 'spoken'):
            streak = 0
            for block in blocks:
                streak = streak + 1 if block['han'] <= shape['short_han'] and block['sentences'] <= 1 else 0
                if streak >= shape['short_streak']:
                    add('W307', 'review', block['start'], '短单句段连续出现，判断是否有实际停顿价值。')
                    break
            if len(blocks) >= shape['paragraph_minimum'] and sum(block['sentences'] <= 1 for block in blocks) / len(blocks) >= shape['single_sentence_ratio']:
                add('W308', 'review', blocks[0]['start'], '单句段比例较高，检查是否在连续喊判断。')
        for opener in shape['repeated_openers']:
            hits = [block for block in blocks if block['text'].lstrip('“‘"（(').startswith(opener)]
            if len(hits) >= shape['opener_minimum']:
                add('W309', 'review', hits[0]['start'], '固定段首反复出现，检查是否有实际衔接作用。', opener, len(hits))
        fields = sorted((match.start(), field, term)
                        for field, terms in shape['metaphor_fields'].items()
                        for term in terms for match in re.finditer(re.escape(term), prose))
        for index, (position, _, _) in enumerate(fields):
            window = [hit for hit in fields[index:] if hit[0] - position <= shape['metaphor_window_characters']]
            if len({hit[1] for hit in window}) >= 3:
                add('W310', 'review', position, '多个词场近邻出现；可能只是实物，不能据此认定混乱借喻。', '、'.join(dict.fromkeys(hit[2] for hit in window)))
                break
        highlights = list(re.finditer(r'[「『][^」』\n]{1,6}[」』]', prose))
        if len(highlights) > max(3, counts['han'] // 700):
            add('W311', 'review', highlights[0].start(), '短语反复加特殊引号，检查是否在批量造金句。', occurrences=len(highlights))

    if style_hints:
        rule = rules['style_punctuation']
        for symbol in rule['symbols']:
            hits = [match for match in re.finditer(re.escape(symbol) + '+', prose)
                    if not (symbol in ':：' and prose[max(0, match.start()-1):match.start()].isdigit()
                            and prose[match.end():match.end()+1].isdigit())]
            if hits:
                add(rule['id'], rule['severity'], hits[0].start(), rule['message'], symbol, len(hits))
    findings.sort(key=lambda item: (item['line'], item['column'], item['rule_id']))
    summary = {severity: sum(item['severity'] == severity for item in findings) for severity in ('error', 'review', 'info')}
    return {'tool': 'yetong-writing-check', 'version': rules['skill_version'], 'genre': genre,
            'counts': counts, 'length': length, 'summary': summary,
            'status': 'fail' if summary['error'] else 'needs_review' if summary['review'] else 'no_machine_errors',
            'findings': findings, 'limitations': rules['limitations']}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='中文词法与篇幅检查，不判断事实真假或 AI 写作概率')
    parser.add_argument('path', help='正文 UTF-8 文件；- 表示 stdin')
    parser.add_argument('--genre', choices=['social', 'spoken', 'prose', 'fiction', 'poetry'], default='prose')
    parser.add_argument('--target', type=int)
    parser.add_argument('--tolerance', type=float, default=0.1)
    parser.add_argument('--count-mode', choices=['nonspace', 'han'], default='nonspace')
    parser.add_argument('--format', choices=['text', 'json'], default='text')
    parser.add_argument('--forbid', action='append', default=[], help='本轮显式禁项，可重复指定')
    parser.add_argument('--style-hints', action='store_true', help='额外显示标点风格线索，不判硬失败')
    args = parser.parse_args(argv)
    try:
        text = sys.stdin.read() if args.path == '-' else Path(args.path).read_text(encoding='utf-8')
        report = analyze(text, genre=args.genre, target=args.target, tolerance=args.tolerance,
                         count_mode=args.count_mode, forbidden=args.forbid, style_hints=args.style_hints)
    except (OSError, UnicodeError, ValueError, KeyError) as error:
        if args.format == 'json':
            print(json.dumps({'tool': 'yetong-writing-check', 'status': 'input_error', 'message': str(error)}, ensure_ascii=False))
        else:
            print(f'输入错误：{error}', file=sys.stderr)
        return 2
    if args.format == 'json':
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"非空白字符 {report['counts']['nonspace']}；汉字 {report['counts']['han']}；状态 {report['status']}")
        if report['length']:
            length = report['length']
            print(f"篇幅口径 {length['count_mode']}，范围 {length['minimum']}～{length['maximum']}，实际 {length['actual']}")
        for finding in report['findings']:
            print(f"{finding['severity']} {finding['rule_id']} 第 {finding['line']} 行第 {finding['column']} 列：{finding['message']} {finding['excerpt']}")
        print('未出现机器硬失败不代表事实正确、材料充分或文风合格。')
    return 1 if report['summary']['error'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
