---
name: mdf-distill
description: >-
  驱动 Mind Distill Factory 流水线，把一位思想家的公开著述蒸馏成 v6 思维框架 Skill
  （采集、清洗、抽取、原则、框架、组装、审查、发布）。用户要求蒸馏（distill）某位人物、
  查看或继续某个人物的流水线进度时使用。只在 mind-distill-factory 仓库根目录下可用。
---

# Mind Distill Factory 流水线驱动

你是编排者：确定性的活交给 `python scripts/mdf.py`，需要判断的活按 `agents/` 里的角色定义去做。完整协议写在 `commands/distill.md`；本文件只说明在 Codex、pi 这类 harness 里怎么跑它（Claude Code 用插件命令 `/mind-distill-factory:distill`）。

## 开工

1. `python scripts/mdf.py doctor` 自检环境；`python scripts/mdf.py harness` 核对适配文件。
2. `python scripts/mdf.py status <slug>` 看进度；新人物先跑 `python scripts/mdf.py init <slug>`。
3. 动手前先读 `commands/distill.md` 里对应阶段的那一节。现行规则是 `CLAUDE.md`（v6）；`AGENTS.md` 与它冲突时，以 `CLAUDE.md` 为准。

## 每个阶段

- **进入新阶段先打标签。** harness 有章节工具就调用；没有就输出一行 H2，例如 `## 阶段 2 · 原则提取`（`python scripts/mdf.py stages` 列出全部阶段）。同一阶段内不再重复。
- **脚本步骤**：照 `python scripts/mdf.py next <slug>` 给出的命令执行。
- **agent 步骤**：先跑 `python scripts/mdf.py brief <slug>`，生成任务简报（角色定义、输入输出、检查点），再：
  - harness 有子代理，就把简报交给子代理；
  - 没有子代理，就用新进程执行，命令由 `brief` 打印出来，例如 Codex 用 `codex exec --sandbox workspace-write "读取 <简报> 并严格按其执行…"`，pi 用 `pi -p "…"`；
  - 分片抽取这类可以拆开的活，可以同时起多个进程。
- **检查点**：每个阶段结束都跑 `python scripts/mdf.py validate <stage> <slug>`；不通过就不进入下一阶段，修好再跑。

## 不可违反

- Stage 5 审查必须在独立上下文里做（子代理或新进程跑 `mdf brief <slug> review`），编排者不得自己审自己。
- 权利声明（`sources/<slug>/rights.json`）、在世人物是否蒸馏、是否发布，都要问用户，不能替用户决定。依据见 `docs/ethics-and-legal.md`。
- 不要自己爬网页：采集原典只用 `python scripts/mdf.py acquire`。
- 不往仓库外写文件。发布用 `python scripts/mdf.py publish`；要装进 harness 的技能目录，用 `python scripts/mdf.py harness plan <slug> --target <harness>` 打印命令，交给用户执行。
