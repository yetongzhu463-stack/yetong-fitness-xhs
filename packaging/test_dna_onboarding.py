#!/usr/bin/env python3
"""Protect onboarding resources and legacy profile gates, not model behavior."""

from pathlib import Path
import re
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
OPENING = (
    "请回答下面几组问题，可以一起答，口语就行，但一定要越详细越好，我来整理。"
    "稍微要有点耐心，这会决定以后你的文案质量。"
)
CONTENT_SKILLS = ("yetong-topic", "yetong-copy", "yetong-title", "yetong-review", "yetong-cover", "yetong-promo", "yetong-timer")


class DnaOnboardingTests(unittest.TestCase):
    def test_exact_opening_in_guide_and_beginner_help(self):
        for relative in ("yetong-dna/references/interview-guide.md", "docs/START_HERE.md"):
            with self.subTest(file=relative):
                self.assertIn(OPENING, (ROOT / relative).read_text(encoding="utf-8"))

    def test_question_template_has_exactly_six_numbered_groups(self):
        guide = (ROOT / "yetong-dna/references/interview-guide.md").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"^### (\d+)\. (.+)$", guide, re.MULTILINE), [
            ("1", "业务定位与场馆优势"),
            ("2", "到店会员与客群痛点"),
            ("3", "客户问题与真实处理"),
            ("4", "你是谁、专业优势与服务交付"),
            ("5", "高光经历与匿名会员案例"),
            ("6", "为什么客户选择你"),
        ])

    def test_city_question_is_neutral(self):
        guide = (ROOT / "yetong-dna/references/interview-guide.md").read_text(encoding="utf-8")
        first = guide.split("### 1. ", 1)[1].split("城市已由", 1)[0]
        self.assertIn("你目前在哪个城市", first)
        self.assertNotIn("上海", first)
        self.assertNotIn("柯桥", first)

    def test_voice_and_examples_have_boundaries(self):
        guide = (ROOT / "yetong-dna/references/interview-guide.md").read_text(encoding="utf-8")
        for required in ("一段或几段语音", "这些只是帮助回忆的例子", "三件而编造", "会员亲口说过"):
            with self.subTest(boundary=required):
                self.assertIn(required, guide)

    def test_legacy_schema_two_active_profile_is_still_accepted(self):
        profile = ROOT / "packaging/fixtures/active-synthetic.md"
        for skill in CONTENT_SKILLS:
            with self.subTest(skill=skill):
                result = subprocess.run(
                    [sys.executable, str(ROOT / skill / "scripts/check_profile.py"), str(profile)],
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(result.stdout.startswith("active:"), result.stdout)

    def test_legacy_draft_is_blocked_for_personalized_content(self):
        profile = ROOT / "packaging/fixtures/draft-synthetic.md"
        for skill in CONTENT_SKILLS:
            with self.subTest(skill=skill):
                result = subprocess.run(
                    [sys.executable, str(ROOT / skill / "scripts/check_profile.py"), str(profile)],
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
