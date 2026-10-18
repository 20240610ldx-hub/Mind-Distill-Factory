# harness 适配

同一条流水线可以在 Claude Code、Codex、pi 里跑。三者能力不同（有没有子代理、有没有章节导航），工厂的做法是：**协议只写一份**（`commands/distill.md` + `agents/*.md`），每个 harness 只配一个轻量入口；缺的能力用确定性命令补齐。

> 下文关于各 harness 的事实核对于 **2026-10-17**，来源列在 `config/harnesses.json` 的 `sources` 字段里；用到的命令行参数另外在本机版本的 `--help` 里逐一核对过：codex-cli 0.145.0（`exec --sandbox workspace-write`）、pi 0.65.2（`-p`）、Claude Code 2.1.301（`-p`、`--permission-mode`、`--plugin-dir`）。harness 迭代很快，以官方文档为准；`python scripts/mdf.py harness` 现场检测本机情况。

## 总表

| | Claude Code | Codex | pi |
|---|---|---|---|
| 入口文件 | `.claude-plugin/plugin.json`（插件） | `.agents/skills/mdf-distill/SKILL.md` | 同 Codex（pi 也扫描 `.agents/skills`） |
| 加载 | 仓库根目录 `claude --plugin-dir .` | 在仓库根目录启动 `codex` | 在仓库根目录启动 `pi` |
| 启动编排 | `/mind-distill-factory:distill <人物>` | `$mdf-distill <人物>` | `/skill:mdf-distill <人物>` |
| 读的规则文件 | `CLAUDE.md` | `AGENTS.md` | `AGENTS.md` 与 `CLAUDE.md`（拼接） |
| 子代理 | 原生（Task 工具 + `agents/*.md`） | 官方文档未核实到稳定接口，不依赖 | 不内置（README 明确说明） |
| 隔离执行一个步骤 | 子代理；或 `claude -p` | `codex exec --sandbox workspace-write "…"` | `pi -p "…"` |
| 章节导航 | 桌面版有章节工具 | 无可调用的章节 API | 无 |
| 已发布技能装到 | `~/.claude/skills/<name>/` | `~/.agents/skills/<name>/` | `~/.agents/skills/<name>/`（也认 `~/.pi/agent/skills/`） |

## 三个补齐机制

### 1. 任务简报 `mdf brief`：没有子代理也能隔离

```bash
python scripts/mdf.py brief <slug>            # 下一个未完成的 agent 步骤
python scripts/mdf.py brief <slug> review     # 指定步骤
```

它把一个 agent 步骤打包成一个自足的 Markdown 文件 `output/<slug>/briefs/<step>.md`，内容包括：当前状态与待办（取自 `mdf status`）、规则、检查点命令、该步骤所有角色定义的全文（`{slug}` 已替换）。然后打印各 harness 的新进程命令：

```bash
codex exec --sandbox workspace-write "读取 output/<slug>/briefs/review.md 并严格按其执行，完成后报告检查点结果。"
```

```bash
pi -p "读取 output/<slug>/briefs/review.md 并严格按其执行，完成后报告检查点结果。"
```

注意 `codex exec` 默认是只读沙箱，要写产物必须加 `--sandbox workspace-write`（旧的 `--full-auto` 已不再支持）。分片抽取这类可拆的活可以同时起多个进程。

Stage 5 审查的简报额外声明「你是独立审查者」。新进程从没见过生成过程，所以「不得自审」在没有子代理的 harness 里也成立。

**`mdf run`：简报 + 新进程 + 等待 + 闸门，一条命令。** 墨子试跑时，编排者手写 `until [ -f x.done ]; do sleep 5; done` 去等无头进程，后台任务面板里只有一串看不懂的 shell。现在用：

```bash
python scripts/mdf.py run <slug> [step] --harness codex          # 阶段卡 + 计划，不执行
python scripts/mdf.py run <slug> [step] --harness codex --yes    # 用户同意后执行
```

它先打印阶段卡，再生成简报，然后按 `config/harnesses.json` 的 `isolated_run` 起新进程。命令不经过 shell，提示词作为一个参数传入。`--model`、`--effort` 按各 harness 档案声明的参数传入（`model_flag`、`effort_flag`），都插在提示词前面：

| | Claude Code | Codex | pi |
|---|---|---|---|
| 模型 | `--model` | `--model`（放在 `exec` 子命令里） | `--model` |
| 推理强度 `--effort` | `--effort low…max` | 没有对应参数，指定了就报错 | `--thinking off…xhigh` |
| 授权数据根 | `--add-dir`（放在命令末尾） | `--add-dir` | 不需要（没有目录沙箱） |

数据根不在仓库里时（worktree 里没有私有语料，`MDF_DATA_ROOT` 指向别处），新进程的工作目录仍是仓库，额外授权它读写数据根。Claude Code 的 `--add-dir` 和 `--allowedTools` 一样是可变参数，所以放在末尾，不会吞掉提示词。简报这时多一条「路径约定」：`sources/…`、`output/…` 在数据根下，`scripts/…` 在仓库里。另附一条在本机能直接运行的检查点命令（先 cd 到数据根，脚本用仓库里的绝对路径）。`mdf run` 自己跑检查点时用的是同一套改写。

运行中每 30 秒一行心跳：

```
  … 1分30秒 · 日志 12.4 KB · 新产物 3 个 · 最近输出：已写 shard_004_extracts.json
```

结束后报这一步的状态变化（如「⬜ 待办 → ✅ 完成」），并跑这一步自己的检查点（阶段树里步骤级的 `checkpoint`，例如审查步骤是 `validate package <slug> --strict`）；本阶段的步骤全部完成时，再跑阶段检查点。Claude Code 的无头进程用 `--output-format stream-json --verbose`（stream-json 必须带 `--verbose`）。每行一个事件，心跳里的「最近」就是最后一次工具调用（如「Read shard_001.json」）。结束时的结果对象给出费用、轮数、缓存读取 token 和被拒的工具调用数，都写进结果行和运行记录。2026-10-18 用 Sonnet 5.5 实测时发现两点：一是改用流式之前，只用 `json` 要到进程结束才输出，心跳一直是「日志 0.0 KB」；二是结果对象的字段顺序不固定，以 `duration_api_ms` 起头，按 `{"type":"result"` 前缀去找会丢掉费用。所以现在逐行解析。墨子试跑 9 次调用合计 $6.04，大头是缓存读。Codex、pi 的用量格式没有核实，不解析。最后打一行进度条，记录追加到 `output/<slug>/runs/runs.jsonl`。新进程按量计费，所以不加 `--yes` 只打印计划、什么也不写（fail-closed）。后台任务面板里显示的就是 `mdf run <slug> <step>`，一眼能看出在跑哪一步。

### 2. 章节标签与 H2 兜底：左侧的阶段轨

章节规则写在 `config/pipeline_stages.json` 的 `chapter_policy`：每进入一个阶段打一次标签。Claude 桌面版的章节工具是 `mcp__ccd_session__mark_chapter`（常列在 deferred 工具里，先用 ToolSearch 加载），调用后左侧出现可跳转的「阶段 N · 标题」；Codex、pi、终端输出同名的 H2 标题（如 `## 阶段 2 · 原则提取`），在长对话里可以搜索。Codex App 的长线程导航是按轮次跳转的，H2 标题落在对应那一轮里，同样能用。

章节由编排者打。只要在驱动流水线，就算每一步都交给新进程、自己只是在等，也算编排者。墨子试跑没有打标签，原因是驱动会话把自己当成了「测试脚本」。现在 `commands/distill.md` 写明了这一点，还规定了每个阶段的三拍叙述：开场贴阶段卡（`mdf next <slug> --card`），过程只在有新信息时开口，收尾贴结果行和进度条。

### 3. 状态面板 `mdf status`：不靠对话记忆

`python scripts/mdf.py status <slug>` 只看磁盘产物，就能重建进度，表格末尾附一行进度条（▶ 当前、▰ 完成、◐ 部分完成、✖ 未通过、▱ 未开始）。`--json`（schema `pipeline-status-v1`）给 GUI 或其他工具读。中断后换一个 harness 接着做，进度不丢。

`--html` 生成自包含的可视化面板 `output/<slug>/status.html`，不引用任何外部资源，离线可开，深浅色、手机宽度都适配。面板内容：

- 左侧是阶段轨，与对话里的章节一一对应；
- 右侧逐阶段列出步骤状态、说明、下一步和闸门命令；
- 当前阶段高亮；
- 底部是 `mdf run` 的运行记录。

在 Claude 桌面版里，编排者用文件发送工具以渲染方式打开它；其他 harness 给出文件路径即可。

## 安装已发布的技能

工厂不往仓库外写文件（发布时自动安装的功能曾被刻意移除，是否恢复待定）。要装进某个 harness，先打印命令：

```bash
python scripts/mdf.py harness plan zhang-juzheng-v6 --target codex
```

它核对 gallery 包与 manifest，按 SKILL.md 的 `name` 定目标目录，给出 bash 与 PowerShell 两种复制命令（不复制 `人物档案.md`），并提示兼容性问题，例如 `argument-hint` 是 Claude Code 专有字段，其他 harness 会忽略。命令由你自己执行。

## Claude Code 补充

- `claude plugin validate .` 应当通过。唯一的警告是「插件根目录的 CLAUDE.md 不作为插件上下文加载」：在仓库根目录工作时，Claude Code 本来就把它当项目上下文读，不受影响。
- 插件里的子代理带命名空间，例如 `mind-distill-factory:quality-reviewer`。
- 不想用插件，也可以把 `commands/`、`agents/` 链接进项目的 `.claude/` 目录（该目录在 `.gitignore` 里，不会入库）。

## 已知限制

- **AGENTS.md 与 CLAUDE.md 是两份文件**：`AGENTS.md` 已对齐 v6，并补了 `mdf` 入口与进度协议；以后改规则要两份一起改，冲突时以 `CLAUDE.md` 为准。`mdf harness` 会检查 `AGENTS.md` 是否仍是 v6。
- **Codex 子代理**：二手资料称已正式提供，但说法互相矛盾，官方文档里没有核实到，所以流水线不依赖它，统一走简报 + 新进程。
- **gallery 包的 frontmatter**：含 `format_version`、`argument-hint` 等非 Agent Skills 标准字段。Codex、pi 是否对此告警没有逐一验证；`harness plan` 会提示。
- **Codex、pi 仍没有端到端实测**：墨子试跑（[harness-trial-mozi.md](harness-trial-mozi.md)）用 `claude -p` 新进程走完了简报路径（到发布），修掉了简报缺口，但 Codex、pi 本身没有跑过。首次使用请留意 agent 是否按简报写对了文件，检查点会兜底。
- **Claude Code 无头模式需要 `--allowedTools`**：只给 `--permission-mode acceptEdits` 时 Bash 被拦，执行者跑不了检查点命令；`mdf brief` 打印的命令和 `mdf run` 已带上 `--allowedTools Bash,Read,Write,Edit,Glob,Grep`（等于授权该进程执行任意 shell，自行判断）。提示词必须写在 `--allowedTools` 前面：它是可变参数，排在它后面的位置参数会被当成工具名吞掉。
