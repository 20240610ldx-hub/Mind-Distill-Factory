#!/usr/bin/env python3
"""工作区：代码根（仓库）+ 数据根（语料与产物）。

代码根放 scripts/ agents/ config/ 和入库的发布产物 gallery/；数据根放 sources/ output/。通常两者是同一个目录。
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


def _parts(text: str) -> list[str]:
    return [p for p in re.split(r"[\\/]+", text) if p]


def _is_absolute(text: str) -> bool:  # 跨平台判断：Windows 写下的路径可能在 posix 上读回，反之亦然
    return bool(re.match(r"[\\/]|[A-Za-z]:", text))


def _anchor(parts: list[str]) -> int | None:
    """数据根之下的第一级目录在路径里的位置：`sources/<slug>/processed/…` 或 `output/…`。
    取最后一处匹配：旧数据根的上级目录叫 output / sources 时，不会被误认成锚点。"""
    found = None
    for i, part in enumerate(parts[:-1]):
        name = part.lower()
        if name == "output" or (name == "sources" and len(parts) > i + 2 and parts[i + 2].lower() == "processed"):
            found = i
    return found


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

    @classmethod
    def containing(cls, artifact: str | os.PathLike[str], code_root: Path = CODE_ROOT) -> "Workspace | None":
        """产物文件（`<数据根>/sources|output/…`）所在的工作区；路径不在这个布局里就返回 None。
        状态文件据此认出自己属于哪个数据根，不看环境变量，所以数据根被复制或挪走后仍然自洽。"""
        parts = list(Path(artifact).resolve().parts)
        i = _anchor(parts)
        return cls(Path(*parts[:i]), code_root) if i else None

    def locate(self, stored: str | os.PathLike[str]) -> Path:
        """产物里存的路径 → 当前数据根下的真实路径。相对路径挂到数据根下；旧版存的绝对路径只取
        `sources/…` 或 `output/…` 起的部分重新挂上，不信任写入时的那个位置；认不出布局的绝对路径原样返回。"""
        text = os.fspath(stored)
        parts = _parts(text)
        if not _is_absolute(text):
            return self.data_root.joinpath(*parts)
        i = _anchor(parts)
        return self.data_root.joinpath(*parts[i:]) if i is not None else Path(text)

    def portable(self, path: str | os.PathLike[str]) -> str:
        """写进产物的路径：相对数据根的 posix 形式，数据根复制或挪走后依然有效。"""
        text = os.fspath(path)
        if not text:
            return ""
        parts = _parts(text)
        if _is_absolute(text):
            try:
                return Path(text).resolve().relative_to(self.data_root).as_posix()
            except ValueError:
                i = _anchor(parts)
                return "/".join(parts[i:]) if i is not None else Path(text).as_posix()
        return "/".join(parts)

    @property
    def gallery(self) -> Path:
        """发布产物入库，跟着代码根（当前分支）走，不跟数据根：在 worktree 里发布、数据根指向主检出时，
        写数据根下的 gallery/ 会绕过 worktree 和分支，直接改主检出里入库的文件。"""
        return self.code_root / "gallery"

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
