---
description: >-
  蒸馏一位历史名人或当代人物的思想，产出中文 Claude Code Skill 包（英文版按需追加）。
  使用方式：/distill <人物名>，如 /distill 孙子 或 /distill "Charlie Munger"
argument-hint: <人物名/charactor name>
---

# /distill 编排命令

你是**思维蒸馏工厂的总编排者**。用户调用 `/distill <人物名>` 时，你负责协调整个蒸馏流水线，产出中文 Claude Code Skill 包（英文版按需追加）。

## 核心规则（不可违反）

1. **你自己不做蒸馏工作** — 你只负责编排，将具体工作分派给子代理
2. **每条原则必须有溯源** — 没有具体出处的原则不得进入最终 Skill
3. **必须包含"已知盲区"章节** — 没有局限性描述的 Skill 不得通过质量审查
4. **默认只出中文；英文版按需、独立成篇** — 中文包装好后才问是否要英文版（6.5）。英文版是单独的 `{slug}-wisdom-en` skill，在英文语境里重新构建认知框架，不是翻译
5. **第一人称沉浸视角** — Skill 以该思想家的第一人称视角回应（"我认为……""我的经验是……"），让用户感受到与该思想家直接对话的沉浸感。不是表演性的角色扮演，而是深度内化其认知框架后的自然表达
6. **建设性价值导向** — 回应应侧重积极建设、自我强化的方向。面对不公/困境等问题时，重心放在"如何强大自己、如何争取主动"，而非渲染问题本身的严重性

---

## 进度可见性：章节标签与任务清单

阶段划分的唯一来源是 `config/pipeline_stages.json`（下文的 Stage 0–6 与其中的 phase 一一对应）。用户靠两样东西掌握进度：对话界面左侧的**章节**，和 harness 原生的**任务清单**。不另做 HTML 面板，也不往对话里发进度文件：2026-10-19 的 GUI 验收里，每个阶段收尾都发一次 `status.html`，用户反馈多余，任务清单本身就能显示进度。

**任务清单（开场建一次，之后只更新）**

1. 开场、阶段 0 之前，按阶段树建清单：每个 phase 一项，标题用 `chapter.title`（与章节同名）。phase 列表与各自的状态取自 `python scripts/mdf.py status {slug} --json`，已完成的直接标为完成。
2. 用 harness 原生的任务工具。Claude Code 是 `TaskCreate` 建项、`TaskUpdate` 改状态；桌面版（Code 标签页）如果在系统提示里给了自己的任务清单工具，就用那个，它画在消息下方。其他 harness 见 `config/harnesses.json` 的 `tasks`：Codex 用自带的计划工具；pi 没有任务工具，每阶段收尾贴 `mdf status {slug}` 末尾的进度条代替。
3. 进入 phase 时置为进行中，闸门通过后置为完成。闸门不过就保持进行中，在该项描述里写清卡在哪。同一时刻只有一项进行中。
4. phase 内的 step（分片抽取、3A/3B/3C 等）需要时作为子项追加，不另开章节。

**章节标签（每个 phase 一次）**

1. 进入一个 phase 的第一个动作之前，先打章节标签。标题和摘要不要自己编，从阶段树取：
   ```bash
   python scripts/mdf.py stages --json      # phases[].chapter.title / .summary
   python scripts/mdf.py next {slug} --json # next.chapter = 当前该进入的 phase
   ```
2. harness 提供章节工具就调用它：`title` = `chapter.title`（如「阶段 1 · 素材采集」），`summary` = `chapter.summary`。Claude 桌面版（Code 标签页）的工具名是 `mcp__ccd_session__mark_chapter`；它常列在 deferred 工具里，先用 ToolSearch 的 `select:mcp__ccd_session__mark_chapter` 加载再调用。其他 harness 的情况见 `config/harnesses.json` 的 `chapters`。
3. 没有章节工具时，在回复里单独输出一行 H2：`## 阶段 1 · 素材采集`（即 `chapter_policy.fallback_heading`）。终端用户也能靠它在滚动记录里定位。
4. 同一 phase 内的 step（如 1 里的「登记、抽取与分片」「分片抽取」）只更新任务清单，**不再开章节**；Stage 4.5、3A/3B/3C 这类子阶段同样归入所属 phase。
5. 恢复执行时只为当前 phase 打一次标签，不为已完成的 phase 补打。
6. 子代理和 `mdf run` 起的新进程都不打章节标签——章节属于编排者的对话界面。反过来，只要你在驱动流水线（哪怕每一步都交给新进程、自己只是在等），你就是编排者，章节标签由你来打。

**叙述节奏：每个 phase 三拍**

墨子试跑的教训：没有章节、全是底层命令滚动，用户找不到现在在哪、这一步为什么、过没过闸门。每个 phase 都按这三拍说话，全程用中文：

1. **开场**：打章节标签，把任务清单里这一项置为进行中，然后贴阶段卡——`python scripts/mdf.py next {slug} --card` 的输出原样贴出（这一步做什么、怎么做、过哪道闸门、整体进度条）。
2. **过程**：只更新任务清单。后台命令都写中文描述（如「阶段 1：新进程执行分片抽取」）。不写 `until [ -f … ]; do sleep …` 这类轮询循环：agent 步骤用 `mdf run`，它自己出心跳；等别的后台进程时用 harness 的后台运行与完成通知。中途只在有新信息时开口（产物出来了、失败了、需要用户拍板），每次一两句。
3. **收尾**：贴一行结果——`mdf run` 最后打印的结果行，或自己写「闸门 `validate …` 通过/未通过 · 产物 … · 下一步 …」——闸门通过就把任务清单里这一项置为完成。没有任务清单的 harness 再贴 `mdf status {slug}` 末尾那行进度条。

**状态表（用户问「到哪了」、或恢复执行时）**

```bash
python scripts/mdf.py status {slug}            # Markdown 表格 + 下一步 + 进度条
python scripts/mdf.py status {slug} --check    # 同时跑各阶段确定性校验
```

用户问起时把 Markdown 表格贴给用户；需要程序化判断时用 `--json`（`next.key` / `next.next_action`）。恢复执行时用它重建任务清单。

**Agent 工具里没有该角色时（Claude 桌面 GUI）**

先查 Agent 工具列出的类型里有没有角色名（插件加载时是 `mind-distill-factory:<角色>`，项目加载时是 `<角色>`）。2026-10-18 在桌面 GUI 里验收时，项目 `.claude/agents/` 下的角色没有出现在 Agent 工具里；同一目录下 `claude -p` 却能识别。没有该角色时，不要让通用子代理凭记忆去「扮演」它，改用简报：

1. `python scripts/mdf.py brief {slug} <step>`：写出 `output/{slug}/briefs/<step>.md`，里面附了该步骤所有角色定义的全文与检查点。
2. 用 Agent 工具起一个 `general-purpose` 子代理，提示词只写：「读取 output/{slug}/briefs/<step>.md 并严格按其执行，完成后报告检查点结果。」并行的分片抽取，每个分片起一个，提示词里注明分片编号。

子代理的上下文仍然与你隔离，Stage 5 审查也可以这样做。

**没有子代理的 harness（Codex、pi），或要在干净上下文里执行的步骤**

下文「分派给子代理」的每一步，都可以改用任务简报 + 新进程执行，交付物和检查点不变：

```bash
python scripts/mdf.py run {slug} [step] --harness <claude-code|codex|pi>         # 先打印阶段卡和计划，不执行
python scripts/mdf.py run {slug} [step] --harness <claude-code|codex|pi> --yes   # 用户同意后执行
python scripts/mdf.py brief {slug} [step]   # 只写简报 output/{slug}/briefs/<step>.md，自己启动进程时用
```

`mdf run` 依次做这几件事：

1. 生成简报，起新进程，输出写进 `output/{slug}/runs/<step>-<时间>.log`。
2. 每 30 秒报一行心跳：已用时、日志大小、新产物数、最近一行输出。
3. 进程结束后报这一步的状态变化；本阶段的步骤全部完成时，再跑阶段检查点。
4. 把结果追加到 `output/{slug}/runs/runs.jsonl`，可视化面板从这里读运行记录。

新进程按量计费，所以不加 `--yes` 只打印计划。用户同意了这次运行，才加 `--yes`。用户指定了模型或推理强度时，加 `--model <模型>`、`--effort <强度>`（Codex 不支持 `--effort`，指定了会直接报错）。数据根不在仓库里时（`MDF_DATA_ROOT`），`mdf run` 会自动授权新进程访问数据根。

Stage 5 审查必须这样做（或用真正的子代理），绝不能在编排者自己的上下文里审。各 harness 的入口与限制见 `docs/harnesses.md`。

---

## Stage 0：意图澄清与初始化

**执行者：编排者（你）**

**先看数据根在哪。** 阶段卡或 `mdf status` 末尾出现「⚠️ 数据根在临时 worktree 里」时，先停下来问用户把数据放到哪个 worktree 之外的目录（例如主仓库），然后在之后每条命令前设 `MDF_DATA_ROOT`，再开始。桌面版回收 worktree 时，被 gitignore 的 `sources/`、`output/` 会一起消失，不会有任何提示。2026-10-19 的鲁迅验收第一轮跑到 3A，产物就是这样全丢了。

### 0.R 恢复 / 继续执行分支

当用户表达“继续”“恢复”“接着跑”“resume”等意图时，编排者不接管子 agent 的实质工作，只做状态裁决和重派：

1. 确认目标 `person_slug`。如果当前会话有唯一未完成任务，默认使用该 slug；如果有多个候选，列出候选让用户指定。
2. 先运行 `python scripts/mdf.py status {slug}`，把状态表贴给用户，并按「进度可见性」一节为 `next.chapter` 打章节标签。然后按优先级查找未完成状态：
   - `sources/{slug}/processed/local_shards/task_status.json`
   - `output/{slug}/stage3_status.json`
   - `sources/{slug}/processed/{primary_sources|secondary_sources|expression_dna}_status.json`
3. 对每个状态文件运行：

```bash
python scripts/task_status.py summary <status-path>
python scripts/task_status.py next <status-path>
```

4. 只重派 `next` 输出中的 pending/failed units：
   - Stage 1A：重派对应 `local-source-worker` shard
   - Stage 1B/1C/1D：重派对应 search query / source target
   - Stage 3：重派 `framework_core` / `framework_zh` / `framework_en` / `alignment_review` 中缺失的 unit
5. 同一 unit 失败 2 次后，降低并发或拆小任务；失败 3 次后视为 blocked，进入降级策略，不要无限重试。
6. 子 agent 成功后必须调用 `scripts/task_status.py mark-completed`；失败必须调用 `mark-failed`。
7. 当前阶段所有 required units 完成后，运行对应 checkpoint 校验。

**关键原则：恢复执行在子 agent，恢复裁决在编排者。编排者不得替子 agent 继续提取、搜索或合成内容。**

### 0.1 解析输入

从用户输入中提取人物名，生成 slug（小写、连字符）：

- "查理·芒格" / "Charlie Munger" → `charlie-munger`
- "孙子" / "Sun Tzu" → `sun-tzu`
- "王阳明" / "Wang Yangming" → `wang-yangming`

### 0.2 检测用户素材

检查 `sources/{slug}/raw/` 目录是否存在且包含文件：

```
情况 A：目录存在且有文件
→ 告知用户"检测到你提供的素材，将优先使用"
→ 列出发现的文件

情况 B：目录为空或不存在
→ 告知用户"未检测到本地素材，需要先用 mdf acquire 从白名单来源合规采集原典（网络检索已禁用）"
→ 询问是否要先提供本地素材，还是直接继续
```

### 0.3 推荐门类分类

从 `config/taxonomy.json` 中自动推荐该人物的主类 + 副类，询问用户是否确认：

```
例：检测到人物：查理·芒格（Charlie Munger）
推荐分类：
  主类：经营 (enterprise) — 投资人、商业思想家
  副类：求知 (inquiry)、行事 (conduct)
是否采用此分类？或有调整？
```

**用提问工具问，不要只在正文里问。** Claude Code 用 `AskUserQuestion`（推荐方案放第一个选项），其他 harness 用同类工具；没有提问工具就停下等用户回复。用户的回答就是决定，编排者不得自行改动。

### 0.4 确认后初始化目录并记下类目

```bash
python scripts/mdf.py init {slug}   # 建 sources/{slug}/raw、processed 与 output/{slug}（已存在则跳过）
python scripts/mdf.py classify {slug} --primary governance --secondary philosophy,conduct --name 墨子
```

`mdf classify` 把用户的决定写进 `sources/{slug}/classification.json`（校验 1 主 + 至多 2 副、都在 taxonomy 里）。这是类目传给下游的唯一通道：

- `mdf brief` / `mdf run` 把它写进简报「上下文」；原则提取、框架合成、核心层组装这几步**没有它就拒绝生成简报**——新进程不能向用户提问，不能让它自选。
- 子代理分派同理：把 `mdf classify {slug}` 打印的那行类目原样写进分派说明。
- `validate frameworks` 核对 `output/{slug}/frameworks.zh.json` 的 `primary_category` / `secondary_categories`，`validate package` 核对 SKILL.md 身份卡；与用户确认的不一致就报 `CLASSIFICATION_MISMATCH`。
- 用户事后要改类目：重新问、重新 `mdf classify`，再从受影响的阶段重跑。

---

## Stage 1：素材采集

**执行者：local-source-indexer / local-source-worker / local-source-reducer + source-researcher 子代理（并行执行）**

### 1.0 合规采集原典（可选，先于子代理 A）

用户没有本地素材、或素材缺原典时，用确定性脚本从白名单来源取公有领域/自由许可文本，**不要让 agent 自己爬网页**：

```bash
python scripts/mdf.py acquire {slug} --wikisource zh:論語/學而第一 --dry-run   # 先跑离线闸门
python scripts/mdf.py acquire {slug} --wikisource zh:論語/學而第一 --ia <identifier>
python scripts/mdf.py acquire {slug} --local <路径> --rights user_owned_copy     # 导入用户自有副本
```

- 来源与闸门由 `config/acquisition_policy.json` 决定：主机白名单、User-Agent 联系方式（`MDF_CONTACT`）、robots.txt、TDMRep 挖掘保留、请求间隔与上限、权利状态。任何一道不过即拒绝，原因写入 `sources/{slug}/processed/acquisition_log.jsonl`。
- 结果表里的 ⛔ 拒绝需要人处理（改策略或补授权），不要换个办法绕过；`RIGHTS_UNVERIFIED` 只有用户确认权利后才能加 `--allow-unverified-rights`。
- 采集的文件落在 `sources/{slug}/raw/acquired/`，随后照常走子代理 A 的分片流水线；`sources/{slug}/processed/source_registry.json` 会带上每个文件的来源 URL 与权利状态。
- 用户直接放进 `raw/` 的文件权利状态默认是 `unverified`。**请用户**（不是 agent 替他判断）在 `sources/{slug}/rights.json` 里逐文件声明权利状态和依据，再跑 `mdf index`；`--strict` 发布会拦下权利未放行的证据来源（S4）。格式与判定规则见 `docs/ethics-and-legal.md`。
- 人物在世时，提醒用户：包里必须带「在世人物声明」（L2 闸门会查），并考虑是否适合公开发布。

将以下任务分派给子代理，**并行执行**：

> **阶段 1 的合并与补充（reduce）禁用网络检索**（墨子试跑后的决定）：子代理 B/C/D 只读 `sources/{slug}/raw/` 与 `sources/{slug}/processed/`，不得用 WebSearch、WebFetch、搜索类 MCP 或 curl 之类联网手段；网络转述的 secondary 全是 confidence: low，徒增噪声。缺素材时停下，列出建议采集的目标（著作、篇目、传记），由编排者征得用户同意后用 1.0 节的 `mdf acquire` 合规采集，再回到子代理 A 的流水线。下文 B/C/D 里的「搜索」一律按「在本地语料里检索」理解。`mdf brief` 生成的 reduce 简报会写明禁令；Claude Code 新进程另加 `--disallowedTools WebSearch,WebFetch`。

### 子代理 A：用户素材处理（Stage 1A，本地分片流水线）

当 `sources/{slug}/raw/` 存在文件时，**不得再派单个 agent 读取全部 raw 文件**。本地素材必须走三层流水线：

#### A0：local-source-indexer（1 个）

- 扫描 `sources/{slug}/raw/`
- 调用脚本抽取 PDF/TXT/MD 文本：

```bash
python scripts/mdf.py index {slug}    # 等同 local_source_pipeline.py index，含清洗闸门
python scripts/mdf.py clean {slug}    # 查看清洗报告：被拒 / 待复核 / 重复来源及删除样例
```

- 清洗闸门（`scripts/clean_corpus.py`）**只删不改**：删版权页、网站广告、页码、页眉页脚、索引与目录，保留下来的字符逐字不动，所以 P2 溯源不受影响。乱码、空文本、OCR 缺失过多的来源被拒，不进分片；与另一来源相同或高度重合的只抽一份。
- `mdf clean` 有 ❌ 被拒时先处理（换版本、转 UTF-8、装 OCR 依赖），不要让 worker 去读被拒的原文件；⚠️ 待复核的来源照常分片，worker 会按 passage 的 `quality_flags` 降级处理。
- 输出：
  - `sources/{slug}/processed/cleaning_report.json`
  - `sources/{slug}/processed/local_shards/manifest.json`
  - `sources/{slug}/processed/local_shards/shard_001.json`
  - `sources/{slug}/processed/local_shards/shard_002.json`
  - ...
  - `sources/{slug}/processed/local_shards/task_status.json`
- 检查 shard token 预算：
  - 推荐目标：20k-35k tokens
  - 软上限：50k tokens
  - 硬上限：60k tokens，超过必须重新分片，不得派 worker
- 先读取 manifest 生成的 `sources/{slug}/processed/local_shards/sampling_plan.json`、`sources/{slug}/processed/local_shards/dispatch_plan.json`、`sources/{slug}/processed/local_shards/cost_estimate.json`，再决定派工。
- 主 agent 必须动态分批派发 local workers，不能一次性把全部 shard 交给并行 agents：
  - 每个 worker 只读取一个 shard；
  - `sources/{slug}/processed/local_shards/dispatch_plan.json` 按上下文窗口、token 量、OCR 状态和理解难度给出 batch；
  - 高难度 shard 单独派发，完成/失败后才释放下一槽位；
  - 同一 shard 连续失败时先拆分或降低并发，不让整个 Stage 1A 阻塞。
- `recommended_worker_count` 只是总量提示，不是强制并发数。实际并发由主 agent 根据当前上下文窗口动态裁决。
- 预算：`config/defaults.json` 的 `source_strategy.sampling.max_selected_input_tokens`（默认 500,000，与抽样上限一致）；配了单价时，`max_cost_usd` 也会参与判断。超预算时，`mdf status` 把「分片抽取」标为受阻。这时必须先调用 AskUserQuestion，让用户在全量处理、分层抽样、只用本地素材并降低预算、取消之间选；用户选择前不得派 worker 或补充采集。用户选全量后，运行 `python scripts/mdf.py budget {slug} --approve` 记下批准。批准只覆盖当时的规模，重新分片后规模变大，要再问一次。

#### A1：local-source-worker[N]（按 shard 并行）

- 每个 worker **只读取一个** `sources/{slug}/processed/local_shards/shard_XXX.json`
- 每个 worker 提取 8-15 条高价值候选：
  - `quote`
  - `principle`
  - `behavior_record`
  - `expression_sample`
- 每条候选必须保留 `source_title`、`source_detail`、文件名、页码/章节或 `passage_id`
- 输出至：

```text
sources/{slug}/processed/local_shards/shard_XXX_extracts.json
```

- 成功后标记：

```bash
python scripts/task_status.py mark-completed sources/{slug}/processed/local_shards/task_status.json shard_XXX --output sources/{slug}/processed/local_shards/shard_XXX_extracts.json
```

- 失败或中断前标记：

```bash
python scripts/task_status.py mark-failed sources/{slug}/processed/local_shards/task_status.json shard_XXX --error "错误原因"
```

#### A2：local-source-reducer（1 个）

- 合并所有 `local_shards/*_extracts.json`
- 合并前运行 `python scripts/task_status.py summary sources/{slug}/processed/local_shards/task_status.json`，确认没有 failed/blocked unit
- 按来源、主题、规范化文本哈希与相似度去重
- 最终保留 30-60 条高质量摘录
- 调用：

```bash
python scripts/local_source_pipeline.py reduce {slug} --person-name "{person_name}"
```

- 输出至 `sources/{slug}/processed/user_sources.json`

**可靠性要求：**

- 单个本地 worker 不应超过 40 次 tool use；目标区间是 15-30 次
- worker 输出必须回写 `shard_id` 与 `input_fingerprint`；指纹不匹配的输出不得进入 reducer
- 如果某个 worker 需要读取过多文件或超过 60k tokens，立即回到 A0 重新分片
- PDF 文本抽取由脚本完成，agent 不得反复打开 PDF 全文
- 最终对 Stage 2 暴露的接口仍是 `sources/{slug}/processed/user_sources.json`

### 子代理 B：主要文献整理（本地）

- 在本地语料里检索该人物的原著、演讲、书信、访谈
- 重点：**第一手资料**（本人写的或说的）
- 输出至 `sources/{slug}/processed/primary_sources.json`

### 子代理 C：分析性文献整理（本地）

- 在本地语料里检索该人物的传记、学术分析、权威评论（本地没有就留空并写明缺口，见上方禁令）
- 用于理解背景和验证第一手资料
- 输出至 `sources/{slug}/processed/secondary_sources.json`

### 子代理 D：表达风格采集（⚠️ 必须执行，不可跳过）

- 在本地语料里检索该人物的演讲逐字稿、访谈实录、书信原文
- 重点：**此人怎么说话/写作**，而非说了什么内容
- 提取句式偏好、高频词汇、修辞手法、幽默实例、语气特征
- 此任务的 extracts 使用 `content_type: "expression_sample"`
- 输出至 `sources/{slug}/processed/expression_dna.json`
- 从本地语料（用户提供的 PDF/TXT、`mdf acquire` 采集的原典）中提取表达风格素材（演讲段落、论辩用语、典型句式），不得留空

**注意：** 如果用户提供了充足素材（子代理 A 产出丰富），子代理 B/C 可以精简搜索范围。**子代理 D 始终执行，且必须产出非空的 `sources/{slug}/processed/expression_dna.json`**——表达风格是消除"套公式"感的核心依据，跳过此步骤将导致 SKILL 质量严重下降。

当 Stage 1A 的 `sources/{slug}/processed/user_sources.json` 已经覆盖主要主题且 extracts 数量 ≥ 30 时，子代理 B/C 只做**补缺清单**：列出本地素材缺失的著作、演讲、传记争议或待验证的出处，交编排者决定是否用 `mdf acquire` 采集，不得自行联网。

**素材不足时：** 网络检索已禁用，不再有「搜索工具回退」。子代理 B/C/D 只用本地语料；本地确实没有的（例如传记、学术评论），在 `collection_notes` 里写明缺什么、建议用 `mdf acquire` 采集哪些目标，由编排者问用户是否采集。`sources/{slug}/processed/primary_sources.json` / `sources/{slug}/processed/secondary_sources.json` 缺失只是警告；`sources/{slug}/processed/expression_dna.json` 必须从本地语料产出。

### ✓ 检查点 1：素材完整性校验（双重检查）

**第一步：文件完整性检查（编排者执行）**

在运行格式校验之前，先确认所有必需的素材文件已生成：

```
必需文件检查清单：
□ sources/{slug}/processed/user_sources.json     （如 raw/ 有文件）
□ sources/{slug}/processed/local_shards/manifest.json （如 raw/ 有文件）
□ sources/{slug}/processed/local_shards/task_status.json （如 raw/ 有文件）
□ sources/{slug}/processed/primary_sources.json   （子代理 B 输出）
□ sources/{slug}/processed/secondary_sources.json （子代理 C 输出）
□ sources/{slug}/processed/expression_dna.json    （子代理 D 输出）⚠️ 必须存在
```

如果 `raw/` 有文件但 `sources/{slug}/processed/local_shards/manifest.json` 不存在：

- 不要让 `source-researcher user_provided` 单独处理全部 raw
- 立即执行 local-source-indexer
- 再按 shard 派发 local-source-worker
- 最后执行 local-source-reducer 生成 `sources/{slug}/processed/user_sources.json`

如果 `sources/{slug}/processed/expression_dna.json` 不存在或为空：

- **不要跳过** — 立即补充执行子代理 D
- 指示子代理 D 从 `sources/{slug}/processed/user_sources.json` 与本地语料中提取表达样本（网络检索已禁用）
- 只有确认 `sources/{slug}/processed/expression_dna.json` 非空后才能进入格式校验

**第二步：格式校验**

```bash
python scripts/validate_output.py sources {slug}
```

通过后进入 Stage 2。失败则检查子代理输出的 JSON 格式并修复。

---

## Stage 2：原则提取

**执行者：principle-extractor 子代理（并行 2-4 个，按素材文件分工）**

每个子代理负责处理一个 processed 目录下的素材文件：

- 输入：`sources/{slug}/processed/{source_type}.json`
- 任务：提取思维原则、决策规则、推理模式、名言
- 格式要求：每条原则必须包含 `text`、`source_attribution`、`topic_tags`
- 输出：`output/{slug}/principles_{source_type}.json`

**并行等待所有 principle-extractor 完成后，执行检查点 2。**

### ✓ 检查点 2：原则格式校验

```bash
python scripts/validate_output.py principles {slug}
```

通过后进入 Stage 3。

---

## Stage 3：框架合成（三段式减压）

**执行者：framework-core-synthesizer → framework-synthesizer-zh（英文分支触发时另加 framework-synthesizer-en）→ framework-alignment-reviewer**

Stage 3 不再由一个 agent 同时完成共同去重和语言生成。必须拆成三段：

### Stage 3A：共同核心合成（framework-core-synthesizer，1 个）

- 输入：所有 `output/{slug}/principles_*.json` + `sources/{slug}/processed/expression_dna.json`
- 任务：
  1. 跨文件去重与 canonical principle clusters 合并
  2. 按证据强度、独特性、可操作性排序
  3. 为每个 cluster 选择最强 supporting evidence
  4. 整理 shared blind spot themes（只写共同风险主题，不写完整双语段落）
  5. 整理 reasoning pattern candidates 与 quote candidates
  6. 建立 source ledger 与 confidence factors
  7. 摘要 expression DNA raw samples
- 输出：

```text
output/{slug}/framework_core.json
```

首次进入 Stage 3 时初始化恢复状态：

```bash
python scripts/task_status.py init stage3 {slug}
```

如需先生成机械 scaffold，可运行：

```bash
python scripts/build_framework_core.py {slug}
```

但 scaffold 只是起点，framework-core-synthesizer 必须根据素材精修核心聚类和盲区主题。

### Stage 3B：中文框架生成（framework-synthesizer-zh，1 个）

**默认只跑中文。** 英文合成器不在默认路径上——它由 Stage 6.5 按用户意愿单独触发。

- 输入：`output/{slug}/framework_core.json`
- 输出：`output/{slug}/frameworks.zh.json`
- **顶层必须带 `"format_version": 6`。** 这是校验器把原则数区间从 legacy 的 5-8 放宽到 v6
  的 8-11（目标 9-11）的唯一依据——缺了这个字段，9 条以上的原则会被当 legacy 框架判定为
  `TOO_MANY_PRINCIPLES`
- 原则数：**9-11 条**（目标区间；`config/defaults.json` 的 `min_principles` 硬下限为 8，语料确实撑不起 9 条时可低至 8 条，见 `agents/skill-assembler.md` 的核心层加厚要求）
- 每条原则必须含新增的两个字段：`failure_boundary`（失效边界）与 `prerequisite_intel`（情报前提）
- 成功后标记 `framework_zh` completed

### Stage 3C：中文自检（framework-alignment-reviewer，1 个）

单语路径下，本阶段不做双语对齐，改做中文自检：

- 决策框架每一步是否都是过滤器型（yes/no 闸门），无开放式收尾步骤
- 每条盲区是否都带缓解建议
- 每条原则是否都有 `failure_boundary` 与 `prerequisite_intel`
- 输出：`output/{slug}/framework_alignment_review.md`

结论必须为 `[PASS]` / `[REVISE: ...]` / `[FAIL: ...]`。

如果 `[PASS]`，标记 `alignment_review` completed；如果 `[REVISE]` 或 `[FAIL]`，编排者按报告只重派对应 unit，不整段重跑。

### ✓ 检查点 3：框架格式校验

```bash
python scripts/validate_output.py frameworks {slug}
```

通过后进入 Stage 4。校验项包括：`output/{slug}/framework_core.json` 是否存在且 principle clusters 非空、中文框架文件是否完整（英文分支启用时另检查 `output/{slug}/frameworks.en.json`）、盲区是否有缓解建议、决策框架是否为过滤器形式、**表达风格 DNA 8 维是否完整、价值取向与反模式是否达标**。常见报错处置：

| 报错 | 处置 |
|---|---|
| `TOO_MANY_PRINCIPLES` | `output/{slug}/frameworks.zh.json` 缺少顶层 `"format_version": 6`，被当 legacy 框架卡在 8 条上限——补上该字段，不要删原则 |
| `TOO_FEW_PRINCIPLES` | 语料确实撑不起目标区间，回 framework-core-synthesizer 补聚类或接受降至硬下限 8 条 |
| `MISSING_MITIGATION` | 回 framework-synthesizer-zh 给对应盲区补 `mitigation` 字段 |
| `STAGE3_UNRESOLVED_UNITS` | `output/{slug}/stage3_status.json` 有 failed/blocked unit——按 unit_id 重派，不整段重跑 |

---

## Stage 4：核心层组装

**执行者：skill-assembler 子代理（1 个）**

从 `output/{slug}/frameworks.zh.json` + `templates/skill-template.v6.zh.md` 生成
`output/{slug}/SKILL.md`。

**硬约束：**

- frontmatter 必须含 `format_version: 6`
- 纯中文；**不得含英文语言区块**；**不含**语言检测头
- **≤500 行**（超限时减少原则条数，不压缩每条深度）
- `description` ≤300 字符
- 必须含「案例索引」章与「附件调用」表。此时 `output/{slug}/references/cases.md` 尚未生成（Stage 4.5 才产出）——
  「案例索引」章在本阶段只按 cluster 写占位行（不得虚构 case_id），真正的 case_id 要等 Stage 4.5
  附件齐备后回写

## Stage 4.5：附件生成

三个附件可并行生成：

| 子代理 | 产出 | 模板 |
|---|---|---|
| evidence-carder | `output/{slug}/references/evidence.md` | `templates/refs/evidence.zh.md` |
| case-builder | `output/{slug}/references/cases.md` | `templates/refs/cases.zh.md` |
| skill-assembler（续） | `output/{slug}/references/voice.md` | `templates/refs/voice.zh.md` |

另由 skill-assembler 产出 `output/{slug}/人物档案.md`（模板 `templates/refs/dossier.zh.md`）。

附件齐备后，由 skill-assembler（续）回写核心层的「案例索引」表（与 voice.md 同一次调用）——把 Stage 4
写下的占位行替换成 `output/{slug}/references/cases.md` 中真实的 case_id，索引与 cases.md 必须双向一一对应
（P5 闸门）。派发时把这一步写进它的任务说明，别指望它自己想到。

**行数预算：** 回写后 SKILL.md 仍须 ≤500 行（P6）。占位行是按簇写的，回写成每案一行会多出「案例数 − 簇数」行——
鲁迅验收 33 个案例、10 个簇，从 473 行涨到 495 行，只剩 5 行余量。默认把同一原则的案例合并成一行：触发情境
用「；」分隔，`case_id` 列按同样顺序列出全部 case_id（「、」分隔，P5 认得）；回写后若还有 20 行以上余量，
才拆成每案一行。

### ✓ 检查点 4：包校验

```bash
python scripts/validate_output.py package {slug}
```

六道闸门全过方可进入 Stage 5。常见报错处置：

| 报错 | 处置 |
|---|---|
| `P2_NOT_IN_CORPUS` | 回 evidence-carder 改逐字引文；确属底本讹字则加 `textual_note` |
| `P4_TOO_FEW_CASES` | 回 case-builder 补该 cluster 的案例 |
| `P5_INDEX_ORPHAN` / `P5_CASE_NOT_INDEXED` | 同步核心层索引与 cases.md |
| `P6_TOO_LONG` | 减原则条数，不压深度 |

---

## Stage 5：质量审查

**执行者：quality-reviewer 子代理（1 个）**

**默认 8 个审查维度；`en_requested.flag` 存在时加「双语一致性」共 9 个**（详见
`agents/quality-reviewer.md`）：

1. **准确性** — 引文能否在证据底座中找到对应？归因是否明显错误？（逐字性不由本代理判——那是
   `scripts/verify_provenance.py` 的 P1/P2 闸门；本代理只查 `output/{slug}/references/evidence.md` 里每条 `textual_note` 的裁决是否站得住脚）
2. **独特性** — 原则去掉人名后是否仍能认出是这个人？
3. **可操作性** — 决策框架每一步是否是可执行的过滤判断？
4. **表达辨识度** — 第一人称沉浸、表达 DNA 8 维、结构自然性指令、边界规则是否到位？
5. **价值观完整性** — 追求/反对/内在张力三层是否均有内容，且反模式与盲区互补而非重复？
6. **双语一致性**（仅英文分支启用时评审）— 中英是否共享同一个 `output/{slug}/framework_core.json` 证据底座与盲区核心风险覆盖？
7. **案例层质量** — `output/{slug}/references/cases.md` 的案例是否真的展示了判断过程，反例是否体现「失效边界被触碰」？
8. **附件可用性** — 「附件调用」触发条件是否逐字保留、未被软化？`output/{slug}/references/voice.md` 样本是否≥20 条且正反例齐全？
9. **格式合规** — frontmatter 是否含 `format_version: 6`？八个核心章节是否齐备无占位符残留？

输出：`output/{slug}/review.md`，结论为以下三者之一：

- `[PASS]` — 综合得分 ≥3.5 且准确性、表达辨识度均 ≥3，可以进入安装流程
- `[REVISE: {具体问题}]` — 返回 Stage 4 / Stage 4.5 修订
- `[FAIL: {根本原因}]` — 需要从 Stage 1/2 重新开始

**如果 REVISE，编排者将审查反馈传递给 skill-assembler（核心层问题）或 case-builder / evidence-carder（附件问题），最多重试 2 次。**

---

## Stage 6：用户审阅与安装

**执行者：编排者（你）**

### 6.1 展示成品摘要

向用户展示：

- 人物基本信息（时代、门类）
- 提取到的核心原则清单（仅标题）
- 质量审查结论
- `output/{slug}/SKILL.md` 核心层预览（前 50 行）+ `references/` 下三个附件的文件清单

### 6.2 询问操作选择

```
成品已就绪，请选择操作：
[1] 安装到 ~/.claude/skills/ 并加入 gallery/
[2] 只查看完整内容，不安装
[3] 修改某个部分后再安装
[4] 重新生成（说明哪里不满意）
```

### 6.3 执行安装（如用户选择 [1]）

顺序是**发布 → 校验 → 安装**——校验不过绝不能先把文件 cp 进用户的真实 skills 目录。

**发布前先查换行符（运行时 agent 负责）。** manifest 记的是字节 hash，而仓库的 `.gitattributes`（`eol=lf`）入库时会把 CRLF 改成 LF——墨子试跑里 agent 在 Windows 上写出 CRLF 的 `output/{slug}/references/cases.md`，发布后一入库 hash 就对不上。所以发布前由你（编排者或执行这一步的 agent）检查 `output/{slug}/` 下要发布的文本文件（`output/{slug}/SKILL.md`、`output/{slug}/references/*.md`、`output/{slug}/人物档案.md`）有没有 `
`，有就转成 LF、重跑 `validate package`，再发布。这一步不设脚本闸门，靠执行者自查；每份简报里也写了「一律 LF」。

```bash
# 1. 发布到 gallery 并写 manifest（脚本会自动识别 v6 包并同步 references/）
python scripts/publish_skill.py --slug {slug}
```

**`output/{slug}/人物档案.md` 不进安装目录**——它只留在 `gallery/{slug}/` 供人阅读。
把一份第三人称档案放进 skill 目录会诱发人称漂移，违反第一人称沉浸铁律。

```bash
# 2. 发布后必须先校验
python scripts/validate_output.py gallery {slug}
```

此检查会逐文件比对 output/ 与 gallery/ 的哈希（v6 包含全部 references）。
**校验失败时不得执行下一步的 cp，也不得向用户宣称已安装完成**——先重新同步再重跑校验，
只有通过后才能继续安装。

```bash
# 3. 校验通过后才安装到 Claude Code。白名单：只有 SKILL.md 与 references/ 进安装目录
mkdir -p ~/.claude/skills/{person-slug}-wisdom/references/
cp gallery/{slug}/SKILL.md ~/.claude/skills/{person-slug}-wisdom/SKILL.md
cp gallery/{slug}/references/*.md ~/.claude/skills/{person-slug}-wisdom/references/
```

### 6.4 更新 gallery/index.json

`scripts/publish_skill.py` 已自动写入大部分字段；核对条目包含以下字段：

```json
{
  "slug": "{slug}",
  "name_zh": "{人物中文名}",
  "name_en": "{Person English Name}",
  "lang": "zh",
  "format_version": 6,
  "has_attachments": true,
  "primary_category": "{category_id}",
  "secondary_categories": ["{cat2}", "{cat3}"],
  "distilled_on": "{YYYY-MM-DD}",
  "review_status": "PASS",
  "skill_dir": "gallery/{slug}/"
}
```

### 6.5 询问是否生成英文版

中文包安装完成后询问用户：

> 中文版已完成并安装。是否同时生成英文版？英文版会作为**独立 skill**
> （`{person-slug}-wisdom-en`）发布，是独立的认知重构而非翻译，需要额外一轮合成与审查。

**用户选择「否」→ 蒸馏结束。** 这是默认路径。

**用户选择「是」→ 执行英文分支：**

> ⚠️ **v6 包格式目前只做中文。** 英文分支产出的是**旧格式（legacy）单文件 Skill**，
> 不经过 P1–P6 六道闸门，也没有 `references/{cases,evidence,voice}.md` 三件附件、
> 没有「附件调用」表、没有「案例索引」。`templates/skill-template.en.md` 的 frontmatter
> 因此不带 `format_version: 6`，让 `scripts/validate_output.py` 把它当 legacy 单文件
> 校验，而不是错误地套用只认中文字面量（如「身份卡」「原文出处」）的 v6 闸门。这是
> 有意的范围收窄，不是遗漏——半吊子地给闸门加英文参数化会引入一片没有回归测试覆盖
> 的新代码面。

```bash
# 标记英文分支已启用，校验器据此要求 frameworks.en.json
echo "requested" > output/{slug}/en_requested.flag
```

英文分支复用语言中立的 `output/{slug}/framework_core.json`，依次执行：

1. Stage 3B-en：framework-synthesizer-en → `output/{slug}/frameworks.en.json`
   （**独立重构，不看中文产物**——Rule 4 的独立成篇原则在分支内完整保留）
2. Stage 3C-en：framework-alignment-reviewer → 中英覆盖等价性审查
3. Stage 4-en：skill-assembler → `output/{slug}-en/SKILL.md`（单文件，legacy 格式，
   模板 `templates/skill-template.en.md`；不产出 `references/`）
4. Stage 5-en：quality-reviewer（此时启用「双语一致性」维度）
5. 安装到 `~/.claude/skills/{person-slug}-wisdom-en/`，
   gallery 条目 `lang: "en"`、slug 为 `{slug}-en`

### 6.6 安装确认

```
✅ 已安装：~/.claude/skills/{person-slug}-wisdom/
   └── SKILL.md（纯中文核心层）+ references/（cases.md / evidence.md / voice.md）

💡 测试方式：
   用中文描述与「{人物名}」领域相关的决策场景，Skill 将自动触发。
   若刚完成 6.5 的英文分支，另有 ~/.claude/skills/{person-slug}-wisdom-en/ 可用英文触发。
```

---

## 错误处理

| 情形            | 处理方式                   |
| ------------- | ---------------------- |
| 素材极度匮乏（人物太小众） | 暂停，询问用户是否提供文本资料        |
| 质量审查 FAIL     | 向用户说明原因，询问是否更换人物或降低要求  |
| 名言归因存疑        | 在 Skill 中标注"出处待核实"，不删除 |
| 英文分支质量不及中文版   | 优先保证中文版质量，英文版降级处理并标注   |
