# 交接文书：Mind Distill Factory 工程化改造

本文件为交接给后续线程的实施凭据。已完成部分可运行、可测试；未完成部分按优先级列出，避免重复探索。

- 阶段 1（来源与抽样链）：`4dda010`
- 阶段 2 / P0（发布与校验事务化，M1–M4）：`296b05e` → `861feb8` → `7b5e436` → `655a82f`
- 阶段 3（流水线自动化）：`effcb3f` → … → `21334b5` 经 PR #2、#4 合入 main；`0ce2f3d`（OCR 收尾）、`3801fb3`（`mdf run`）、墨子试跑、文档分支合并与《熱風》整本 OCR 修正（`66c0537`）经 PR #5、#7 合入；OCR 后续 `df08946` → `e01044e` → `b829b9f` 经 PR #6 合入；刻本双行小注 `3856504` 经 PR #8 合入
- 鲁迅 GUI 验收与修复（2026-10-19/20）：PR #9（`b080dd4` 等，墨子试跑决策 + 值对象）、PR #10（`0963022`、`89f593d`）、PR #11（`9e9ef17` → `58cc872`）均已合入 main（`3ed4e0c`），明细见「〇-2」

测试基线：`python -m unittest discover -s tests -p 'test_*.py'`
结果：`Ran 766 tests ... OK (skipped=11)`（skipped 来自 `skipUnless`：可选的 PDF/OCR 依赖或私有 raw corpus 不在时跳过，属预期）

---

## 〇、阶段 3 已完成（流水线自动化）

目标：接近全自动的「采集 → 清洗 → 识别 → 抽取 → 校验 → 发布」，阶段可见、人可掌控、跨 harness。入口统一为 `python scripts/mdf.py`。

| 提交 | 内容 | 关键文件 |
|---|---|---|
| `effcb3f` | 阶段逻辑树（7 个 phase，每个 phase 一次章节标签，无章节工具时用 H2 兜底）；`mdf status/next/stages/init/doctor/validate` | `config/pipeline_stages.json`、`scripts/pipeline_status.py`、`scripts/mdf.py` |
| `e8c7d28` | 合规采集 `mdf acquire`（后续提交补了 W3C TDMRep 保留闸门）：白名单 + https、带联系方式的 UA、RFC 9309 robots、限速与 Retry-After、权利三态、去重、原子写、采集日志；连接器 Wikisource / Internet Archive / Gutenberg 镜像 / URL / 本地 | `scripts/acquire.py`、`config/acquisition_policy.json` |
| `050a2b4` | 减法清洗闸门（只删不改，页码标记受保护，近重复检测）；index / 清洗 / P2 共用一个解码器 | `scripts/clean_corpus.py`、`scripts/text_decoding.py` |
| `e91c7c6` | 确定性人格/表达代理指标：主张账本、来源集中度、去名锚点、文体指纹、对话漂移；方法论文档 | `scripts/persona_metrics.py`、`docs/methodology.md` |
| `0069e53` | 伦理与法律闸门：L1 引文长度、L2 在世人物声明、strict S4 证据来源权利（P2 证明里带权利汇总）；人工权利声明 `sources/{slug}/rights.json` | `scripts/validate_output.py`、`docs/ethics-and-legal.md` |
| `8b12577` | harness 适配：Claude Code 插件、Codex/pi 共用的 Agent Skill、`mdf harness`（检测/核对/安装命令只打印）、`mdf brief`（自足任务简报，无子代理的 harness 用新进程执行）；架构文档（阶段图由配置生成，测试防漂移） | `.claude-plugin/plugin.json`、`.agents/skills/mdf-distill/`、`config/harnesses.json`、`scripts/harness.py`、`docs/architecture.md`、`docs/harnesses.md` |
| `be4db33` | 负例夹具 10 个 + 阳性对照；回归协议勘误；`distill.md` 规则 4 与 v6 对齐；本文件 | `evaluation/fixtures/negative/`、`evaluation/scripts/check_negative_fixtures.py` |
| `9f8f0a9` | 采集遵守 W3C TDMRep（站点 JSON → 响应头 → HTML meta，保留即拒） | `scripts/acquire.py`、`config/acquisition_policy.json` |
| `4d0e927` | OCR 校准台 `mdf ocr calibrate` / `scan`；OCR 引擎每进程只建一次 | `scripts/ocr_calibrate.py`、`evaluation/fixtures/ocr/` |
| `21334b5` | 真实 OCR 校准：rapidocr 3.x（PP-OCRv6）适配、PaddleOCR-json（Umi-OCR 插件）管道引擎、`MDF_OCR_BACKEND` 钉选；按实测把低置信阈值 0.6→0.9，新增 `ocr_garbled` 退回与 `ocr_text` 标记（OCR 页码标 `(OCR)`，引文默认 ≤medium） | `scripts/pdf_quality.py`、`scripts/clean_corpus.py`、`agents/local-source-worker.md`、`docs/methodology.md` |
| `0ce2f3d` | 真实扫描件抽查后的 OCR 行级后处理：竖排页按列右→左重排、横排页眉页脚归位到页首页尾；识别分 <0.5 被丢的行与只认出一部分的行计为「可疑行」，新增 `ocr_lines_dropped` 标记与 `--- Page n (OCR, k unread) ---` 页码标记；`mdf ocr scan --pages/--out` 抽页并导出页图与识别文字供人对照 | `scripts/pdf_quality.py`、`scripts/ocr_calibrate.py`、`scripts/clean_corpus.py`、`agents/local-source-worker.md`、`docs/methodology.md` |
| `df08946` | 校准样张扩到 8 页 52 句（加《大學》《孫子》、白话小说、带数字的现代段落、英文），`--fonts` 四种字体族 × `--layout` 横排/竖排，64 次运行重定阈值依据；竖排页从列距推算检测器漏掉的列，计入可疑行；`mdf ocr survey` 整书抽样体检（每个 PDF 均匀抽页，估 OCR 用时、竖排页、可疑行与闸门标记）；P2 归一化补齐全角/竖排标点与全角字母数字（校准里竖排页丢的 23 句有 19 句只是句末全角「？」「！」被认成半角） | `scripts/ocr_calibrate.py`、`scripts/pdf_quality.py`、`scripts/verify_provenance.py`、`evaluation/fixtures/ocr/sample_zh.txt`、`docs/methodology.md` |
| `b829b9f` | 明刻本抽查的两处修正：`mdf ocr scan --pages`/`survey` 改在原文件上逐页读（分层压缩扫描件拷进临时 PDF 后渲染不同，置信度与识别文字都变，导出的图也对不上）；被音注撑宽的被丢框按本页字号折算字数，限宽 ≤1.5 字宽且读出 ≥3 个汉字，排除馆藏印章与插图标注 | `scripts/local_source_pipeline.py`、`scripts/ocr_calibrate.py`、`scripts/pdf_quality.py`、`docs/methodology.md` |
| `3801fb3` | 墨子试跑的可视化反馈（没有章节标签、叙述没节奏、全是无头脚本）：`mdf run` 把「简报→新进程→心跳→状态变化→阶段检查点→运行记录」收成一条命令（不加 `--yes` 只打印计划）；阶段卡 `mdf next --card`、进度条、自包含可视化面板 `mdf status --html`；编排协议写明三拍叙述与章节工具确切名 `mcp__ccd_session__mark_chapter`，驱动无头进程的会话也算编排者 | `scripts/stage_runner.py`、`scripts/pipeline_status.py`、`commands/distill.md`、`.agents/skills/mdf-distill/SKILL.md`、`config/harnesses.json`、`docs/harnesses.md` |
| `66c0537` | 整本扫描书端到端（《熱風》134 页竖排，`mdf index` → `mdf clean`）暴露的两处页眉页脚漏删：字距拉开的页眉拆成单字框插进正文列（竖排页里落在正文列起止线之外的单字框归页首页尾，起止线取四分位）；页码短横认成「一」或丢一边（页边纯数字加横线的行一律按页码计数）。页眉页脚删除 41→171 行，无正文误删；rapidocr 日志降到 error。另 8 本竖排书各抽 8 页审计：被归到页边的 44 个单字框全是页眉页码，没有正文 | `scripts/pdf_quality.py`、`scripts/clean_corpus.py`、`docs/methodology.md` |
| `3856504` | 刻本双行小注：校准台按〔…〕画双行小注（先右后左，跨列续排），新样张 `sample_notes_zh.txt` 量出 rapidocr 逐字存活只有 25%（整列被并成一个框读成乱码，重排救不回）；识别分 <0.7 的长行计为可疑行（`doubtful_lines`），64 次校准里逐字存活 <60% 的运行被标出 28→32 次，体检新增标出的 4 份文件逐条核过都是真认错 | `scripts/ocr_calibrate.py`、`scripts/pdf_quality.py`、`scripts/clean_corpus.py`、`agents/local-source-worker.md`、`evaluation/fixtures/ocr/sample_notes_zh.txt`、`docs/methodology.md` |

文档入口：[架构](docs/architecture.md) · [方法论](docs/methodology.md) · [伦理与法律](docs/ethics-and-legal.md) · [harness 适配](docs/harnesses.md)。

CI：`.github/workflows/tests.yml`（PR #3 合入）在 ubuntu + windows × Python 3.12 / 3.13 上跑 `py_compile` 与全套单测，触发于所有 PR 及 push 到 main；不装 extras、无网络/OCR/API key 依赖。

## 〇-2、鲁迅 GUI 验收与修复（PR #9–#11，2026-10-19/20）

鲁迅（`lu-xun`）在桌面版 GUI 里由编排者按 `commands/distill.md` 跑完阶段 0–5（审查 PASS 4.07，`distill_confidence`=2），阶段 6 按用户要求只做 dry-run。验收笔记在只读的 `.claude/worktrees/lu-xun-acceptance/output/lu-xun/acceptance_notes.md`（临时 worktree，会被回收）。修复原则：**每个修复都要接进管线的全部入口**（编排协议、角色定义、阶段树 `checkpoint_note`、状态表/阶段卡、模板），不做单项目最优。

| 提交 | PR | 内容 |
|---|---|---|
| `b080dd4` | #9 | 墨子试跑决策：`mdf classify` 类目通道（`CLASSIFICATION_MISMATCH`）、reduce 禁网（`--disallowedTools WebSearch,WebFetch`）、运行记录写费用/轮数/子代理数 |
| `cb10d3e` | #9 | Sonnet 5.5 high 实跑 extract 暴露的：`mdf run --effort`、数据根授权、stream-json 心跳显示最近一次工具调用 |
| `fe89e48` | #9 | 值对象 `Workspace`（数据根解析只此一处，架构测试禁止别处读 `MDF_DATA_ROOT`）与 `HarnessProfile` |
| `05a5a9b` | #9 | GUI 里项目 agent 不在 Agent 工具类型中时：`mdf brief` 生成简报交给 general-purpose 子代理 |
| `617ad75` | #9 | 清洗报告的标记改短标签 + 注释表 |
| `e52c870` | #9 | 发现 7：阶段 3A scaffold 从文件级读推理模式/名言，候选 id 带来源类型，仅 secondary 支撑的簇标 `secondary_only`，核心层盲区主题 <2 报 `TOO_FEW_BLIND_SPOTS` |
| `349d73b` | #9 | 进度走原生任务清单，不生成/发送 HTML 看板（`mdf status --html` 只留作手动命令） |
| `0963022` | #10 | 发现 0：数据根在 `.claude/worktrees/<name>/` 下时（会被回收）阶段卡、`mdf status`、`mdf run` 计划都警告，协议在阶段 0 停下先挪数据根 |
| `89f593d` | #10 | 发现 5：按 token 的预算闸门，超预算时抽取步骤「受阻」，用户同意后 `mdf budget <slug> --approve` |
| `9e9ef17` | #11 | 发现 10：`distill_confidence` <3 拒发布（`BLOCKED_LOW_CONFIDENCE`），`--force` 记 `FORCED_LOW_CONFIDENCE` |
| `2973239` | #11 | 发现 15：`validate package` 通过后写 `output/<slug>/.gates/package.json`（包文件指纹），状态表不加 `--check` 也能推进 |
| `f321bbf` | #11 | 发现 6、8：high 占比警告与 reduce 抽取不足分 `[不可改善]`/`[可改善]`；`validate principles` 加下限（`[原则候选不足]`，评论者观点不计） |
| `ba1e941` | #11 | 发现 11：`P2_COVERAGE` 覆盖率行；语料外的卡标 high 报 `P2_UNVERIFIED_HIGH` |
| `3b4baf9` | #11 | 发现 12、13：P5 的 `case_id` 列一格可放多个 id；Stage 4.5 写明回写归属与行数预算 |
| `bcc78ba` | #11 | 把以上接进编排协议检查点 1/2/4、evidence-carder/quality-reviewer、阶段树 `checkpoint_note`、状态表 |
| `4ad1372` | #11 | 值对象 `EvidenceCoverage`；`attest_p2` 只扫一遍语料 |
| `55a8acb` | #11 | 恢复执行时附件步骤只派缺的角色，已有的写明「不要重做」 |
| `c5ebf35` | #11 | 反例在案例索引里单独一行 |
| `c666045` | #11 | `docs/architecture.md` 第 9 节通用语言补四个概念，测试逐个解析表里的 `模块.名字` |
| `a46bac5` | #11 | `PKG_CRLF`：包内 .md 有 CRLF 即硬错误（墨子第 13 条改判，见下） |
| `af5883d` | #11 | `mdf publish` 认 `MDF_DATA_ROOT`（经 `Workspace`） |
| `06ca3a1` | #11 | 未发布且置信度不够时状态表发布行「受阻」并给 AskUserQuestion；模板删「质量审查：{review_status}」 |
| `58cc872` | #11 | CI（ubuntu）修复：`validate_principles` 变量遮蔽 + glob 顺序依赖 |

### 本轮新增的闸门

| 代码 | 级别 | 触发 | 处置（`commands/distill.md` 有对应行） |
|---|---|---|---|
| `PKG_CRLF` | 硬错误 | SKILL.md、人物档案.md、`references/*.md` 含 CRLF | 转 LF 后重跑包校验。manifest 按字节记 hash，入库时 `eol=lf` 会改写，发布后校验必然失败 |
| `P2_UNVERIFIED_HIGH` | 硬错误 | 卡只靠 `textual_note` 放行，`语料位置` 首路径不在 `sources/<slug>/raw/`，却标 high | 降为 medium（规则 6）；原文在 `raw/` 里的底本讹字卡可保留 high |
| `P2_COVERAGE` | 警告 | 逐字核对未覆盖全部证据卡 | 不挡路；写进 review.md 准确性一节与 Stage 6.1 摘要；补救是 `mdf acquire` 采原文进 `raw/` |
| `PKG_REVIEW_STATUS_LINE` | 警告 | 技能正文还写着「质量审查：…」 | 删掉这一行；审查结论以 manifest 与 index.json 为准 |
| `[原则候选不足]` / `NO_PRINCIPLES` | 警告 / 硬错误 | 单文件 <6 条或本人来源合计 <8 条 / 一条都没有 | 不许拿评论者观点凑数；先看是不是语料薄（`[不可改善]`） |
| `TOO_FEW_BLIND_SPOTS` | 硬错误 | 核心层盲区主题 <2 | 回 3A 补 |
| `CLASSIFICATION_MISMATCH` | 硬错误 | 框架/身份卡的类目与 `classification.json` 不一致 | 以用户确认的记录为准 |
| 置信度门 | 发布拒绝 | `distill_confidence` <3 | 发布前状态表就显示「受阻」，用 AskUserQuestion 让用户选：补素材 / 接受不入 gallery / `--force` |
| 预算门 | 步骤受阻 | 选中输入 token 超过上限（默认 500,000） | 问用户，同意后 `mdf budget <slug> --approve` |
| 临时数据根 | 警告 | 数据根在 `.claude/worktrees/<name>/` 下 | 阶段 0 先把 `MDF_DATA_ROOT` 挪到 worktree 之外 |

闸门通过记录 `.gates/package.json` 存指纹与 `notes`（目前只带 `P2_COVERAGE`），状态表不加 `--check` 时据此判断「通过且未改动」并显示覆盖率。

### 领域值对象（DDD）

通用语言与不变式在 `docs/architecture.md` 第 9 节，测试会解析表里每个 `模块.名字`，改名或删类时套件直接失败。

| 值对象 | 负责 |
|---|---|
| `workspace.Workspace` | 数据根解析（`--root` > `MDF_DATA_ROOT` > 仓库根）、新进程授权与环境、临时 worktree 判定（`ephemeral`）、产物路径的存取（`portable` 存相对路径，`locate` 读回，`containing` 由产物位置认数据根） |
| `harness.HarnessProfile` | `config/harnesses.json` 一项的能力声明与 argv 构造 |
| `cost_estimator.Budget` | 按选中 token（必知）与费用上界（有价格时）判定是否超预算 |
| `verify_provenance.EvidenceCoverage` | 逐字覆盖率（verified / total / adjudicated）：警告文本的生成与解析、manifest 字段、状态表那句话。用 `NamedTuple` 而非 dataclass，原因见第四节 |

### 实跑结论

| 实跑 | 方式 | 结果 |
|---|---|---|
| extract（2026-10-19） | `mdf run` 简报路径，Sonnet 5.5 high，《熱風》OCR 语料 | 15 条抽取，全部按 OCR 规则封顶 medium、逐字在分片里，检查点通过；暴露费用解析与心跳问题（`cb10d3e` 已修） |
| attachments（scratchpad/realrun） | `mdf run lu-xun attachments --harness claude-code`，Sonnet 5.5 high | 3 分 11 秒，$0.78，0 次权限拒绝；cases.md、evidence.md 字节未变（只做了缺的）；voice.md 24 条；33 个案例回写成 23 行索引，SKILL.md 485 行 |
| Stage 4.5 → 6 dry-run（scratchpad/guirun） | 本会话当编排者，角色由 Sonnet 5.5 high 子代理担任 | 索引 17 行（6 条反例各一行），SKILL.md 479 行，voice.md 28 条；检查点 4 先被 `PKG_CRLF` 拦下（cases.md 465 处 CRLF）；隔离审查 PASS 4.24；dry-run 给出 `BLOCKED_LOW_CONFIDENCE`。暴露 `a46bac5`、`af5883d` 两个 bug |
| GUI 复验（用户启动的会话，笔记 `%TEMP%/claude/D--mind-distill-factory/acceptance-pr11-root/acceptance_notes_pr11.md`） | 按 `bcc78ba` 从 Stage 4.5 复验到 6 dry-run | (a)–(f) 全过：SKILL.md 472 行，覆盖率 12/24（carder 合并了补充卡，分母从 28 变 24），审查 PASS 3.87。问题 1 = `af5883d`，2、3 = `06ca3a1`，4 = `55a8acb`，5、7 只是提示 |

鲁迅包的内容问题（不在管线范围，没改）：表达 DNA 写「不用应当/必须」但语料里出现 22 次（发现 14）；边界规则「已逐字核对」对 12 张网络卡说过头；部分反例案例偏推演。

---

## 一、阶段 2 / P0 已完成（M1–M4）

### M1：共享 slug 校验 + 发布清单 v2
- `scripts/slug_rules.py`：白名单 `^[a-z0-9]+(-[a-z0-9]+)*$`、≤64 字符、拒绝 Windows 保留名（con/nul/com1…）；**只拒绝不规范化**（`"Seneca "` 报错，不再悄悄 `strip().lower()`）。`slug_arg` 供 argparse 用（保留错误原因）。已接入 `publish_skill`、`validate_output`、`local_source_pipeline`、`task_status`、`build_framework_core` 的 CLI
- `scripts/package_manifest.py`：manifest v2 = 文件 sha256 + `clusters`（P4 用）+ 构建期 P2 证明（evidence.md hash + 语料指纹）+ 审查结论。`verify_manifest` 双向核对（列出的文件必须存在且 hash 吻合；包里有、清单没有的文件也报错）。不含时间戳，同内容重发逐字节相同
- `verify_provenance.check_p2_corpus_closure` 可接收已加载的 corpus：P2 与指纹用同一次读盘

### M2：published-only 校验
- `validate_output.py` 拆为 `package`（构建期，读 `output/`，P2 现场比对语料）与 `published`（只读 `gallery/{slug}/` + manifest；P1/P3–P6 原地重跑，P4 簇取自 manifest，P2 由构建期证明担保）。`gallery` 是 `published` 的别名
- legacy 与 v6 一视同仁：都必须有 v2 manifest
- `python scripts/package_manifest.py backfill <slug> [--corpus-root DIR]`：legacy 只记 hash、不写审查结论；v6 重跑 P2，不通过拒绝写入
- 已为 gallery 全部 8 个包补发 v2 manifest（张居正 v6 用主仓库语料重跑 P2 通过）

### M3：事务化发布
- `publish_skill.py`：`gallery/.staging-*` 组包 → 写 manifest → published 校验 → 新 index 写临时文件 → 旧包改名 `.backup-*` → 暂存改名正式 → 临时 index 替换正式（**提交点**）→ 发布后再校验 → 删备份。任一步失败回滚，旧包与旧 index 逐字节恢复
- `recover_interrupted()`：进程中途被杀后，依据临时 index 是否还在判断是否过了提交点，回滚或清理
- v6 身份卡缺 H1/时代/主类、类目不在 `config/taxonomy.json`、副类 >2 → 拒发（不再回落 Unknown/philosophy）
- `review_gate`：PASS 放行；REVISE/MISSING 仅 `--force` 放行并记 `FORCED_<verdict>`；FAIL/UNPARSEABLE/未知值加 `--force` 也拒绝。`review_status` 不再无条件写 PASS
- `--force` 只跳过构建期预检；暂存包的 published 校验永远不可跳过

### M4：P1–P6 加固 + `--strict`
默认规则（package / published 都跑）：
- 证据卡：非空、每卡有逐字原文/出处/confidence（high|medium|low，可带括号注释）、每条核心原则有卡、high 卡必须有「语料位置」、`textual_note` 不得是占位（待定/TODO/？）
- 语感：≥20 条样本，每条有原文、「为什么像他/她」、「误写成通用分析腔」反例
- SKILL.md：表达 DNA 八维齐全且非占位 + ✅/❌ 校准；决策框架为代码块内 3–8 步、每步以「？」结尾；价值取向 ≥2/≥2/≥1；盲区 ≥2 条且每条含缓解/应对；响应策略 反套公式≥6 / 结构自然性≥5 / 边界规则≥5 / 输入类型≥6
- 案例：case_id 唯一且为小写-连字符（与 P5 共用 `CASE_ID_FORMAT_RE`）；每案例的原则簇必须存在
- 模板占位（`{xxx}`、`{repeat_block}`）不得残留

`--strict`（仅 package / published / gallery）：S1 无 low 证据卡；S2 审查结论必须 PASS（构建期读 review.md，发布后读 manifest）；S3 发布包必须有审查记录；S4（阶段 3 新增）证据来源已登记且权利放行。所有阈值集中在 `PACKAGE_SCHEMA`。

v6 模板同步：盲区条目加 `*缓解：*` 槽位，决策框架步骤加「以「？」结尾」提示。

### gallery 现状（`published` 实测）

| 包 | 默认 | strict |
|---|---|---|
| zhang-juzheng-v6 + 6 个 legacy | ✅ | ❌ 无审查记录/非 PASS |
| charlie-munger | ❌ 早期模板，缺 8 个章节 | ❌ |

---

## 二、阶段 1 已完成（来源与抽样链，`4dda010`）

| 文件 | 职责 |
|---|---|
| `scripts/source_registry.py` | 递归扫描 raw、SHA-256、稳定 `source_id`、duplicate 关系、`input_fingerprint`；原子写 registry |
| `scripts/pdf_quality.py` | 页级分类、质量分、OCR 触发；OCR 缺依赖时显式 `unavailable` |
| `scripts/sampling.py` | 确定性分层抽样、strata 覆盖、coverage report |
| `scripts/worker_dispatch.py` | 按上下文/OCR/难度动态派工与建议并发 |
| `scripts/cost_estimator.py` | 无费率时输出 token/request 范围并标 `cost_unknown`，不伪造金额 |

另：`local_source_pipeline.py` PDF 双层文本 + sidecar；`task_status.py` 原子写 + Stage 3 动态 DAG；`verify_provenance.load_corpus` 只认 raw 文本 + 父 PDF hash 绑定的 sidecar。

---

## 三、未完成（按优先级）

### 待人工决定
- **鲁迅 `distill_confidence`=2**：审查 PASS，但低于质量门 3，发布会被拒（`BLOCKED_LOW_CONFIDENCE`）。三选一：补一手素材重跑 / 接受不入 gallery / `--force`（记 `FORCED_LOW_CONFIDENCE`）。验收要求只做 dry-run，目前没发布
- **鲁迅 16 张语料外证据卡**（GUI 复验里合并成 12 张）：原文是维基文库转录，不在 `raw/`，逐字核对只覆盖 12/28。是否用 `mdf acquire` 把《坟》《华盖集》《且介亭杂文》等原典采进来，再让 evidence-carder 改卡
- **charlie-munger**：按 v5 模板补齐 8 个章节，或重新蒸馏
- **张居正 v6 过 strict**：缺 review.md（S2/S3），且 manifest 早于 S4、没有权利汇总（`STRICT_NO_RIGHTS_RECORD`）。要过 strict：补做 Stage 5 审查 → 写 `sources/zhang-juzheng-v6/rights.json` → 重跑 `mdf index` → 重新发布
- **`--install`**：发布时同步装入 `~/.claude/skills`。曾在评审中被**刻意删除**（写仓库外，见 `test_publish_v6.py` 的 `test_install_paths_helper_removed`），恢复需重新拍板。现有替代：`mdf harness plan <slug> --target <harness>` 只打印命令
- ~~文档分支~~ **已合并（2026-10-18，用户批准）**：`claude/dreamy-hamilton-3fd992` 把 README/README.en/AGENTS 对齐 v6，`AGENTS.md` 另补「Running the Pipeline」一节（`mdf` 入口、`mdf run`、三拍叙述）；`mdf harness` 不再报 ⚠️。`README.zh.md` 仍过时
- **采集联系方式与法域**：`config/acquisition_policy.json` 的 `contact` 为空（用环境变量 `MDF_CONTACT`，建议填项目主页 URL，**不要提交个人邮箱**）；`jurisdiction` 为 null，`public_domain_us` 因此一律待复核
- **已有语料的权利声明**：所有本地文件默认 `unverified`，strict 发布会拦（S4）。每个人物要由人写 `rights.json`

### ~~P1：claim provenance 与人格/表达可测指标~~ 已完成（`e91c7c6`）
- `mdf metrics <slug> --write` 输出 `output/{slug}/claim_ledger.json` 与 `persona_metrics.json`；闸门与盲区记为 `basis: synthesis`（综合判断，不假装逐字可溯）
- 指标是**代理指标，只提示不拦截**；校准数据与阈值依据见 `docs/methodology.md` 第六节

### P2：runtime evaluator 与附件读取轨迹
- `evaluation/runtime/run_dialogue_eval.py`：受限 `read_reference`（仅 `references/{cases,evidence,voice}.md`，拒绝绝对路径/`..`）+ `runtime-trace.jsonl`；judge 严格 schema，禁止 `setdefault` 与贪婪正则捞 JSON
- `collect_artifacts.py`：接入 `package` 校验；v6 用 8–11 原则区间；zh-only 不被跨语言指标扣分
- 两个 evaluation 脚本的 `--slug` 尚未接 `slug_rules`

### P3：负面 fixtures、CI、文档收敛
- ~~`evaluation/fixtures/negative/` 不存在~~ **已完成**：10 个单点缺陷负例 + 合规基准包阳性对照，`tests/test_negative_fixtures.py` 进 CI；`regression-protocol.md` 已勘误
- ~~无 `.github/workflows/`~~ **已完成（PR #3）**：离线单测 CI，4 个矩阵组合全绿，未改任何测试
- CI 尚未跑 `validate_output.py published` 全量 gallery；要加这一步，需先处理 charlie-munger

### P4：阶段 3 留下的缺口
- **Codex / pi 端到端实测**：墨子试跑（`docs/harness-trial-mozi.md`，已合并）用 `claude -p` 新进程把简报路径跑到发布（9 次调用 $6.04，审查 PASS 4.04/5），修了 7 处简报/闸门缺口。Codex、pi 本身仍没跑过：用户 2026-10-18 选择暂不真跑（Codex 按量计费；pi 本机只有 9B 本地模型）。试跑报告「未修、需要决策」第 8–14 条：
  - ~~8 类目没有传递通道~~ **已修（`b080dd4`）**：`mdf classify` 写 `classification.json`，下游简报只读不选，不一致报 `CLASSIFICATION_MISMATCH`
  - ~~9 发布后 next 仍指向包校验~~ **已修（`2973239`）**：包校验通过即写 `.gates/package.json`，发布只复制、不改 output 里的包文件，记录保持有效。早于这份记录发布的包，跑一次 `mdf validate package <slug>` 即可
  - ~~10 `validate sources` 的 raw 用非递归 glob~~ **已修（`e141b11`）**：「raw/ 里有哪些素材」只由 `source_registry.indexable_raw_files` 判定（递归，格式与索引器一致，有测试钉住），检查点 1 与状态表都用它；顺带修了状态表漏认 `.markdown`、检查点 1 把 .docx 之类也当素材
  - ~~11 reduce 简报没禁网~~ **已修（`b080dd4`）**：`network: forbidden` + `--disallowedTools WebSearch,WebFetch`
  - ~~12 新进程会再派子代理~~ **已处理（用户 2026-10-20 决定，本 PR）**：每份简报写明不得再派（Stage 5 隔离靠新进程本身）；`mdf run` 在子代理数 >0 时于结果行下告警，写进运行记录 `warnings`、面板用量列标 ⚠️，不判失败；编排协议、编排 skill、`AGENTS.md`、`docs/harnesses.md` 同步
  - ~~13 CRLF 致 hash 不符~~ **已修（`a46bac5`，改判）**：原决定「交由运行时 agent，不加脚本闸门」。GUI 实跑里 Claude Code 子代理根本看不到简报那句，上游 cases.md 带 465 处 CRLF 进了检查点 4，于是加硬闸门 `PKG_CRLF`
  - ~~14 小语料分三个进程~~ **已处理（用户 2026-10-20 决定，本 PR）**：只有 1 个分片时，三步合成执行单位 `small-corpus`（阶段树 `bundles`，`run_unit.RunUnit`）：一份简报、三个角色依次执行、三个检查点都跑；多分片照旧。还没用真实模型跑过合并单位
- `gallery/mozi` 已入库，但 3 篇出处篇名标错（维基文库页眉混入正文，`acquire.py` 已修），包里标了「篇次待核」；要更正需重采 → 重抽取 → 重跑后续阶段
- ~~OCR 真实引擎校准~~ **已完成**：rapidocr 3.10 与 Umi-OCR 自带 PaddleOCR-json 同图对比（8 页 52 句 × 4 字体 × 横竖排 × 4 档退化，64 次运行），数字与结论见 `docs/methodology.md`「OCR 校准」；`mdf ocr survey` 已对本机六个人物的 raw 目录做过整书抽样体检。真实扫描件已抽查七类页面（民国竖排、明刻本对开、透墨国图本、手稿、横排简体、英文），结论见同节「真实扫描件抽查」。整本端到端也跑过：《熱風》1947 年版 134 页纯图片竖排，`mdf index` 空闲时 80 秒，判 flagged（`ocr_text`、`ocr_lines_dropped`、`ocr_incomplete`），52 页共 70 行可疑行，见同节「整本端到端」。遗留：样张仍是系统字体画的合成图，没有真实古籍的纸色、刻工字形与版框；竖排漏检列按列距推算、偏保守，横排漏检的行仍只靠低置信度兜底；刻本双行小注页逐字存活只有约三成，要在识别前切分小注列（未做）；CI 不装引擎，真实引擎路径只在本机验证过
- **对话层指标的人类基线**：`mdf metrics --dialogue` 的阈值来自 25 份已有压测报告，没有人工标注的金标准

### P5：鲁迅验收留下的（已有任务卡，未开工）
- ~~状态文件按绝对路径判定分片完成~~ **已完成**（分支 `claude/portable-data-root`，基于 PR #12）：复制/挪动数据根后 `mdf status` 按新位置如实反映，见第四节。遗留：磁盘上已有的旧 `task_status.json` 要等下一次 `mark-*` 才会被改写成相对路径（读取时已兼容，不影响判定）；`validate_output` 的 Stage 1A/3 状态一致性检查本来就按数据根拼路径，未改
- **表达 DNA 禁忌词对语料核对**（发现 14 管线化）：DNA 写「不用 X」时，确定性地数 X 在本人语料里出现几次，超过阈值就警告。鲁迅包写「不用应当/必须」，语料里有 22 次，审查员是凭读才发现的
- **统一按路径加载模块的 helper**：`spec_from_file_location` 不登记 `sys.modules` 的坑本轮踩了 3 次（见第四节），现在各模块各写一份 `_load_sibling`
- Stage 6.1 成品摘要（覆盖率 + `distill_confidence`）仍只靠协议文字要求编排者写，没有机器闸门；状态表的发布行已能在发布前显示置信度门

---

## 四、重要约束与已知坑

**沿用（阶段 1）**
- 私有语料不在版本控制：`.gitignore` 忽略 `output/`、`evaluation/reports/`、`sources/*`。新测试一律用合成小语料（`tests/test_package_v6.py` 的 `PackageFixture` 已是全规则合规包，可复用）
- OCR 依赖 optional，缺失必须显式 `unavailable`；预算门在任何付费调用之前，非交互 fail-closed
- legacy 包（无 `format_version`）走原双语校验路径

**阶段 2 新增**
- **行尾**：`.gitattributes` 为 `* text=auto eol=lf`，gallery 文件 hash 跨平台稳定。Python 在 Windows 上 `write_text` 默认写 CRLF——写进版本控制的 JSON/MD 一律传 `newline="\n"`
- **Windows 控制台编码**：bash heredoc 里的 Python 源码含中文会被 GBK 破坏（字符串匹配失败）。含中文的替换用 Edit 工具或把脚本写成文件
- **按路径加载模块**绕开了 `sys.modules`：`validate_output._load_sibling` 已加 `lru_cache`，否则 `verify_provenance` 每次重建 OpenCC 转换器，校验慢一倍
- **原子改名**：暂存/备份目录必须与 gallery 同盘（放在 `gallery/` 内）；Windows 上杀毒软件会短暂占用新文件，改名带 `PermissionError` 重试；删目录要先清只读位
- **重发布会清掉 gallery 里 output 没有的文件**（含 legacy 包的 `draft.*.md`）——这是「gallery 只放发布内容」的设计
- **并发发布**两个不同 slug 会互相覆盖 index 更新，未处理（单人单机场景）
- 改了 gallery 里任何文件都必须重发 manifest，否则 `tests/test_published_validation.py::CommittedGalleryTests` 失败
- 规则先在真实样板上实测再定：样板「语料位置」是书目描述而非 `sources/` 路径，所以规则 4 只要求字段存在（语料真实性由 P2 保证）

**阶段 3 新增**
- **数据根目录**：worktree 里没有私有语料。`mdf` 的 `--root` 或环境变量 `MDF_DATA_ROOT` 指向主仓库即可读真实数据；`local_source_pipeline` / `task_status` / `build_framework_core` 的 `repo_root()` 都认它。用真实数据根跑会写文件的命令（如 `mdf brief`）时，产物会落进主仓库的 `output/`
- **解码一致**：index、清洗、P2 必须走 `scripts/text_decoding.decode_bytes`。旧测试曾把「GBK 文件 P2 溯源失败」当成预期行为钉住
- **清洗只删不改**：任何改写正文的「修复」都会让 P2 永远失败。页码标记是定位锚点，不能删；页眉页脚只在紧邻分页处、且不含数字时才删
- **bash heredoc 写 Python**：字符串字面量里的 `\n`、`\\n` 会被写成真换行，文件直接坏掉。含反斜杠的内容用 Edit 工具
- **Write 工具**会把 `\uXXXX` 转义变成字面字符（零宽字符等不可见字符就此混入源码）；需要转义序列时用脚本以 `chr(92)` 拼出反斜杠
- **正则里的 `\s`** 会吞换行：生卒年行「卒年为空」时把下一行读成卒年。只匹配行内空白用 `[ \t]`
- **Mermaid**：子图里有节点连出子图时，`direction` 被忽略（10.x）。分层图别用嵌套子图，用平铺节点 + `&` 并列
- **`claude plugin validate .`** 会警告「插件根的 CLAUDE.md 不作为插件上下文」：在仓库根工作时它本来就是项目上下文，可忽略
- **`codex exec`** 默认只读沙箱，写产物要 `--sandbox workspace-write`；`--full-auto` 已不再支持
- **采集的 User-Agent** 会把 `contact` 发给对方站点：只填愿意公开的联系方式

**鲁迅验收新增（2026-10-19/20）**
- **按路径加载 + dataclass**：`spec_from_file_location` 加载的模块如果不登记进 `sys.modules`，其中的 dataclass 在 `from __future__ import annotations` 下会崩（解析注解时找不到模块）。`EvidenceCoverage` 因此用 `NamedTuple`；`publish_skill._load_sibling` 已改为先登记再执行
- **glob 顺序随平台变**：`Path.glob` 在 Linux 与 Windows 上的顺序不同。依赖顺序的逻辑（如「只报第一个」）在本机绿、CI 的 ubuntu 红。遍历文件一律 `sorted(...)`，测试要断言「每个都报」
- **测试夹具的行尾**：Windows 上 `write_text` 写 CRLF，`PKG_CRLF` 加上后共享夹具 15 个测试一起红。夹具写 .md 一律传 `newline="\n"`
- **GUI 里的项目 agent**：桌面版 Agent 工具可能列不出 `.claude/agents` 里的项目角色（`claude -p` 能）。协议的兜底是 `mdf brief` + general-purpose 子代理
- **数据根放在 worktree 外**：桌面版会回收 worktree，被 gitignore 的 `sources/`、`output/` 一起消失（鲁迅第一轮因此丢到 3A）。验收与实跑一律把 `MDF_DATA_ROOT` 指到 worktree 之外，publish 也认它（`af5883d`）
- **mdf 不按当前目录找数据根**：顺序是 `--root` > `MDF_DATA_ROOT` > 仓库根。`cd <数据根> && python <仓库>/scripts/mdf.py …` 会落回仓库根，而 `validate_output.py`、`task_status.py` 这类脚本按当前目录解析，两者行为不同。简报里「本机这样跑」的命令现在都带 `MDF_DATA_ROOT=`；`mdf reduce` 不收 `--root`
- **状态文件里不存绝对路径**（2026-10-20 发现）：`task_status.init` 曾把 `input_path`/`expected_output`/`manifest_path` 写成数据根下的绝对路径，复制数据根后删掉副本里的抽取结果、重置状态，`mdf status` 仍显示「分片抽取 ✅ 1/1」（原位置的产物还在）；数据根挪走后又一直停在 pending。现在新写入的一律相对数据根，读取经 `Workspace.locate`，旧的绝对路径只取 `sources/…`/`output/…` 起的部分重新挂上（`Workspace.containing` 用状态文件自己的位置认数据根，不看环境变量）。同时 manifest 的 `raw_dir`/`shard_dir`、`source_registry.json` 的 `root` 不再存绝对路径。写新的 JSON 产物时同理：要被读回当真相的路径存相对路径
- **PR 合并早于推送**：PR #10 合并时最后两个提交还没推上去，不在 main 里，只能由下一个 PR 带进去。合并前核对 PR 的 head 提交是不是本地最新

---

## 五、验收命令

```bash
python -m py_compile scripts/*.py
python -m unittest discover -s tests -p 'test_*.py'
python scripts/validate_output.py package <slug> [--strict]
python scripts/validate_output.py published <slug> [--strict]
python scripts/package_manifest.py backfill <slug> [--corpus-root DIR]
python scripts/publish_skill.py --slug <slug> --dry-run
python scripts/mdf.py doctor
python scripts/mdf.py status <slug> [--check] [--json]
python scripts/mdf.py classify <slug> --primary <类目> [--secondary <类目>,<类目>]
python scripts/mdf.py budget <slug> [--approve]
python scripts/mdf.py run <slug> <step> --harness claude-code [--yes]   # 不加 --yes 只打印计划；--yes 是付费调用，先问用户
python scripts/mdf.py harness
python scripts/mdf.py stages --mermaid
python evaluation/scripts/check_negative_fixtures.py
claude plugin validate .
```

## 六、建议的下一动作顺序

1. 人工决定项：鲁迅（`distill_confidence`=2 怎么办、是否 `mdf acquire` 补原典）、charlie-munger、张居正补审 + 权利声明、`--install`、采集联系方式与法域
2. 墨子试跑第 8–14 条已全部处理；合并单位 `small-corpus` 还缺一次真实模型实跑。2026-10-20 在鲁迅副本上试过（Sonnet 5.5 high，鲁迅正好 1 个分片），Claude Code 会话额度用完（429），没跑起来，花费 $0；结果行此后会把这类原因打出来
3. P5 两张任务卡：DNA 禁忌词对语料核对、统一按路径加载 helper
4. P2 runtime `read_reference` + trace + judge schema
5. 用户同意后用 `mdf run --harness codex|pi` 在 Codex、pi 里各跑一步
6. 处理完 charlie-munger 后，在 CI 加 `published` 全量 gallery 校验
