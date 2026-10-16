# 交接文书：Mind Distill Factory 工程化改造（阶段 1 / 来源与抽样链）

本文件为交接给后续线程的实施凭据。已完成部分可运行、可测试；未完成部分按优先级列出，避免重复探索。

## 一、本次已完成（已通过全套单测）

测试基线：`python -m unittest discover -s tests -p 'test_*.py'`
结果：`Ran 170 tests ... OK (skipped=11)`（skipped 为依赖私有 raw corpus 的 `test_zhang_provenance_audit.py`，属预期）

### 1. 新增模块（全部新建，无破坏性改动）

| 文件 | 职责 |
|---|---|
| `scripts/source_registry.py` | 递归扫描 raw、SHA-256、稳定 `source_id`、canonical URL、duplicate 关系、`input_fingerprint`；原子写 registry |
| `scripts/pdf_quality.py` | 页级分类（纯文字 / 图像 / 混合 / 空白）、质量分与 band、图像实体性判定、OCR 触发；OCR adapter（RapidOCR CPU 档 → 可选 PaddleOCR 高精度档），缺依赖时显式返回 `unavailable` 而非静默 |
| `scripts/sampling.py` | 确定性分层抽样（seed + 稳定 hash 排序）、strata 最低覆盖、inclusion probability、coverage report |
| `scripts/worker_dispatch.py` | 按上下文窗口 / token / OCR / 理解难度生成动态派工计划与建议并发；高难度 shard 单独派发 |
| `scripts/cost_estimator.py` | 区分确定性扫描/OCR 与 LLM worker/reducer；无费率时输出 token/request 范围并标记 `cost_unknown`，不伪造金额 |

### 2. 修改的关键文件

- `scripts/local_source_pipeline.py`
  - PDF 抽取返回页记录（native text / OCR / quality / band），保留双层文本；fitz 部分失败不污染 pypdf 回退（清空 pages 重组）
  - 输出 `source_registry.json`、`extracted/{source_id}.txt/.json`（PDF sidecar，绑定 `parent_sha256`）
  - 递归扫描 nested raw；unsupported 带明确 reason
  - `write_index()` 重建时清理旧 shard/worker 输出；manifest v2 含 `input_fingerprint`、sampling/dispatch/cost 指针、`sampling_mode`、`recommended_max_concurrency`
  - 大语料按 `sampling_plan` 实际筛选 shard；小语料 exhaustive 但仍产出计划
  - reducer 只加载当前 manifest 的 shard、且 `input_fingerprint`/`shard_id` 匹配的输出；不匹配直接丢弃
- `scripts/task_status.py`
  - 状态文件原子写（临时文件 + `os.replace`），避免并行 worker 截断
  - `schema_version: task-status-v2`
  - Stage 3 动态 DAG：默认仅中文自检，`en_requested.flag` 存在才创建 `framework_en` 并将 alignment 依赖改为 zh+en
  - `sync_outputs()` 不再是“文件存在即完成”：shard 输出必须匹配 `input_fingerprint` + `shard_id`；框架类检查 slug 与非空
  - Stage 1A unit 携带 `input_fingerprint`
- `scripts/verify_provenance.py`
  - `load_corpus()` 只接受 raw 文本 + **父 PDF hash 匹配**的 sidecar；processed 派生文本不再自证，解决“派生文件证明自己”的缺口
- `scripts/validate_output.py`
  - `validate_sources()` 将 registry / provenance / sampling / cost 等元数据排除出 legacy extract schema 循环
- `config/defaults.json`
  - `supported_formats` 去掉未实现的 `epub`（与实现对齐）
  - 新增 `registry` / `pdf`（三类 PDF、OCR 触发与默认/升级后端、质量下限）/ `sampling`（seed 策略、大语料阈值、预算门）
- `pyproject.toml`
  - 新增 optional extras：`pdf`、`ocr`（CPU 档）、`ocr-high-accuracy`（PaddleOCR）
- 文档/契约
  - `commands/distill.md`：主 agent 动态分批派工、预算门前必须 AskUserQuestion、worker 回写 `shard_id`+`input_fingerprint`
  - `agents/local-source-indexer.md` / `local-source-worker.md`：同步上述契约
  - `sources/README.md`：重写来源与 PDF/OCR/抽样/成本说明
- 测试
  - 新增 `tests/test_source_pipeline_v2.py`（PDF 三分类、registry 递归与指纹、抽样可复现、派工限并发、无费率时 cost_unknown）
  - 扩展 `tests/test_provenance_core.py`（hash 绑定 sidecar 接受、未绑定 sidecar 拒绝）

## 二、未完成（按优先级，建议下一线程继续）

### P0：发布与校验事务化（尚未开始）
- `scripts/publish_skill.py`
  - 当前仍是「先复制 → 写 index → 后校验」，失败留半发布状态；`save_json` 无回滚
  - 需改为 staging → 完整校验 → 原子替换；清理 gallery 旧附件/旧 dossier；失败保留旧包与 index
  - slug 仅 `strip().lower()`，需共享 slug 校验（拒绝空/`.`/`..`/分隔符/Unicode 空白/路径穿越）
  - v6 缺身份卡时静默回落 `Unknown`/`philosophy`，应拒绝发布
  - `review_status` 无条件写 `PASS`，须改为真实 review/runtime gate
- `scripts/validate_output.py`
  - `validate_package()` 固定校验 `output/{slug}`；`validate_gallery()` 复用它，导致 gallery 校验依赖未发布的 output/raw
  - 需拆出 `published` 校验：只依赖 gallery 内文件 + package manifest（新增 `scripts/package_manifest.py`），把 `framework_core.json` 的 cluster 信息随包发布或改由 manifest 提供
  - P1–P6 加固：空 evidence/voice、voice <20、八维缺失、重复 case_id、未知 cluster、未决人工裁决、decision framework 改结构化 `gate_type/pass_condition/fail_action`
  - `--strict` 模式：缺失/空内容/未决 provenance/低 confidence/reviewer 非 PASS 一律硬失败

### P1：claim provenance 与人格/表达可测指标（尚未开始）
- `claim_ledger.json`：原则/闸门/盲区/引用/voice sample 绑定 `claim_id → evidence → source_id/page/hash`
- 覆盖矩阵与确定性指标：去名后人物特异锚点、单来源集中度、第一/第三人称漂移、序数公式、口号重复、句长/段落 CV

### P2：runtime evaluator 与附件读取轨迹（尚未开始）
- `evaluation/runtime/run_dialogue_eval.py`
  - 当前只把 `SKILL.md` 拼进 system prompt，没有 tool loop，无法证明 references 被读取
  - 需受限 `read_reference`（仅 `references/{cases,evidence,voice}.md`，拒绝绝对路径/`..`），写 `runtime-trace.jsonl`
  - judge 输出需严格 schema（case 一一对应、0–5 范围、flag/severity 枚举、aggregate 本地重算），禁止 `setdefault` 与贪婪正则捞 JSON
  - `collect_artifacts.py`：加入 `package` 校验；v6 用 8–11 原则区间；zh-only 不应被跨语言指标扣分；比对 references/manifest 而非仅 SKILL.md

### P3：负面 fixtures、CI、文档收敛（尚未开始）
- `evaluation/fixtures/negative/` 实际不存在，regression-protocol 却声称有 4 个
- 无 `.github/workflows/`；CI 需在无网络、无 OCR、无 API key 下稳定通过，真实 LLM/OCR 作为手动 job
- 文档漂移：根 `README.md`、`README.en.md` 仍描述旧单文件双语；`AGENTS.md` 与 v6 中文默认冲突
- `test_package_v6.py:379` 直接读被 gitignore 的 `output/zhang-juzheng-v6/SKILL.md` 且不 skip，干净 checkout 会失败，需 skipUnless 或改用可提交 fixture

## 三、重要约束与已知坑

- 私有语料不在版本控制：`.gitignore` 忽略 `output/`、`evaluation/reports/`、`sources/*`（仅保留 `sources/README.md`）。因此 `zhang-juzheng-v6` 只能作发布结构样板，不能作 P2/package 的稳定验收基线；新增测试请用合成小语料
- Windows 环境：`git status` 正常；替换目录需用 backup + `os.replace`，不要假设 POSIX rename 语义
- OCR 依赖为 optional，缺失时必须显式 `unavailable`/`ocr_required`，不得把扫描页当高置信来源
- 预算门必须发生在任何付费 LLM 调用 / 大规模 OCR / 网络补充之前；非交互环境 fail-closed
- 旧 legacy 包（无 `format_version`）必须继续走原双语校验路径，不得被 v6 闸门误判

## 四、验收命令

```bash
python -m py_compile scripts/*.py
python -m unittest discover -s tests -p 'test_*.py'
python scripts/validate_output.py sources <slug>
python scripts/validate_output.py package <slug>
python scripts/validate_output.py gallery <slug>
```

## 五、建议的下一动作顺序

1. 共享 slug 校验 + package manifest（`scripts/package_manifest.py`）
2. `validate_output.py` 拆 `build` / `published`，gallery 改为 published-only
3. `publish_skill.py` 事务化（staging / 原子替换 / rollback / index 恢复）
4. P1–P6 加固与 `--strict`
5. claim ledger 与覆盖矩阵
6. runtime `read_reference` + trace + judge schema
7. 负面 fixtures + CI + 文档 drift 清零
