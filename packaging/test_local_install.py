#!/usr/bin/env python3
"""Install the allowlisted bundle into a temporary Codex project and verify it."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from zipfile import ZipFile


ARCHIVE_ROOT = "yetong-fitness-xhs-bundle"
SKILL_IDS = (
    "yetong-fitness-xhs",
    "yetong-fitness-xhs-profile",
    "yetong-fitness-xhs-topic",
    "yetong-fitness-xhs-copy",
)


def run(command: list[str], cwd: Path, *, expected: int = 0, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["DISABLE_TELEMETRY"] = "1"
    result = subprocess.run(
        command, cwd=cwd, env=environment, capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != expected:
        detail = (result.stdout + "\n" + result.stderr)[-3000:]
        raise RuntimeError(f"exit {result.returncode}, expected {expected}: {' '.join(command[:4])}\n{detail}")
    return result


def main() -> int:
    if len(sys.argv) not in {2, 3} or (len(sys.argv) == 3 and sys.argv[2] != "--agent-smoke"):
        print("用法：python3 packaging/test_local_install.py <本地预览 ZIP> [--agent-smoke]")
        return 2
    archive = Path(sys.argv[1]).resolve()
    if not archive.is_file():
        print(f"ERROR：找不到预览包：{archive}")
        return 2

    try:
        with tempfile.TemporaryDirectory(prefix="yetong-local-install-") as temporary:
            root = Path(temporary)
            stage = root / "stage"
            consumer = root / "consumer"
            stage.mkdir()
            consumer.mkdir()
            with ZipFile(archive) as bundle:
                for name in bundle.namelist():
                    parts = PurePosixPath(name).parts
                    if not parts or parts[0] != ARCHIVE_ROOT or ".." in parts:
                        raise ValueError(f"预览包含不安全路径：{name}")
                manifest = json.loads(bundle.read(f"{ARCHIVE_ROOT}/MANIFEST.json"))
                bundle.extractall(stage)

            source = stage / ARCHIVE_ROOT
            run(
                ["npx", "-y", "skills", "add", str(source), "--skill", "*", "-a", "codex", "-y", "--copy"],
                consumer,
            )
            installed_root = consumer / ".agents/skills"
            expected_ids = tuple(manifest["required_skills"])
            if set(expected_ids) != set(SKILL_IDS):
                raise ValueError(f"预览包声明的 Skill 集合不符：{expected_ids}")
            for identifier in expected_ids:
                entry = installed_root / identifier / "SKILL.md"
                if not entry.is_file():
                    raise ValueError(f"安装后缺少入口：{entry}")
            for archive_name, digest in manifest["files_sha256"].items():
                relative = PurePosixPath(archive_name).relative_to(ARCHIVE_ROOT)
                if not relative.parts or relative.parts[0] not in expected_ids:
                    continue
                installed = installed_root.joinpath(*relative.parts)
                if not installed.is_file():
                    raise ValueError(f"安装后缺少资源：{relative}")
                if hashlib.sha256(installed.read_bytes()).hexdigest() != digest:
                    raise ValueError(f"安装后资源内容不一致：{relative}")

            router = installed_root / "yetong-fitness-xhs"
            run([sys.executable, str(router / "scripts/validate_registry.py")], consumer)
            profile_validator = installed_root / "yetong-fitness-xhs-profile/scripts/validate_profile.py"
            topic_gate = installed_root / "yetong-fitness-xhs-topic/scripts/check_profile.py"
            copy_gate = installed_root / "yetong-fitness-xhs-copy/scripts/check_profile.py"
            source_root = Path(__file__).resolve().parents[1]
            active = source_root / "packaging/fixtures/active-synthetic.md"
            draft = source_root / "packaging/fixtures/draft-synthetic.md"
            for profile in (active, draft):
                run([sys.executable, str(profile_validator), str(profile)], consumer)
            for gate in (topic_gate, copy_gate):
                run([sys.executable, str(gate), str(active)], consumer)
                run([sys.executable, str(gate), str(draft)], consumer, expected=2)

            if len(sys.argv) == 3:
                installed_active = consumer / "active-synthetic.md"
                installed_draft = consumer / "draft-synthetic.md"
                shutil.copyfile(active, installed_active)
                shutil.copyfile(draft, installed_draft)
                base = [
                    "codex", "exec", "--ephemeral", "--skip-git-repo-check",
                    "--ignore-user-config", "-s", "read-only", "-C", str(consumer),
                ]
                active_prompt = (
                    "使用本项目安装的 $yetong-fitness-xhs。合成测试档案路径是 "
                    f"{installed_active}。我是测试教练，想面向附近线下会员发内容，"
                    "但不知道发什么。请先出 2 个具体选题；我明确授权你代选其中最有依据的 1 题，"
                    "再写一篇很短的小红书测试稿。最后列出实际使用的 YETONG Skill ID 和档案门槛结果。"
                    "只读，不修改文件。"
                )
                inactive_prompt = (
                    "使用本项目安装的 $yetong-fitness-xhs。合成测试档案路径是 "
                    f"{installed_draft}。请按我的经历写一篇个性化小红书文案。"
                    "只读，不修改文件。"
                )
                for label, prompt in (("active chain", active_prompt), ("inactive stop", inactive_prompt)):
                    response = run(base + [prompt], consumer, timeout=240)
                    output = response.stdout.strip()
                    print(f"--- Agent {label} ---\n{output[-6000:]}")

            print("隔离安装通过：4 个 Skill 已复制到临时 Codex 项目")
            print("资源哈希一致；主入口登记校验、人物档案结构校验及选题／文案 active/draft 门槛通过")
            print("临时项目已自动清理；未写入用户的全局 Skill 目录")
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, KeyError) as exc:
        print(f"ERROR：{exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
