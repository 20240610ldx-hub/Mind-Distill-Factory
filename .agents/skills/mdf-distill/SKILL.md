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
3. **类目由用户定**：按 `config/taxonomy.json` 推荐 1 主 + 至多 2 副，用 harness 的提问工具（Claude Code 是 `AskUserQuestion`）让用户确认，再 `python scripts/mdf.py classify <slug> --primary <主类> --secondary <副类1,副类2>` 落盘。原则提取之后的简报没有这份记录会被拒绝生成；产物类目与之不符，`validate` 报 `CLASSIFICATION_MISMATCH`。
4. 动手前先读 `commands/distill.md` 里对应阶段的那一节。现行规则是 `CLAUDE.md`（v6）；`AGENTS.md` 与它冲突时，以 `CLAUDE.md` 为准。

## 每个阶段

每个阶段按三拍说话，全程中文（细则见 `commands/distill.md`「叙述节奏」）：

0. **整条流水线开始时**：用 harness 自带的任务清单工具（Codex 是计划工具）建一份阶段清单，每个阶段一项，标题与章节同名，取自 `python scripts/mdf.py status <slug> --json`。之后只更新它：进入阶段置进行中，闸门通过置完成。没有任务清单工具时，每阶段收尾贴进度条代替。
1. **开场**：先打章节标签。harness 有章节工具就调用；没有就输出一行 H2，例如 `## 阶段 2 · 原则提取`。任务清单里这一项置为进行中。然后把 `python scripts/mdf.py next <slug> --card` 的阶段卡原样贴给用户。同一阶段内不再重复。
2. **过程**：
   - **脚本步骤**：照阶段卡或 `python scripts/mdf.py next <slug>` 给出的命令执行。
   - **agent 步骤**：harness 有子代理，就把 `python scripts/mdf.py brief <slug>` 生成的简报交给子代理。没有子代理，就用 `python scripts/mdf.py run <slug> --harness <codex|pi>` 交给新进程：它先打印计划，用户同意后加 `--yes` 执行，运行中自带心跳和日志，不要自己写轮询循环。分片抽取这类可以拆开的活，可以同时起多个进程。语料只有 1 个分片时，`mdf run` 会把分片抽取、合并与本地补充、原则提取合成一个执行单位 `small-corpus`：一份简报、一个进程，三个检查点都跑。开跑前打阶段 1 的标题，跑完再打阶段 2 的标题，两个阶段的结果都要看。
   - 只在有新信息时开口，每次一两句。
3. **收尾**：每个阶段结束都跑 `python scripts/mdf.py validate <stage> <slug>`，不通过就不进入下一阶段，修好再跑。然后贴一行结果（闸门、产物、下一步），把任务清单里这一项置为完成。不另做 HTML 面板。

## 不可违反

- Stage 5 审查必须在独立上下文里做（子代理，或 `python scripts/mdf.py run <slug> review --harness <名称> --yes`），编排者不得自己审自己。
- 执行简报的新进程或子代理不得再派子代理：隔离靠它本身，简报里写着禁令。`mdf run` 结果行下出现「⚠️ 新进程又派了 N 个子代理」的告警时，告诉用户，按检查点核对产物后再决定重跑还是继续。
- 权利声明（`sources/<slug>/rights.json`）、在世人物是否蒸馏、是否发布，都要问用户，不能替用户决定。依据见 `docs/ethics-and-legal.md`。
- 不要自己爬网页：采集原典只用 `python scripts/mdf.py acquire`。阶段 1 的合并与补充（reduce）**禁用网络检索**，只读本地语料；缺素材就问用户要不要 `mdf acquire`。
- 换行符一律 LF。发布前由你检查 `output/<slug>/` 里要发布的文本文件有没有 CRLF，有就转成 LF、重跑 `validate package` 再发布——manifest 记的是字节 hash，入库后 `.gitattributes` 会把 CRLF 改掉。
- 不往仓库外写文件。发布用 `python scripts/mdf.py publish`；要装进 harness 的技能目录，用 `python scripts/mdf.py harness plan <slug> --target <harness>` 打印命令，交给用户执行。
