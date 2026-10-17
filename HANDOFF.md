# 交接文书：Mind Distill Factory 工程化改造

本文件为交接给后续线程的实施凭据。已完成部分可运行、可测试；未完成部分按优先级列出，避免重复探索。

- 阶段 1（来源与抽样链）：`4dda010`
- 阶段 2 / P0（发布与校验事务化，M1–M4）：`296b05e` → `861feb8` → `7b5e436` → `655a82f`

测试基线：`python -m unittest discover -s tests -p 'test_*.py'`
结果：`Ran 293 tests ... OK (skipped=11)`（skipped 为依赖私有 raw corpus 的 `test_zhang_provenance_audit.py`，属预期）

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

`--strict`（仅 package / published / gallery）：S1 无 low 证据卡；S2 审查结论必须 PASS（构建期读 review.md，发布后读 manifest）；S3 发布包必须有审查记录。所有阈值集中在 `PACKAGE_SCHEMA`。

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
- **张居正 v6 缺 review.md**：补做 Stage 5 审查后才能过 strict；在此之前重发须 `--force`（记 `FORCED_MISSING`）
- **`--install`**：发布时同步装入 `~/.claude/skills`。曾在评审中被**刻意删除**（写仓库外，见 `test_publish_v6.py` 的 `test_install_paths_helper_removed`），恢复需重新拍板
- **文档分支** `claude/dreamy-hamilton-3fd992`（`e853e3d`：README/README.en/AGENTS 对齐 v6）未合并；`README.zh.md` 仍过时

### P1：claim provenance 与人格/表达可测指标
- `claim_ledger.json`：原则/闸门/盲区/引用/voice sample 绑定 `claim_id → evidence → source_id/page/hash`
- 覆盖矩阵与确定性指标：去名后人物特异锚点、单来源集中度、人称漂移、序数公式、口号重复、句长/段落 CV

### P2：runtime evaluator 与附件读取轨迹
- `evaluation/runtime/run_dialogue_eval.py`：受限 `read_reference`（仅 `references/{cases,evidence,voice}.md`，拒绝绝对路径/`..`）+ `runtime-trace.jsonl`；judge 严格 schema，禁止 `setdefault` 与贪婪正则捞 JSON
- `collect_artifacts.py`：接入 `package` 校验；v6 用 8–11 原则区间；zh-only 不被跨语言指标扣分
- 两个 evaluation 脚本的 `--slug` 尚未接 `slug_rules`

### P3：负面 fixtures、CI、文档收敛
- `evaluation/fixtures/negative/` 不存在，`regression-protocol.md` 却声称有 4 个
- 无 `.github/workflows/`；CI 需在无网络、无 OCR、无 API key 下通过（现有测试已满足：P6 pilot 测试改读已提交的 gallery 副本）
- CI 若跑 `published` 全量，需先处理 charlie-munger

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

---

## 五、验收命令

```bash
python -m py_compile scripts/*.py
python -m unittest discover -s tests -p 'test_*.py'
python scripts/validate_output.py package <slug> [--strict]
python scripts/validate_output.py published <slug> [--strict]
python scripts/package_manifest.py backfill <slug> [--corpus-root DIR]
python scripts/publish_skill.py --slug <slug> --dry-run
```

## 六、建议的下一动作顺序

1. 人工决定项（charlie-munger、张居正补审、文档分支合并、`--install`）
2. P3 的 CI 骨架（测试已可离线跑通，成本最低、收益立刻可见）
3. P1 claim ledger 与覆盖矩阵
4. P2 runtime `read_reference` + trace + judge schema
5. P3 负面 fixtures + 文档 drift 清零
