# 试跑报告：墨子（`mozi`）——「无子代理 harness」路径端到端

**日期**：2026-10-18　**基线**：`be4db33`（`claude/pipeline-automation`）　**执行者**：一个 Sonnet 会话当编排者；每个 agent 步骤用 `mdf brief` 生成简报，交给 `claude -p --model sonnet` 新进程执行（不用 Agent/Task 子代理）。

## 结论

- **跑通到阶段 6（只发布到 gallery）**：`mdf validate sources / principles / frameworks / package / published` 全部通过，`package` 与 `published` 另外通过 `--strict`；审查 `[PASS]` 4.04/5；`gallery/mozi` 已发布（manifest v2）。未往 `~/.claude/skills`、`~/.agents/skills` 装任何东西，英文版未做。
- **简报路径可行，但不是开箱即用**：9 次新进程调用里，5 次顺利；4 次暴露了简报缺口（extract、assemble、attachments、review，见「发现」1–3、5），其中 attachments 需要编排者补一句话才继续，其余 3 次执行者如实报告检查点失败或自编命令。这些缺口已在本分支修复并补测试。
- **成本**：9 次 `claude -p` 调用合计 **$6.04**（list price），累计 1495 秒（约 25 分钟），输出 14.6 万 token，缓存读 885 万 / 缓存写 75 万 token，非缓存输入仅 202 token。语料只有 13 篇、5.6 万字节，成本几乎全花在「每轮重读简报与 SKILL 上下文」的缓存读上。
- **产物质量有保留**：全部证据来自维基文库单一来源，confidence 封顶 medium；`distill_confidence` 3 分（刚到下限）；`mdf metrics` 提示核心层文体更接近通用分析腔、4 条原则的去名锚点不成立。另有 3 篇的篇名在已发布包里标错（见「发现」6），已标「篇次待核」。

## 配置

| 项 | 值 |
|---|---|
| 人物 / slug | 墨子 / `mozi`（我按 taxonomy 选的是 governance 主 + philosophy、conduct 辅；**这个选择没有任何通道传给 agent**，见发现 8，最终包里是 philosophy 主 + governance、pedagogy 辅） |
| 采集 | zh.wikisource《墨子》13 篇：尚賢上/中、尚同上、兼愛上/中、非攻上/中、節用上、天志上、非命上、貴義、耕柱、公輸；权利 `cc-by-sa`，全部直接放行，没有出现 `review_rights`，没有用 `--allow-unverified-rights` |
| 联系方式 | 每条命令前 `MDF_CONTACT=https://github.com/20240610ldx-hub/Mind-Distill-Factory`；未写入仓库 |
| 执行者命令 | `claude -p --model sonnet --permission-mode acceptEdits --allowedTools Bash Read Write Edit Glob Grep --output-format json "读取 output/mozi/briefs/<step>.md 并严格按其执行，完成后报告检查点结果。"` |
| 模型回退 | 没有触发（sonnet 没撞额度/上下文闸门，未退到 haiku） |

## 逐步记录

脚本步骤（编排者直接跑）：

| 步骤 | 命令 | 耗时 | 结果 |
|---|---|---|---|
| 初始化 | `mdf init mozi` | <1s | ✅ |
| 离线闸门 | `mdf acquire … --dry-run`（13 目标） | <1s | ✅ 13 待采集（注意：dry-run 不联网，**不验证页面是否存在**） |
| 采集 | `mdf acquire`（13 目标，限速 1s/请求） | 47s | ✅ 13 保存，56KB |
| 登记分片 | `mdf index mozi` | 0.7s | ✅ 1 个分片、1.7 万 token |
| 清洗 | `mdf clean mozi` | <1s | ✅ 13 通过 / 0 待复核 / 0 拒绝 |
| 合并 | `mdf reduce mozi --person-name 墨子` | <1s | ✅ 15 条（警告：目标 30–60） |
| 发布 | `mdf publish --slug mozi`（先 `--dry-run`） | 数秒 | ✅ |

agent 步骤（每步一个新进程；表中「简报是否自足」指新进程能否只凭简报完成，不反问、不找不到文件）：

| # | 简报 | 耗时 | 轮数 | 费用 | 简报是否自足 | 检查点 | 备注 |
|---|---|---|---|---|---|---|---|
| 1 | `extract` | 90s | 9 | $0.53 | ✅（路径、shard、输出格式都对） | ❌→✅ | 简报写的检查点是 `validate sources`，此时必然失败（缺 expression_dna、且 `cleaning_report.json` 被当来源文件）。执行者如实报告「未通过」并停手——行为正确，**简报错了**。已修（发现 1、4） |
| 2 | `reduce` | 169s | 15 | $0.69 | ✅ | ✅（0 错，4 警告：high 占比 0%） | 产出 primary 20 / secondary 6 / expression_dna 10。执行者用了 WebSearch（简报没禁止），secondary 全是转述 low |
| 3 | `principles` | 122s | 14 | $0.47 | ✅ | ✅ | 10 原则 / 4 推理模式 / 10 名言。执行者把三份素材合并成一个 `principles_user_provided.json`，偏离角色定义「每类一个文件」，检查点仍通过 |
| 4 | `frameworks`（3 角色串联） | 257s | 20 | $0.92 | ✅ | ✅ 0 警告 | 10 原则 / 7 步决策框架 / 5 盲区；自检 `[PASS]` |
| 5 | `assemble` | 193s | 16 | $0.76 | ✅ | ❌（预期）| 简报的检查点是 `validate package`，但附件还没生成，必然报 7 错。执行者判断准确并写明原因。已修（发现 3） |
| 6 | `attachments` | 371s | 22 | $1.20 | ❌ | ❌ | **简报缺 `skill-assembler` 续写角色**：`voice.md` 没人写、案例索引没人回写，24 条报错（P5×22 + P3×2）。执行者如实指出「简报里两个角色都不写它」。已修（发现 2） |
| 7 | `attachments`（补跑，限定只做 assembler 续写） | 118s | 14 | $0.53 | ✅（修复后简报 + 编排者补一句「cases/evidence 已写好，别重写」） | ✅ | voice.md 24 条；案例索引回填 22 个 case_id |
| 8 | `review`（独立新进程） | 134s | 1 | $0.69 | ⚠️ | ✅（自编） | 见发现 5：简报无检查点，执行者自己编了 `validate_output.py review`（不存在，报 Unknown stage），随后自行改跑 `skill`/`package`。该进程**又派了一个 general-purpose 子代理**做实际审查（`subagent_stats.spawned=1`），所以「1 轮」是外壳轮数。结论 `[PASS]` 4.04/5，列出 2 处 voice.md 出处错误等 5 条问题 |
| 9 | 修订补丁（无简报，直接 prompt） | 41s | 15 | $0.26 | — | ✅ strict | 修 voice.md 两处出处、溯源里的「待审查」、原则 10 篇名统一。**没有对应的 `mdf brief` 修订回路**（见建议） |

合计 9 次新进程调用，$6.04，1495s。

## 发现与处置

已在本分支修复并补测试（`tests/test_harness_trial_fixes.py`，479 个测试全绿）：

1. **简报检查点指向「整个阶段」而不是「这一步」。** `scripts/harness.py` 的 `build_brief` 只读 `phase.checkpoint`；阶段 1 的 `validate sources` 要 reduce 之后才可能通过，`extract` 的简报却要求执行者先过它。修：步骤可带自己的 `checkpoint`（`config/pipeline_stages.json`），`extract` 改用 `task_status.py summary …/task_status.json`。
2. **`attachments` 步骤漏了 `skill-assembler`（续）。** `commands/distill.md` 4.5 节明说 `voice.md` 和案例索引回写由 skill-assembler 续做，但阶段树里 `attachments` 只列了 case-builder / evidence-carder，简报因此没有这个角色。修：阶段树改为 `case-builder / evidence-carder → skill-assembler（续：voice.md 与案例索引回写）`，`mdf status` 的提示同步。
3. **`assemble` 的检查点必然失败却没说明。** 加 `checkpoint_note`：此时只应报 `MISSING references/*` 与指向它们的 `P3_DANGLING_PATH`，其余必须为零。
4. **`mdf validate sources` 把 `cleaning_report.json` 当来源文件校验**（报 5 个缺字段 + `source_type='None'`）。`mdf index` 一写出这个文件，所有走本地分片流水线的人物都会在检查点 1 被卡住。修：加入 `validate_output.py` 的元数据白名单。
5. **`review` 步骤没有检查点，执行者自己编命令。** 修：步骤级检查点 `validate package {slug} --strict`（`--strict` 会核对 review.md 是 PASS），并说明「没有 `validate review` 这个阶段」。
6. **维基文库页眉没剥干净，导致篇名标错。** 页眉模板渲染成 `<div id="headerContainer">`，不带 `ws-header` class，所以「← / 目錄 / 墨子 / 節用上 / 作者：墨翟 / 節用中（下一篇）」混进了 3/13 篇（天志上、節用上、非命上）正文开头，worker 把末行「下一篇题」当成本篇标题，后续 `source_title` 一路错成「天志中 / 節用中 / 非命中」。修：`acquire.py` 加 `DROP_IDS`。**本次已发布的 `gallery/mozi` 没有重做**（要重采、重抽取、重跑全部后续阶段），包里相关出处标了「篇次待核」；引文本身不受影响（P2 证明逐字命中语料），只是出处篇名有 3 处不准。
7. **`claude -p --permission-mode acceptEdits` 里 Bash 被拦。** 实测：`mdf brief` 打印的 claude-code 命令（原先只有 acceptEdits）会让新进程连检查点命令都跑不了（"requires approval… can't prompt"）。修：`config/harnesses.json` 的 `isolated_run` 加 `--allowedTools Bash Read Write Edit Glob Grep`（等于授权该进程在仓库里执行任意 shell，使用者自行判断）。

未修、需要决策（建议见下节）：

8. **类目没有传递通道。** Stage 0.3 让用户确认分类，但结果不落盘，`mdf brief` 也不带；agent 各自从 `taxonomy.json` 自己选，所以我选的 governance 主类没生效（包里是 philosophy 主）。
9. **`mdf next` / `mdf status` 在发布后仍把「P1–P6 包校验」显示为待办**（不加 `--check` 就不检查），`next` 因此一直指向 `validate package`。
10. **`validate sources` 的 `raw_files` 用非递归 `glob("*")`**，采集落在 `raw/acquired/…/` 的语料不会触发「必须有 manifest / task_status」检查。
11. **阶段 1 的 `reduce` 简报没有禁用网络检索**：执行者用 WebSearch 补 secondary，得到的全是 low 的转述。`distill.md` 说网络来源 confidence 封顶 medium，但对「简报型」执行者没有约束到「只许 acquire」。
12. **新进程会自己再派子代理**（review 步骤）。对「独立上下文」要求是满足的，但费用与可复现性变了；简报没有说明是否允许。
13. **agent 在 Windows 上写出 CRLF 的 `cases.md`。** 发布的 manifest 记的是 CRLF 的 hash，入库时 `.gitattributes`（eol=lf）改成 LF，别处检出就会 hash 不符。本次手工转 LF 后重发布。建议 `publish_skill` 组包时统一规范行尾，或 P1–P6 里加一条「行尾必须是 LF」的闸门。
14. **费用大头是缓存读**：每个进程反复读取 50–200 万 token 的上下文。分片小（1 个分片）时，extract/reduce/principles 三步其实可以合并成一个进程。

## 用户决策与处置（2026-10-18，试跑之后）

| 发现 | 用户决策 | 处置 |
|---|---|---|
| 8 类目没有传递通道 | 沿用「编排者用 AskUserQuestion 问用户、回传决策」 | 新增 `mdf classify <slug> --primary … --secondary …`，写 `sources/<slug>/classification.json`（校验 1 主 + ≤2 副）；阶段 0 多一个「类目确认」步骤；原则提取 / 框架合成 / 核心层组装的简报带上类目，缺记录就拒绝生成；`validate frameworks` 与 `validate package`（身份卡）不一致报 `CLASSIFICATION_MISMATCH`。早于此通道的旧人物不检查 |
| 11 reduce 没禁网 | reduce 禁用网络检索 | 步骤改名「合并与本地补充」，`network: forbidden`：简报写明禁令，Claude Code 新进程加 `--disallowedTools WebSearch,WebFetch`；`distill.md` 子代理 B/C/D 与 `source-researcher.md` 改为只读本地语料，缺素材由编排者问用户是否 `mdf acquire` |
| 12 新进程再派子代理（2026-10-20 决定） | 简报写明不得再派（Stage 5 隔离靠新进程本身），运行记录里子代理数 >0 时告警 | 每份简报的规则段写禁令；`mdf run` 在结果行下告警、运行记录写 `warnings`、面板用量列标 `⚠️ 子代理 N`，不判失败；`distill.md`、编排 skill、`AGENTS.md`、`docs/harnesses.md` 同步 |
| 13 CRLF 致 hash 不符 | 交由运行时 agent 解决 | 不加脚本闸门。每份简报写「一律 LF，写完自查」；`distill.md` 6.3 与编排 skill 要求发布前由执行者检查并转 LF。**2026-10-20 改判**：鲁迅 GUI 实跑里 Claude Code 子代理看不到简报那句，上游 cases.md 带 465 处 CRLF 进了检查点 4，`a46bac5` 加包闸门硬错误 `PKG_CRLF` |
| V1–V4 进度可见性 | 按建议办 | 上游已加 `mdf run`、阶段卡与 `status --html`（3801fb3）。本次补：`mdf run` 跑步骤级检查点（extract 的 `task_status.py summary --strict`——原先 summary 永远返回 0，当闸门无效）；Claude Code 新进程带 `--output-format json`，运行记录写入费用 / 轮数 / token / 子代理数，结果行与面板显示，面板有合计费用；阶段卡的「闸门」改用步骤级检查点 |

测试：`tests/test_trial_decisions.py`（23 个）。

## 对三份文件的修改建议

### `scripts/harness.py`

- ✅ 已做：步骤级 `checkpoint` / `checkpoint_note`；`isolated_run` 带 `--allowedTools`。
- 简报「上下文」节增加 **人物显示名与已确认类目**（来自 `sources/{slug}/meta.json`，由 `mdf init --name 墨子 --primary governance --secondary philosophy,conduct` 写入）；`validate_output` / `publish_skill` 优先读它，不再让 agent 自选。
- 简报增加「**允许 / 禁止**」节：是否允许网络检索（reduce 步骤默认只许读 `raw/` 与 `processed/`）、是否允许再派子代理（review 默认允许但要在报告里注明）。
- 增加 `mdf brief <slug> revise`：把 `review.md` 的 REVISE/一般性问题连同对应角色定义打包（本次只能手写 prompt）。
- 每个简报末尾加固定的「**报告格式**」：检查点命令、退出码、错误原文、本次写入的文件清单、偏离角色定义之处——本次执行者都自觉做了，但格式各异。
- `mdf brief` 打印的命令可附 `--output-format json`，方便统计 token/费用（本次 `claude -p` 的 usage 就是这么拿到的）。

### `commands/distill.md`

- Stage 0.3 / 0.4：落实类目通道（`mdf init` 写 meta）；0.4 的命令示例随之更新。
- 4.5 节已写明 skill-assembler 续写，阶段树现与之一致；建议在「没有子代理的 harness」一节明确：4.5 要**一个进程里按顺序**跑 case-builder → evidence-carder → skill-assembler（续），不要拆三个进程各自过检查点。
- Stage 5：补一句「检查点是 `mdf validate package {slug} --strict`，没有 `validate review`」。
- Stage 1：分片很少（≤2）时允许把 extract + reduce + principles 合并到一个进程，省缓存读费用。
- 「`sources/{slug}/raw/` 里 `acquired/` 的文件名是哈希」：说明篇名要看 `source_registry.json` 的 `canonical_url`，别靠文件名猜。

### `.agents/skills/mdf-distill/SKILL.md`

- 「agent 步骤」一节补：检查点以简报「完成标准」为准；中间步骤的检查点和阶段检查点不同。
- 补「编排者的补充说明」写法：简报缺口被发现时（如 4.5 只跑了前两个角色），可在 prompt 里追加一句限定范围，不要重写简报。
- 补「Codex/pi 的写入沙箱」之外，说明 Claude Code 无头模式需要 `--allowedTools`。

### 未验证（无法通过 `claude -p` 验证）

- **Codex**（`codex exec --sandbox workspace-write`）与 **pi**（`pi -p`，本机只有 9B 本地模型）：本次**没有运行**。简报是纯 Markdown，文件结构上不依赖 Claude 特有能力；但 (a) pi 的小模型能否在 13+ 步里不偏离角色定义、(b) Codex 沙箱里 `python scripts/…` 与写 `output/` 是否放行、(c) 两者对 `argument-hint` 等非标准 frontmatter 的态度，都**未验证**。
- `.agents/skills/mdf-distill` 的 `$mdf-distill` / `/skill:mdf-distill` 触发方式：未验证。
- 同一简报在不同模型下的稳定性：本次全程 sonnet-5.5，没有对比 haiku。

## 可视化与可控性（用户反馈，试跑中后补）

编排者（本会话）在试跑中**没有**按 `commands/distill.md`「进度可见性」一节做事，用户因此看到的是一串底层无头脚本。这是编排侧的执行缺口，也说明协议只靠「自觉」不可靠：

| # | 现象 | 影响 | 本次的处置 / 建议 |
|---|---|---|---|
| V1 | 进入各阶段前**没有打章节标签**（`mark_chapter` 或 H2 兜底都没用），左侧没有定位轨 | 用户无法按阶段跳转、不知道走到哪 | 上游会话在 `mdf` 里新增 `mdf run` 执行器，由它负责在阶段边界输出章节标签；协议里应写成「脚本做，不靠编排者记」 |
| V2 | **叙述没有节奏**：没有阶段开头卡（做什么、产物、闸门）和结尾行（闸门是否通过、产物数、下一步），只有工具调用与零散结论 | 看起来像一堆无头脚本在跑 | 上游新增阶段卡协议；建议由 `mdf brief` 把「开头卡 / 结尾行」模板写进简报「完成标准」，由 `mdf run` 自动填入检查点结果与产物数 |
| V3 | 等待后台进程时**写了 `until [ -f … ]; do sleep 5` 轮询循环**，且过程话是英文（如 "Waiting for the headless extract run to finish."） | 阻塞前台、输出无信息量；与「完成时自动通知」的机制重复 | 直接用 Bash 的 `run_in_background` 跑 `claude -p …`，每个后台命令写清楚的中文 description（如「阶段 5：新进程执行隔离审查」），完成时会自动通知；`mdf run` 应内置这一点，不再让编排者手写 shell |
| V4 | 无头执行者的原始 JSON 输出（含 usage）散落在临时目录，没有汇总视图 | 费用、轮数、是否派了子代理只能事后用脚本拼 | `mdf run` 应把每次调用的耗时 / 轮数 / 费用 / 子代理数写进 `output/{slug}/run_log.jsonl`，`mdf status` 读它 |

> 补救：收到反馈后，从「试跑收尾」起已补打章节、改用中文叙述；前面 9 次新进程调用的阶段卡无法追补，报告里的逐步表是事后重建。

## 复现

```bash
export MDF_CONTACT=https://github.com/20240610ldx-hub/Mind-Distill-Factory
python scripts/mdf.py init mozi
python scripts/mdf.py acquire mozi --wikisource zh:墨子/兼愛上 …（共 13 篇）--dry-run   # 再去掉 --dry-run
python scripts/mdf.py index mozi && python scripts/mdf.py clean mozi
python scripts/mdf.py brief mozi <extract|reduce|principles|frameworks|assemble|attachments|review>
claude -p --model sonnet --permission-mode acceptEdits --allowedTools Bash Read Write Edit Glob Grep "读取 output/mozi/briefs/<step>.md 并严格按其执行，完成后报告检查点结果。"
python scripts/mdf.py validate <sources|principles|frameworks|package> mozi
python scripts/mdf.py publish --slug mozi && python scripts/mdf.py validate published mozi --strict
```

`sources/mozi`、`output/mozi` 在 `.gitignore` 里（与已有人物一致），不入库；`gallery/mozi` 与 `gallery/index.json` 入库（与已有人物一致）。
