# 交接文书：Mind Distill Factory 工程化改造

本文件为交接给后续线程的实施凭据。已完成部分可运行、可测试；未完成部分按优先级列出，避免重复探索。

- 阶段 1（来源与抽样链）：`4dda010`
- 阶段 2 / P0（发布与校验事务化，M1–M4）：`296b05e` → `861feb8` → `7b5e436` → `655a82f`
- 阶段 3（流水线自动化，分支 `claude/pipeline-automation`）：`effcb3f` → … → `21334b5` 已经 PR #2、#4 合入 main；`0ce2f3d`（OCR 收尾）、`3801fb3`（`mdf run`）、墨子试跑合并、文档分支合并、`66c0537` 及之后的提交在 PR #5。OCR 后续分支 `claude/wonderful-hodgkin-bde0f1` 在 PR #6；两者试合并只有 HANDOFF.md、methodology.md 文本冲突，合并树 559 个测试通过，后合的那个解决冲突

测试基线：`python -m unittest discover -s tests -p 'test_*.py'`
结果：`Ran 546 tests ... OK (skipped=11)`（skipped 为依赖私有 raw corpus 的 `test_zhang_provenance_audit.py`，属预期）

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
| 本次 | 明刻本抽查的两处修正：`mdf ocr scan --pages`/`survey` 改在原文件上逐页读（分层压缩扫描件拷进临时 PDF 后渲染不同，置信度与识别文字都变，导出的图也对不上）；被音注撑宽的被丢框按本页字号折算字数，限宽 ≤1.5 字宽且读出 ≥3 个汉字，排除馆藏印章与插图标注 | `scripts/local_source_pipeline.py`、`scripts/ocr_calibrate.py`、`scripts/pdf_quality.py`、`docs/methodology.md` |
| `3801fb3` | 墨子试跑的可视化反馈（没有章节标签、叙述没节奏、全是无头脚本）：`mdf run` 把「简报→新进程→心跳→状态变化→阶段检查点→运行记录」收成一条命令（不加 `--yes` 只打印计划）；阶段卡 `mdf next --card`、进度条、自包含可视化面板 `mdf status --html`；编排协议写明三拍叙述与章节工具确切名 `mcp__ccd_session__mark_chapter`，驱动无头进程的会话也算编排者 | `scripts/stage_runner.py`、`scripts/pipeline_status.py`、`commands/distill.md`、`.agents/skills/mdf-distill/SKILL.md`、`config/harnesses.json`、`docs/harnesses.md` |
| `66c0537` | 整本扫描书端到端（《熱風》134 页竖排，`mdf index` → `mdf clean`）暴露的两处页眉页脚漏删：字距拉开的页眉拆成单字框插进正文列（竖排页里落在正文列起止线之外的单字框归页首页尾，起止线取四分位）；页码短横认成「一」或丢一边（页边纯数字加横线的行一律按页码计数）。页眉页脚删除 41→171 行，无正文误删；rapidocr 日志降到 error。另 8 本竖排书各抽 8 页审计：被归到页边的 44 个单字框全是页眉页码，没有正文 | `scripts/pdf_quality.py`、`scripts/clean_corpus.py`、`docs/methodology.md` |

文档入口：[架构](docs/architecture.md) · [方法论](docs/methodology.md) · [伦理与法律](docs/ethics-and-legal.md) · [harness 适配](docs/harnesses.md)。

CI：`.github/workflows/tests.yml`（PR #3 合入）在 ubuntu + windows × Python 3.12 / 3.13 上跑 `py_compile` 与全套单测，触发于所有 PR 及 push 到 main；不装 extras、无网络/OCR/API key 依赖。

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
- **Codex / pi 端到端实测**：墨子试跑（`docs/harness-trial-mozi.md`，已合并）用 `claude -p` 新进程把简报路径跑到发布（9 次调用 $6.04，审查 PASS 4.04/5），修了 7 处简报/闸门缺口。Codex、pi 本身仍没跑过：用户 2026-10-18 选择暂不真跑（Codex 按量计费；pi 本机只有 9B 本地模型）。试跑报告「未修、需要决策」第 8–14 条（类目传递通道、发布后 next 仍指向包校验、raw 非递归 glob、reduce 简报未禁网、新进程再派子代理、CRLF、合并小语料步骤）尚未处理
- `gallery/mozi` 已入库，但 3 篇出处篇名标错（维基文库页眉混入正文，`acquire.py` 已修），包里标了「篇次待核」；要更正需重采 → 重抽取 → 重跑后续阶段
- ~~OCR 真实引擎校准~~ **已完成**：rapidocr 3.10 与 Umi-OCR 自带 PaddleOCR-json 同图对比，数字与结论见 `docs/methodology.md`「OCR 校准」。真实扫描件已抽查七类页面（民国竖排、明刻本对开、透墨国图本、手稿、横排简体、英文），结论见同节「真实扫描件抽查」。整本端到端也跑过：《熱風》1947 年版 134 页纯图片竖排，`mdf index` 空闲时 80 秒，判 flagged（`ocr_text`、`ocr_lines_dropped`、`ocr_incomplete`），52 页共 70 行可疑行，见同节「整本端到端」。遗留：样张只有 3 页 19 句、只用宋体；没被检测出来的行（透墨、淡印）不计入可疑行；刻本双行小注会与大字交错；CI 不装引擎，真实引擎路径只在本机验证过
- **对话层指标的人类基线**：`mdf metrics --dialogue` 的阈值来自 25 份已有压测报告，没有人工标注的金标准

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
python scripts/mdf.py harness
python scripts/mdf.py stages --mermaid
python evaluation/scripts/check_negative_fixtures.py
claude plugin validate .
```

## 六、建议的下一动作顺序

1. 人工决定项：charlie-munger、张居正补审 + 权利声明、`--install`、采集联系方式
2. PR #2、#4 已于 2026-10-17 合入 main；之后的提交（OCR 收尾、`mdf run`、墨子试跑与文档分支合并）走新 PR
3. 处理墨子试跑报告第 8–14 条；用户同意后用 `mdf run --harness codex|pi` 在 Codex、pi 里各跑一步
4. P2 runtime `read_reference` + trace + judge schema
5. 处理完 charlie-munger 后，在 CI 加 `published` 全量 gallery 校验
