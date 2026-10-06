#!/usr/bin/env python3
"""Verify the published GitHub Skill set in a disposable Codex project.

Run only after pushing the intended source to GitHub. This never installs
Skills globally and compares the downloaded files with the local bundle
allowlist byte for byte.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from build_bundle import ARCHIVE_ROOT, collect, registered_files, sha256


REPOSITORY = "yetongzhu463-stack/yetong-fitness-xhs"
MENU_MARKERS = (
    "小红书内容创作｜已可用",
    "朋友圈营销｜规划中",
    "业绩管理｜规划中",
)


def run(command: list[str], cwd: Path, environment: dict[str, str], *, timeout: int) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stdout + "\n" + result.stderr)[-4000:]
        raise RuntimeError(f"命令失败（退出码 {result.returncode}）：{' '.join(command[:4])}\n{detail}")
    return result.stdout


def expected_skill_hashes() -> tuple[tuple[str, ...], dict[str, str]]:
    registered_ids, source_files = registered_files()
    skill_ids = ("yetong", *registered_ids)

    prefix = f"{ARCHIVE_ROOT}/"
    expected: dict[str, str] = {}
    for archive_name, content in collect(source_files).items():
        if not archive_name.startswith(prefix):
            raise ValueError(f"封装白名单含异常归档路径：{archive_name}")
        relative = archive_name[len(prefix):]
        if relative.split("/", 1)[0] in skill_ids:
            expected[relative] = sha256(content)
    if {f"{identifier}/SKILL.md" for identifier in skill_ids} - expected.keys():
        raise ValueError("本地白名单缺少某个 Skill 入口")
    return skill_ids, expected


def installed_skill_hashes(installed_root: Path, skill_ids: tuple[str, ...]) -> dict[str, str]:
    if not installed_root.is_dir():
        raise ValueError(f"Codex 项目中没有 Skill 目录：{installed_root}")
    directories = {path.name for path in installed_root.iterdir() if path.is_dir()}
    if directories != set(skill_ids):
        missing = sorted(set(skill_ids) - directories)
        extra = sorted(directories - set(skill_ids))
        raise ValueError(f"安装目录与本次发布清单不一致：缺少 {missing}；多出 {extra}")

    actual: dict[str, str] = {}
    for identifier in skill_ids:
        skill_dir = installed_root / identifier
        if skill_dir.is_symlink():
            raise ValueError(f"--copy 未复制 Skill 目录：{identifier}")
        if not (skill_dir / "SKILL.md").is_file():
            raise ValueError(f"安装后缺少入口：{identifier}/SKILL.md")
        for path in skill_dir.rglob("*"):
            if path.is_symlink():
                raise ValueError(f"安装内容包含符号链接：{path.relative_to(installed_root)}")
            if path.is_file():
                relative = path.relative_to(installed_root).as_posix()
                actual[relative] = sha256(path.read_bytes())
    return actual


def main() -> int:
    try:
        skill_ids, expected = expected_skill_hashes()
        with tempfile.TemporaryDirectory(prefix="yetong-remote-install-") as temporary:
            workspace = Path(temporary)
            consumer = workspace / "consumer"
            consumer.mkdir()
            environment = os.environ.copy()
            environment["CI"] = "1"
            environment["DISABLE_TELEMETRY"] = "1"
            environment["npm_config_cache"] = str(workspace / "npm-cache")

            run(
                ["npx", "-y", "skills", "add", REPOSITORY, "-a", "codex", "--skill", "*", "-y", "--copy"],
                consumer,
                environment,
                timeout=300,
            )
            installed_root = consumer / ".agents" / "skills"
            actual = installed_skill_hashes(installed_root, skill_ids)
            missing = sorted(expected.keys() - actual.keys())
            extra = sorted(actual.keys() - expected.keys())
            changed = sorted(name for name in expected.keys() & actual.keys() if expected[name] != actual[name])
            if missing or extra or changed:
                raise ValueError(
                    "远端安装内容与本地发布白名单不一致；检查 GitHub 推送和安装器缓存。"
                    f" 缺少：{missing}；多出：{extra}；哈希不符：{changed}"
                )

            menu = run(
                [sys.executable, str(installed_root / "yetong" / "scripts" / "show_menu.py")],
                consumer,
                environment,
                timeout=30,
            )
            count_marker = f"安装校验通过：{len(skill_ids)}/{len(skill_ids)} 个 YETONG Skill"
            for marker in (count_marker, *MENU_MARKERS, *skill_ids):
                if marker not in menu:
                    raise ValueError(f"安装后菜单缺少必要展示：{marker}")

        print(f"远端安装验证通过：{REPOSITORY}")
        print(f"Codex 项目内安装：{len(skill_ids)} 个短名 Skill；逐文件哈希一致：{len(expected)} 个")
        print("三类菜单校验通过；临时项目及 npm 缓存已清理，未执行全局 Skill 安装")
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
