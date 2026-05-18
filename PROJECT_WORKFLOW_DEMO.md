# Mind Distill Factory · Workflow Demo

面向演示的项目工作流图。风格目标是 Claude 式的“清晰、克制、可追踪”：先给一张全局地图，再展示数据产物、质量闸门、运行期调优闭环，最后给出当前发布态检查。

## 1. Factory Spine

```mermaid
flowchart LR
  U["User intent\n/distill <person>"]:::input
  S0["Stage 0\nIntent framing"]:::stage
  S1["Stage 1\nSource collection"]:::stage
  S2["Stage 2\nPrinciple extraction"]:::stage
  S3["Stage 3\nFramework synthesis"]:::stage
  S4["Stage 4\nSkill assembly"]:::stage
  S5["Stage 5\nQuality review"]:::stage
  S6["Stage 6\nPublish & install"]:::stage
  S7["Stage 7\nRuntime tuning"]:::stage

  U --> S0 --> S1 --> S2 --> S3 --> S4 --> S5
  S5 -- "PASS" --> S6 --> S7
  S5 -- "REVISE" --> S4
  S5 -- "FAIL" --> S1
  S7 -- "patch skill / backflow template" --> S4

  classDef input fill:#F7F7F5,stroke:#6B6B6B,color:#202124,stroke-width:1px;
  classDef stage fill:#F3F1EA,stroke:#8A8175,color:#201F1D,stroke-width:1.2px;
```

这条主干的关键设计不是“生成一个角色提示词”，而是把人物思想压缩成可执行的认知系统：来源证据、原则抽取、双语框架、表达 DNA、盲点缓解、运行期对话测试，全都必须能回到具体文件与校验门。

## 2. Artifact Conveyor

```mermaid
flowchart TB
  subgraph A["Input Layer"]
    A1["sources/{slug}/raw/\nPDF · TXT · MD"]:::data
    A2["config/taxonomy.json\ncategory map"]:::data
    A3["templates/\nSkill templates + examples"]:::data
  end

  subgraph B["Processed Evidence"]
    B1["sources/{slug}/processed/user_sources.json"]:::json
    B2["web_sources.json"]:::json
    B3["bibliography.json"]:::json
    B4["coverage_report.json"]:::json
  end

  subgraph C["Distilled Reasoning"]
    C1["output/{slug}/principles_zh.json"]:::json
    C2["output/{slug}/principles_en.json"]:::json
    C3["output/{slug}/frameworks.zh.json"]:::json
    C4["output/{slug}/frameworks.en.json"]:::json
  end

  subgraph D["Skill Deliverable"]
    D1["output/{slug}/SKILL.zh.md\nintermediate"]:::draft
    D2["output/{slug}/SKILL.en.md\nintermediate"]:::draft
    D3["output/{slug}/SKILL.md\nsingle installable file"]:::skill
    D4["gallery/{slug}/SKILL.md\npublished copy"]:::skill
    D5["~/.claude/skills/{slug}-wisdom/\ninstalled skill"]:::install
  end

  A1 --> B1
  A1 --> B2
  A1 --> B3
  A2 --> C3
  A2 --> C4
  A3 --> D1
  A3 --> D2
  B1 --> C1
  B2 --> C1
  B3 --> C2
  B4 --> C3
  C1 --> C3
  C2 --> C4
  C3 --> D1
  C4 --> D2
  D1 --> D3
  D2 --> D3
  D3 --> D4 --> D5

  classDef data fill:#EEF4F8,stroke:#7B98AA,color:#17212B;
  classDef json fill:#F7F2E8,stroke:#B59B69,color:#221A10;
  classDef draft fill:#F5F5F5,stroke:#A0A0A0,color:#222222;
  classDef skill fill:#EAF6EF,stroke:#6B9B7E,color:#102618,stroke-width:1.4px;
  classDef install fill:#EFEAFA,stroke:#8A74C9,color:#1D1733,stroke-width:1.4px;
```

平台约束决定了最后一步的形态：无论中间是否生成独立中文稿和英文稿，Codex/Claude skill discovery 只认目录里的 `SKILL.md`。因此最终发布物必须是一个双语合并文件，并用 `## English` / `## 中文版` 让模型按用户语言自动选区。

## 3. Stage Anatomy

```mermaid
flowchart LR
  subgraph S1["Stage 1 · Source Collection"]
    S1a["source-collector\n用户材料清点"]:::worker
    S1b["web-searcher\n补充公开资料"]:::worker
    S1c["bibliography-analyst\n书目与版本"]:::worker
    S1d["coverage-mapper\n覆盖度报告"]:::worker
  end

  subgraph S2["Stage 2 · Principle Extraction"]
    S2a["principle-extractor zh\n中文认知框架"]:::worker
    S2b["principle-extractor en\nEnglish cognitive frame"]:::worker
  end

  subgraph S3["Stage 3 · Framework Synthesis"]
    S3a["source trace\nprinciple -> evidence"]:::core
    S3b["filter-chain decisions\nyes/no gates only"]:::core
    S3c["8D Expression DNA\nsentence · rhetoric · tone · certainty\nhumor · taboos · rhythm · markers"]:::core
    S3d["values / anti-patterns / tensions"]:::core
  end

  subgraph S4["Stage 4 · Skill Assembly"]
    S4a["first-person immersion"]:::core
    S4b["anti-formula response strategy"]:::core
    S4c["known blind spots + mitigation"]:::core
    S4d["single bilingual SKILL.md"]:::core
  end

  S1a --> S2a
  S1b --> S2a
  S1c --> S2b
  S1d --> S2b
  S2a --> S3a
  S2b --> S3a
  S3a --> S3b --> S3c --> S3d --> S4a --> S4b --> S4c --> S4d

  classDef worker fill:#F1F4F7,stroke:#7A8A99,color:#111820;
  classDef core fill:#F7F3EA,stroke:#B09663,color:#211A10;
```

这里最容易误解的是“人物思想蒸馏”不是做文风模仿。真正的核心产物是可执行决策算法：每条原则有证据锚点，每个框架是过滤链，每个表达规则都服务于运行时可用性，而不是装饰性的角色扮演。

## 4. Quality Gates

```mermaid
flowchart TB
  G0["validate_output.py sources <slug>\nraw materials + processed source map"]:::gate
  G1["validate_output.py principles <slug>\nsource-traced principles"]:::gate
  G2["validate_output.py frameworks <slug>\nindependent zh/en frameworks"]:::gate
  G3["validate_output.py skill <slug>\ninstallable bilingual SKILL.md"]:::gate
  G4["validate_output.py gallery <slug>\npublished copy matches output"]:::gate

  Q1["source confidence rules\nweb-only quote <= medium"]:::rule
  Q2["three-tier uniqueness test\nde-name · evidence · methodology"]:::rule
  Q3["decision framework shape\nyes/no filter chain"]:::rule
  Q4["anti-formula v4\nnatural structure + 8D voice"]:::rule
  Q5["blind spots\nmust include mitigation"]:::rule

  G0 --> G1 --> G2 --> G3 --> G4
  Q1 --> G1
  Q2 --> G1
  Q3 --> G2
  Q4 --> G3
  Q5 --> G3

  classDef gate fill:#FFF7E8,stroke:#BE8A2F,color:#24180A,stroke-width:1.4px;
  classDef rule fill:#F4F6F8,stroke:#8B98A5,color:#17202A;
```

这些门不是形式检查。它们分别守住四件事：来源可信、方法不泛化、输出能被 skill loader 发现、发布目录与开发产物一致。

## 5. Runtime Tuning Loop

```mermaid
flowchart LR
  T0["conversation tests\nlatest dialogue logs"]:::test
  T1["defect marking\nwhere output feels mechanical"]:::review
  T2["priority classify\nP0 identity · P1 structure · P2 nuance"]:::review
  T3["weak clause locator\nwhich rule failed to activate"]:::review
  T4["precise patch\nminimal edit to SKILL.md"]:::patch
  T5["re-test\nsame prompt + nearby prompt"]:::test
  T6["template backflow\nonly if defect repeats across thinkers"]:::patch

  T0 --> T1 --> T2 --> T3 --> T4 --> T5
  T5 -- "fixed" --> T6
  T5 -- "still weak" --> T3
  T6 --> T0

  classDef test fill:#EAF4F7,stroke:#6F97A8,color:#11232B;
  classDef review fill:#F7F3EA,stroke:#AA9368,color:#221A10;
  classDef patch fill:#EAF6EF,stroke:#6E9B7F,color:#102618;
```

运行期调优是本项目相对成熟的一步：它把“感觉不像、太列表化、太长、引用重复、行动建议单薄”这类主观问题，转化为可定位的规则补丁，而不是继续堆更多抽象原则。

## 6. Current Release Snapshot

| Area                   | Current reading                                                                                                        |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Core pipeline          | 已形成从 `sources/` 到 `output/` 再到 `gallery/` 的完整流水线。                                                                      |
| Skill format           | 当前标准已经收敛到单一 `SKILL.md`，内含英文与中文两套运行规则。                                                                                  |
| Anti-formula v4        | 项目级规则已经要求 8 维 Expression DNA、结构自然性、价值取向与反模式。                                                                           |
| Post-review tuning     | `config/post-review-tuning-guide.md` 已补上运行期对话测试后的精修闭环。                                                                 |
| Mao release gate       | `mao-zedong` 的 sources / principles / frameworks / skill / gallery 五个校验阶段均通过；`output/` 与 `gallery/` 的 `SKILL.md` 哈希一致。 |
| Charlie audit gap      | `charlie-munger` 作为 hand-crafted gallery 基准仍存在，但当前没有对应的 `output/charlie-munger/SKILL.md`，因此无法用同一 gallery 校验链复现。        |
| Install target wording | 项目命令文档使用 `~/.claude/skills/`，当前 Codex 环境强调 `SKILL.md` 发现约束；跨环境演示时应把不变量表述为“local skills directory + exact `SKILL.md`”。  |

## 7. Demo Narrative

演示时可以按三句话讲完整个项目：

1. 先把人物材料变成证据网络，不急着写 Skill。
2. 再把证据网络压缩成双语独立认知框架，并强制每个决策框架变成 yes/no 过滤链。
3. 最后把框架装配成单一 `SKILL.md`，通过质量闸门、gallery 同步、真实对话测试，持续把“像一个报告”调成“像一种可执行的思考方式”。

## 8. Final Workflow Board

```mermaid
flowchart LR
  P["Raw Sources"]:::a --> E["Evidence"]:::b --> R["Reasoning"]:::c --> K["Skill"]:::d --> V["Validation"]:::e --> L["Live Dialogue"]:::f
  L -- "observed defects" --> K
  V -- "sync failure" --> K

  P1["books\nspeeches\nletters\nnotes"]:::a --> P
  E1["source ids\nconfidence\ncoverage"]:::b --> E
  R1["principles\nfilter chains\nblind spots"]:::c --> R
  K1["first-person voice\n8D expression DNA\nbilingual SKILL.md"]:::d --> K
  V1["schema\nquality gates\ngallery hash"]:::e --> V
  L1["test prompts\nruntime behavior\npatch loop"]:::f --> L

  classDef a fill:#F5F5F2,stroke:#8D8A80,color:#1D1C18;
  classDef b fill:#EEF4F8,stroke:#7798AA,color:#16232B;
  classDef c fill:#F7F2E8,stroke:#AD9463,color:#211A10;
  classDef d fill:#EAF6EF,stroke:#6E9B7F,color:#102618;
  classDef e fill:#FFF7E8,stroke:#BE8A2F,color:#24180A;
  classDef f fill:#EFEAFA,stroke:#8A74C9,color:#1D1733;
```
