#!/usr/bin/env python3
"""执行单位：一次 `mdf run`（一份简报、一个新进程）要做的事。

通常就是一个 agent 步骤。阶段树 `bundles` 里声明的相邻步骤，在语料不超过 `max_shards` 个分片时合成一个单位：
简报只有一份，角色依次执行，成员的检查点都跑。墨子试跑第 14 条（用户 2026-10-20 决定）：语料只有 1 个分片时，
抽取、合并、原则提取三个进程读的几乎是同一批材料，每个都要重读一遍上下文，费用大头是缓存读。多分片时照旧分开。

简报（harness.build_brief）、`mdf run`（stage_runner）与阶段卡（pipeline_status.render_card）都从这里判断。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterable, NamedTuple


class RunUnit(NamedTuple):
    id: str
    title: str
    members: tuple[tuple[dict[str, Any], dict[str, Any]], ...]  # (phase, step)，按执行顺序
    note: str = ""

    @property
    def is_bundle(self) -> bool:
        return len(self.members) > 1

    @property
    def step_ids(self) -> list[str]:
        return [step["id"] for _, step in self.members]

    @property
    def steps_text(self) -> str:
        return " → ".join(step["title"] for _, step in self.members)

    @property
    def forbids_network(self) -> bool:
        return any(step.get("network") == "forbidden" for _, step in self.members)

    @property
    def requires(self) -> set[str]:
        return {need for _, step in self.members for need in step.get("requires", [])}

    def member_checkpoints(self) -> list[tuple[dict[str, Any], list[str]]]:
        """合并单位里每个成员做完要过的检查点（`{slug}` 未替换）：它自己的，加上由它收尾的阶段的。"""
        gates = []
        for phase, step in self.members:
            commands = [step["checkpoint"]] if step.get("checkpoint") else []
            if phase.get("checkpoint") and step["id"] == phase["steps"][-1]["id"]:
                commands.append(phase["checkpoint"])
            gates.append((step, list(dict.fromkeys(commands))))
        return gates

    def checkpoints(self, phase_finished: Callable[[str], bool]) -> list[str]:
        """要跑的检查点命令（`{slug}` 未替换），按执行顺序、去重。

        单个步骤：它自己的检查点；本阶段的步骤都做完了，再加阶段检查点（中间步骤先跑阶段检查点必然失败，墨子试跑发现 1）。
        合并单位：每个成员的检查点一律都跑——成员都在同一个进程里做完，阶段也由它收尾。
        """
        if self.is_bundle:
            return list(dict.fromkeys(c for _, commands in self.member_checkpoints() for c in commands))
        phase, step = self.members[0]
        commands = [step["checkpoint"]] if step.get("checkpoint") else []
        if phase.get("checkpoint") and phase_finished(phase["id"]):
            commands.append(phase["checkpoint"])
        return list(dict.fromkeys(commands))


def _find(tree: dict[str, Any], step_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    for phase in tree["phases"]:
        for step in phase["steps"]:
            if step["id"] == step_id:
                return phase, step
    raise SystemExit(f"阶段树里没有步骤 {step_id!r}（mdf stages 查看全部）")


def plan(tree: dict[str, Any], step_id: str, *, pending: Iterable[str], shard_count: int | None) -> RunUnit:
    """step_id（步骤 id 或合并单位 id）要落成哪个执行单位。

    合并的条件：语料有分片清单且分片数 ≤ max_shards；所请求的步骤本身还没完成（重跑一个已完成的步骤只跑它）；
    从它起、单位里还没完成的步骤至少两个（只剩一步就不用合并）。直接点名合并单位却不满足条件，报 ValueError。
    """
    pending = set(pending)
    for bundle in tree.get("bundles") or []:
        if step_id != bundle["id"] and step_id not in bundle["steps"]:
            continue
        start = 0 if step_id == bundle["id"] else bundle["steps"].index(step_id)
        members = [s for s in bundle["steps"][start:] if s in pending]
        small = shard_count is not None and 1 <= shard_count <= bundle["max_shards"]
        if small and len(members) >= 2 and (step_id == bundle["id"] or step_id in pending):
            return RunUnit(bundle["id"], bundle["title"], tuple(_find(tree, s) for s in members), bundle.get("note", ""))
        if step_id == bundle["id"]:
            raise ValueError(f"「{bundle['title']}」只在语料不超过 {bundle['max_shards']} 个分片、且 "
                             f"{'、'.join(bundle['steps'])} 里至少还有两步没做完时可用；"
                             f"当前分片数 {shard_count if shard_count is not None else '未知（还没跑 mdf index）'}，"
                             f"未完成 {len(members)} 步。改为按步骤运行")
    phase, step = _find(tree, step_id)
    return RunUnit(step_id, step["title"], ((phase, step),))


def shard_count(root: Path, slug: str) -> int | None:
    """分片清单里的分片数；没有清单（还没 mdf index，或没有本地素材）返回 None。"""
    path = root / "sources" / slug / "processed" / "local_shards" / "manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(manifest, dict):
        return None
    shards = manifest.get("shards")
    return len(shards) if isinstance(shards, list) else manifest.get("shard_count")
