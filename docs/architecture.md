# 架构说明

本文讲**工厂怎样搭起来**：分几层、数据怎么流、闸门放在哪、在不同 harness 里怎么跑。**为什么这样抽取**见 [方法论](methodology.md)；**合规边界**见 [伦理与法律规范](ethics-and-legal.md)。

一句话：**判断交给 agent，事实交给脚本，决定交给人。** agent 负责读和写（抽取、合成、组装、审查）；`mdf` 命令行负责一切能确定判定的事（登记、清洗、分片、闸门、发布）；采不采、能不能用、发不发，由人拍板。

---

## 1. 分层

```mermaid
flowchart TB
    U["<b>人 / GUI</b><br/><small>出题 · 提供素材 · 权利声明 · 拍板发布<br/>章节导航 · 任务清单 · 状态面板</small>"]
    CC["Claude Code<br/><small>插件 /mind-distill-factory:distill</small>"]
    CX["Codex<br/><small>skill $mdf-distill</small>"]
    PI["pi<br/><small>skill /skill:mdf-distill</small>"]
    P["<b>编排协议</b>（Markdown，harness 无关）<br/><small>commands/distill.md · agents/*.md（14 个角色）· config/pipeline_stages.json</small>"]
    K["<b>确定性内核</b>：python scripts/mdf.py<br/><small>status · next · stages · brief<br/>acquire · index · clean · reduce<br/>validate：P1–P6 · L1–L2 · S1–S4<br/>publish · manifest · metrics · harness · ocr</small>"]
    S["sources/{slug}/<br/><small>原典与中间结果（不入库）</small>"]
    O["output/{slug}/<br/><small>框架、草稿包、简报、审查（不入库）</small>"]
    G["gallery/{slug}/<br/><small>已发布包 + manifest（入库）</small>"]
    U --> CC & CX & PI
    CC & CX & PI --> P
    P --> K
    K --> S & O & G
    U -. GUI 读 mdf status --json .-> K
```

| 层 | 内容 | 设计约束 |
|----|------|---------|
| harness 适配 | `.claude-plugin/plugin.json`、`.agents/skills/mdf-distill/SKILL.md`、`config/harnesses.json` | 只做**入口与转接**，不复制协议内容，避免三份说明各自漂移 |
| 编排协议 | `commands/distill.md`、`agents/*.md`、`config/pipeline_stages.json` | 纯 Markdown / JSON，任何能读文件、跑命令的 agent 都能执行 |
| 确定性内核 | `scripts/mdf.py` 统一入口，转交给各脚本 | 不调用模型、不联网（`acquire` 除外，它有完整闸门）；人看 Markdown，程序读 `--json` |
| 数据 | `sources/`、`output/`、`gallery/` | 原典与中间结果在 `.gitignore` 里；只有 `gallery/` 的发布内容入库 |

---

## 2. 阶段树

阶段、步骤、执行者、检查点都定义在 `config/pipeline_stages.json`，它是唯一来源：`mdf status` 用它排进度，章节标签用它取标题，下面这张图也由它生成（`python scripts/mdf.py stages --mermaid`；测试会比对，配置改了图没跟着改就失败）。

矩形是脚本步骤，圆角是 agent 步骤，平行四边形是需要人参与的步骤，六边形是阶段检查点（不过不放行）。

<!-- BEGIN GENERATED: mdf stages --mermaid -->
```mermaid
flowchart TD
    subgraph init["阶段 0 · 意图澄清与初始化"]
        init_init["目录初始化<br/><small>脚本</small>"]
    end
    subgraph stage1["阶段 1 · 素材采集"]
        stage1_sources[/"素材入库<br/><small>人工、脚本</small>"/]
        stage1_index["登记、抽取与分片<br/><small>脚本</small>"]
        stage1_clean["清洗与质量闸门<br/><small>脚本</small>"]
        stage1_extract(["分片抽取<br/><small>agent</small>"])
        stage1_reduce["合并与网络补充<br/><small>脚本、agent</small>"]
        stage1_checkpoint{{"✓ validate sources"}}
    end
    subgraph stage2["阶段 2 · 原则提取"]
        stage2_principles(["原则提取<br/><small>agent</small>"])
        stage2_checkpoint{{"✓ validate principles"}}
    end
    subgraph stage3["阶段 3 · 框架合成"]
        stage3_frameworks(["框架合成与自检<br/><small>agent</small>"])
        stage3_checkpoint{{"✓ validate frameworks"}}
    end
    subgraph stage4["阶段 4 · 组装与附件"]
        stage4_assemble(["核心层组装<br/><small>agent</small>"])
        stage4_attachments(["附件生成<br/><small>agent</small>"])
        stage4_gates["P1–P6 包校验<br/><small>脚本</small>"]
        stage4_checkpoint{{"✓ validate package"}}
    end
    subgraph stage5["阶段 5 · 质量审查"]
        stage5_review(["质量审查<br/><small>agent</small>"])
    end
    subgraph stage6["阶段 6 · 发布与安装"]
        stage6_publish["发布<br/><small>脚本</small>"]
        stage6_checkpoint{{"✓ validate published"}}
    end
    init_init --> stage1_sources
    stage1_sources --> stage1_index
    stage1_index --> stage1_clean
    stage1_clean --> stage1_extract
    stage1_extract --> stage1_reduce
    stage1_reduce --> stage1_checkpoint
    stage1_checkpoint --> stage2_principles
    stage2_principles --> stage2_checkpoint
    stage2_checkpoint --> stage3_frameworks
    stage3_frameworks --> stage3_checkpoint
    stage3_checkpoint --> stage4_assemble
    stage4_assemble --> stage4_attachments
    stage4_attachments --> stage4_gates
    stage4_gates --> stage4_checkpoint
    stage4_checkpoint --> stage5_review
    stage5_review --> stage6_publish
    stage6_publish --> stage6_checkpoint
    classDef agent fill:#eef4ff,stroke:#4a6fd1
    classDef human fill:#fff6e5,stroke:#c98a12
    class stage1_sources human
    class stage1_extract agent
    class stage2_principles agent
    class stage3_frameworks agent
    class stage4_assemble agent
    class stage4_attachments agent
    class stage5_review agent
```
<!-- END GENERATED -->

**进度可见性。** 每进入一个阶段，编排者先打一次章节标签：有章节工具的 harness（Claude 桌面版）调用工具，左侧导航就会出现「阶段 N · 标题」；没有的（Codex、pi、终端）输出同名 H2 标题。任何时候 `mdf status <slug>` 都能重建全貌：它只看磁盘上的产物，不依赖对话记忆，所以中断后换个 harness 接着做也不丢进度。

---

## 3. 数据流与证据链

```mermaid
flowchart LR
    R["raw/<br/>原典 PDF/TXT/MD"] --> REG["source_registry.json<br/><small>sha256 · source_id · 权利</small>"]
    RJ["rights.json<br/><small>人工权利声明</small>"] --> REG
    AQ["acquisition_log.jsonl<br/><small>采集来源与权利</small>"] --> REG
    R --> CL["清洗（只删不改）<br/><small>cleaning_report.json</small>"]
    CL --> SH["local_shards/<br/><small>分片 + quality_flags</small>"]
    SH --> EX["*_extracts.json<br/><small>逐字摘录候选</small>"]
    EX --> US["user_sources.json 等<br/><small>归并去重</small>"]
    US --> PR["principles_*.json"]
    PR --> FC["framework_core.json<br/><small>原则簇 · 盲区主题</small>"]
    FC --> FZ["frameworks.zh.json"]
    FZ --> SK["SKILL.md"]
    FC --> RF["references/<br/><small>cases · evidence · voice</small>"]
    RF --> SK
    SK --> MF["manifest.json<br/><small>文件 hash · P2 证明 · 权利汇总 · 审查结论</small>"]
    RF --> MF
    MF --> GL["gallery/{slug}/"]
    R -. P2 逐字比对 .-> RF
```

两条不变量贯穿全程：

1. **只删不改。** 清洗只删除整行或整段噪声，从不改写正文，所以证据卡里的逐字原文永远能在 `raw/` 里找回原样（P2）。页码标记作为定位锚点受保护。
2. **同一份解码。** 抽取、清洗、P2 溯源都经过 `scripts/text_decoding.py`（UTF-16 BOM → UTF-8 → GB18030 → Big5），不会出现抽得出、却溯不了源的编码分叉。

---

## 4. 闸门分布

| 位置 | 闸门 | 判定方式 | 失败时 |
|------|------|---------|-------|
| 采集 | 白名单、robots.txt、TDMRep 保留、限速、权利三态、内容类型与大小 | 规则 | 拒绝并记日志，不落盘 |
| 清洗 | PUA / U+FFFD 占比、近重复、页眉页脚 | 规则 + 阈值 | 文件被拒收或打标，写入清洗报告 |
| 阶段 1–3 检查点 | 结构、schema、原则可溯源、过滤链 | 规则 | 不进入下一阶段 |
| 阶段 4（`validate package`） | P1 引文闭合、P2 语料闭合、P3 附件路径、P4 按簇覆盖、P5 案例索引、P6 核心自足；L1 引文长度、L2 在世人物声明 | 规则（无 LLM 打分） | 不进入审查 |
| 阶段 5 | 独立审查，裁决 `[PASS / REVISE / FAIL]` | 隔离的 agent | REVISE 回到对应阶段 |
| 阶段 6（`publish`） | 暂存包重跑 published 校验；审查裁决门 | 规则 | 事务回滚 |
| `--strict` | S1 无 low 证据、S2 审查 PASS、S3 有审查记录、S4 证据来源权利放行 | 规则 | 不得进入正式发布 |

闸门全是规则，没有 LLM 打分：曾有 LLM 审查员把抽查的 7 条引文全判为「EXACT」，而同一组 15 条里有 4 条并非逐字。代理指标（`mdf metrics`：来源集中度、文体距离、人称漂移……）只提示、不拦截，见方法论第六节。

---

## 5. 在不同 harness 里跑

| | Claude Code | Codex | pi |
|---|---|---|---|
| 加载 | 仓库根目录 `claude --plugin-dir .` | 仓库根目录启动，自动扫描 `.agents/skills` | 同 Codex |
| 编排入口 | `/mind-distill-factory:distill <人物>` | `$mdf-distill <人物>` | `/skill:mdf-distill <人物>` |
| 规则来源 | `CLAUDE.md` | `AGENTS.md`（编排 skill 声明以 `CLAUDE.md` 为准） | `AGENTS.md` + `CLAUDE.md` |
| agent 步骤 | 原生子代理（`agents/*.md`） | `mdf brief` + `codex exec` 新进程 | `mdf brief` + `pi -p` 新进程 |
| 进度标签 | 桌面版章节工具 | H2 兜底标题 | H2 兜底标题 |

完整说明、核对来源与已知限制见 [harness 适配](harnesses.md)；`python scripts/mdf.py harness` 现场检测本机装了哪些 harness、适配文件是否就位。

agent 步骤在不同 harness 里走不同的路，交付物却一样：

```mermaid
flowchart LR
    N["mdf status / next<br/><small>下一步是 agent 步骤</small>"] --> Q{"harness 有子代理？"}
    Q -- 有 --> SA["子代理执行<br/><small>agents/&lt;role&gt;.md</small>"]
    Q -- 没有 --> B["mdf brief &lt;slug&gt;<br/><small>写 output/&lt;slug&gt;/briefs/&lt;step&gt;.md</small>"]
    B --> P["新进程执行简报<br/><small>codex exec / pi -p / claude -p</small>"]
    SA --> F["产物写入 output/ 或 processed/"]
    P --> F
    F --> V["mdf validate &lt;stage&gt;<br/><small>检查点</small>"]
```

简报自足：角色定义全文、slug、当前状态、规则、检查点都在一个文件里，新进程不需要任何对话历史。这也是 Stage 5「不得自审」在没有子代理的 harness 里也能做到的原因：审查在一个从没见过生成过程的进程里进行。

---

## 6. 发布事务

```mermaid
sequenceDiagram
    participant P as mdf publish
    participant G as gallery/
    participant I as index.json
    P->>G: 恢复上次中断的残留（recover_interrupted）
    P->>G: 组包到 .staging-{slug}-{token}/（不含中间产物）
    P->>G: 写 manifest：文件 hash + P2 证明 + 权利汇总 + 审查结论
    P->>G: 对暂存包跑 published 校验（--force 也不能跳过）
    P->>I: 新 index 写临时文件
    P->>G: 旧包改名 .backup-*，暂存包改名为正式目录
    P->>I: 临时 index 替换正式 index（提交点）
    P->>G: 发布后再校验一次，删除备份
    Note over P,G: 提交点之前任一步失败：旧包与旧 index 逐字节恢复
```

manifest 不含时间戳，同样的内容重发，manifest 逐字节相同。发布后的校验（`validate published`）只读 `gallery/` 与 manifest：P2 由构建期证明担保，strict 的权利检查读 manifest 里的权利汇总，所以 gallery 可以脱离私有语料独立复核。

装进 harness 的技能目录是写仓库外的操作，工厂不自动做。`python scripts/mdf.py harness plan <slug> --target <harness>` 只打印命令，由用户执行（不复制 `人物档案.md`）。

---

## 7. 目录

```text
mind-distill-factory/
├── .claude-plugin/plugin.json      Claude Code 插件清单
├── .agents/skills/mdf-distill/     Codex / pi 的编排入口
├── commands/distill.md             阶段协议（编排者读）
├── agents/*.md                     14 个角色定义
├── config/
│   ├── pipeline_stages.json        阶段树与章节规则（唯一来源）
│   ├── harnesses.json              各 harness 的入口、子代理、章节能力与核对来源
│   ├── acquisition_policy.json     采集白名单、限速、权利词汇
│   └── taxonomy.json · defaults.json
├── scripts/mdf.py                  统一命令行入口
├── scripts/*.py                    确定性内核
├── templates/                      v6 模板与样例
├── docs/                           架构 · 方法论 · 伦理与法律 · harness 适配
├── sources/{slug}/                 raw/ 原典 · processed/ 中间结果 · rights.json（均不入库）
├── output/{slug}/                  框架、草稿包、简报、审查（不入库）
├── gallery/{slug}/                 已发布包 + manifest.json（入库）
└── tests/                          离线单测（CI：ubuntu + windows × py3.12/3.13）
```

---

## 8. 人在哪里控制

| 节点 | 人做什么 | 工厂怎样配合 |
|------|---------|------------|
| 开题 | 选人物、确认分类、判断在世人物是否适合蒸馏 | `mdf init`；L2 声明闸门 |
| 素材 | 提供原典、写 `rights.json` | `mdf acquire` 只放行白名单与已声明权利；`mdf index` 打 WARNING |
| 清洗 | 看被拒、被打标的文件 | `mdf clean` 报告逐文件列出原因 |
| 每个检查点 | 看 `mdf status` | 不过不放行；失败信息带文件与行号 |
| 审查 | 读 `review.md`，接受或要求返工 | 裁决写进 manifest；REVISE、MISSING 需 `--force` 才能发布，并记为 `FORCED_*` |
| 发布与安装 | 决定发不发、装到哪 | 事务式发布；`harness plan` 只打印安装命令 |
