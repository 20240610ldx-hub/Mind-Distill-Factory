#!/usr/bin/env python3
"""工作区：代码根（仓库）+ 数据根（语料与产物）。

代码根放 scripts/ agents/ config/；数据根放 sources/ output/。通常两者是同一个目录。
worktree 里没有私有语料时，数据根经 `--root` 或环境变量 MDF_DATA_ROOT 指向别处，两者「分离」。分离时：

- 子进程（脚本、harness 新进程）要拿到 MDF_DATA_ROOT；
- harness 新进程的工作目录仍是仓库，要额外授权它访问数据根（`grants`）；
- 阶段树里写的检查点命令（相对仓库根）要改写成在数据根下能直接运行的形式。

解析规则只在这里定义一次：`--root` > MDF_DATA_ROOT > 仓库根（tests/test_workspace.py 防止别处再写一遍）。
"""

from __future__ import annotations

import os
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

CODE_ROOT = Path(__file__).resolve().parents[1]
ENV = "MDF_DATA_ROOT"


@dataclass(frozen=True)
class Workspace:
    data_root: Path
    code_root: Path = CODE_ROOT

    def __post_init__(self) -> None:  # 值对象：同一目录的不同写法相等
        object.__setattr__(self, "data_root", Path(self.data_root).resolve())
        object.__setattr__(self, "code_root", Path(self.code_root).resolve())

    @classmethod
    def resolve(cls, root: str | os.PathLike[str] | None = None, *, environ: Mapping[str, str] | None = None,
                code_root: Path = CODE_ROOT) -> "Workspace":
        environ = os.environ if environ is None else environ
        return cls(Path(root or environ.get(ENV) or code_root), code_root)

    @property
    def separate(self) -> bool:
        return self.data_root != self.code_root

    def grants(self) -> tuple[str, ...]:
        """新进程除工作目录（仓库）外还要被授权访问的目录。"""
        return (self.data_root.as_posix(),) if self.separate else ()

    def child_env(self, base: Mapping[str, str] | None = None) -> dict[str, str]:
        return {**(os.environ if base is None else base), ENV: str(self.data_root), "PYTHONUTF8": "1"}

    @property
    def ephemeral(self) -> bool:
        """数据根落在桌面版的 worktree 池（`.claude/worktrees/<名字>/`）里。worktree 被回收时，被 gitignore 的
        sources/、output/ 一起消失，没有任何提示（2026-10-19 鲁迅 GUI 验收发现 0：第一轮跑到 3A 的产物全丢了）。"""
        parts = [p.lower() for p in self.data_root.parts]
        return any(a == ".claude" and b == "worktrees" for a, b in zip(parts, parts[1:]))

    def risk_notice(self) -> str | None:
        if not self.ephemeral:
            return None
        return (f"⚠️ 数据根在临时 worktree 里（{self.data_root.as_posix()}）：worktree 被回收时 sources/、output/ "
                f"会一起消失。长流水线先把 {ENV} 指向 worktree 之外的目录（例如主仓库），再继续。")

    def checkpoint_argv(self, command: str, slug: str, python: str = sys.executable) -> list[str]:
        """检查点命令 → 在数据根下执行的 argv：`python` 换成给定解释器，`scripts/*.py` 换成仓库里的绝对路径，
        其余参数（sources/… output/…）留给数据根解析。只放行 `python scripts/<脚本>.py …`：mdf run 会直接执行它。"""
        tokens = shlex.split(command.replace("{slug}", slug))
        if len(tokens) < 2 or tokens[0] not in ("python", "python3") or not re.fullmatch(r"scripts/\w+\.py", tokens[1]):
            raise SystemExit(f"检查点命令不是 python scripts/<脚本>.py 形式，不会执行：{command}")
        tokens[0] = python
        return [(self.code_root / t).as_posix() if t.startswith("scripts/") and t.endswith(".py") else t
                for t in tokens]

    def runnable(self, command: str, slug: str) -> str:
        """给执行者看、在本机能直接运行的一行命令。

        连环境变量一起给：mdf 按 --root > MDF_DATA_ROOT > 仓库根找数据根，不看当前目录，只 cd 过去会落回仓库根；
        拿到简报的 GUI 子代理没有这个变量（mdf run 的新进程有），`mdf reduce` 也不收 --root。"""
        data = self.data_root.as_posix()
        return f"cd '{data}' && {ENV}='{data}' " + shlex.join(self.checkpoint_argv(command, slug, python="python"))


def data_root(root: str | os.PathLike[str] | None = None) -> Path:
    """各脚本的 `--root` 参数与 repo_root() 都走这里。"""
    return Workspace.resolve(root).data_root
