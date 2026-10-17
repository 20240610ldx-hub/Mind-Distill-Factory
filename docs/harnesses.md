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

### 2. H2 兜底标题：没有章节工具也能定位

章节规则写在 `config/pipeline_stages.json` 的 `chapter_policy`：每进入一个阶段打一次标签。Claude 桌面版调用章节工具，左侧出现可跳转的「阶段 N · 标题」；Codex、pi、终端输出同名的 H2 标题（如 `## 阶段 2 · 原则提取`），在长对话里可以搜索。Codex App 的长线程导航是按轮次跳转的，H2 标题落在对应那一轮里，同样能用。

### 3. 状态面板 `mdf status`：不靠对话记忆

`python scripts/mdf.py status <slug>` 只看磁盘产物，就能重建进度；`--json`（schema `pipeline-status-v1`）给 GUI 或其他工具读。中断后换一个 harness 接着做，进度不丢。

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

- **AGENTS.md 过时**：它还停在 v6 之前的规则（「双语合一 SKILL.md」），Codex 和 pi 都会读到。编排 skill 已声明以 `CLAUDE.md` 为准，但根治需要同步 `AGENTS.md`；文档分支 `claude/dreamy-hamilton-3fd992` 做了这件事，尚未合并。`mdf harness` 会对此给出 ⚠️。
- **Codex 子代理**：二手资料称已正式提供，但说法互相矛盾，官方文档里没有核实到，所以流水线不依赖它，统一走简报 + 新进程。
- **gallery 包的 frontmatter**：含 `format_version`、`argument-hint` 等非 Agent Skills 标准字段。Codex、pi 是否对此告警没有逐一验证；`harness plan` 会提示。
- **Codex、pi 仍没有端到端实测**：墨子试跑（[harness-trial-mozi.md](harness-trial-mozi.md)）用 `claude -p` 新进程走完了简报路径（到发布），修掉了简报缺口，但 Codex、pi 本身没有跑过。首次使用请留意 agent 是否按简报写对了文件，检查点会兜底。
- **Claude Code 无头模式需要 `--allowedTools`**：只给 `--permission-mode acceptEdits` 时 Bash 被拦，执行者跑不了检查点命令；`mdf brief` 打印的命令已带上 `--allowedTools Bash Read Write Edit Glob Grep`（等于授权该进程执行任意 shell，自行判断）。
