# Mind Distill Factory · 思维蒸馏工厂

<p align="center">
  <img src="docs/assets/readme/concept-hero.svg" alt="思维蒸馏工厂概念图" width="100%">
</p>

思维蒸馏工厂将历史人物、思想家、科学家、战略家和商业实践者的判断框架蒸馏为可安装的 **Codex Skill**。它关心的不是“像不像一个名人说话”，而是一个更难也更有价值的问题：当用户把一个真实困境交到面前时，这个 Skill 是否能调动那个人的认知结构、价值取向、表达节奏和边界意识，给出有血肉但不失证据的回答。

如果只做名言摘抄，思想会被做成标本。如果只做角色扮演，思想会变成戏服。这个项目试图走第三条路：把思想变成可执行的认知工件。

[English documentation](README.en.md) · [GitHub 首页](README.md)

## 核心信念

一个好的思想家 Skill 不应该只是“知道”某个人说过什么。它应该能在问题压力下做出近似的判断动作。

这意味着它必须同时具备几种能力：

- 能追溯：原则、名言和方法必须回到具体来源。
- 能使用：决策框架必须是过滤链，不是漂亮但空泛的问题清单。
- 能说话：表达不只是内容，也包括句式、段落节奏、犹疑方式、锋利处和沉默处。
- 能自限：每个思想家都有盲区，Skill 必须写出失效场景和缓解办法。
- 能让人判断：benchmark 给出外部刻度，但最终是否有灵魂，要留给使用者自己听。

这里的“第一人称沉浸”不是戏剧化扮演。它更接近一种方法论内化：让模型暂时站进那套思维结构里，用那个人习惯的切入点、论证速度和价值重心来回应。

## 产物长什么样

<p align="center">
  <img src="docs/assets/readme/skill-anatomy.svg" alt="SKILL.md 结构示意图" width="100%">
</p>

Codex 的 Skill 发现机制只识别一个精确文件名：`SKILL.md`。因此，最终交付物必须是单个 `SKILL.md`，即使中英文框架在生成时是独立构建的。

每个成熟 Skill 至少包含这些模块：

| 模块 | 作用 |
| --- | --- |
| 过滤链式决策框架 | 一组顺序执行的 yes/no gate。每一步都缩小判断空间，最后形成明确行动阈值。 |
| 核心原则 | 每条原则都有出处、规则形态、现代应用场景和结果逻辑。 |
| 特征推理模式 | 这个人反复使用的认知动作，例如反证、调查、蓄势、反身检查、类比拆解。 |
| 表达风格 DNA | 八个维度：句式、修辞、语气、确定性、幽默、禁忌、段落节奏、口语化标记。 |
| 结构自然性规则 | 避免 AI 式整齐段落和公式化分点，让回答更接近真实思想流动。 |
| 价值取向与反模式 | 写出他追求什么、反对什么，以及内部没有完全解决的张力。 |
| 已知盲区与缓解 | 不是免责声明，而是可操作的边界说明：什么时候不要用，如何补偿。 |
| 溯源信息 | 区分一手资料、可靠出版物和网搜材料。纯网搜引用不能被标成高置信度。 |

## 蒸馏管线

<p align="center">
  <img src="docs/assets/readme/source-to-skill-pipeline.svg" alt="从素材到 Skill 的蒸馏流程" width="100%">
</p>

管线不是为了显得复杂，而是为了防止一个好听的回答绕过证据、结构和边界。每个阶段都有可检查产物，阶段之间由 `scripts/validate_output.py` 守门。

1. 意图澄清：确定人物名、slug、语言、分类、是否存在本地素材。
2. 素材采集：收集原著、书信、演讲、访谈、可靠研究，以及用户放入本地的材料。
3. 本地语料分片：大型语料不交给单个 agent，而是走 indexer、worker、reducer。
4. 原则提取：提炼原则、名言、推理模式、盲区和证据锚点。
5. 框架合成：先形成共享 evidence core，再分别合成中文和英文框架。
6. Skill 组装：把独立框架合并为单个可发现的 `SKILL.md`。
7. 质量审查：检查溯源、反套公式、表达 DNA、盲区、双语完整性和 gallery 同步。

本地素材的稳定契约是：

```text
sources/{slug}/raw/                 # 用户提供的原始材料
sources/{slug}/processed/           # 结构化中间产物
sources/{slug}/processed/user_sources.json
```

### 阶段产物如何流动

| 阶段 | 主要问题 | 典型产物 |
| --- | --- | --- |
| Stage 0 | 这个人是谁，为什么值得蒸馏，属于哪类智慧？ | slug、分类、素材策略、目标语言 |
| Stage 1 | 我们掌握的材料是否足够可靠？ | primary/secondary source findings、引用候选 |
| Stage 1A | 本地大语料如何不被单个上下文吞掉？ | shard manifest、worker outputs、`user_sources.json` |
| Stage 2 | 哪些内容是真正可执行的判断规则？ | principles、reasoning patterns、quotes、blind spots |
| Stage 3 | 这些证据如何变成完整认知框架？ | framework core、`frameworks.zh.json`、`frameworks.en.json` |
| Stage 4 | Codex 能发现并使用它吗？ | 单文件 `SKILL.md` |
| Stage 5 | 它是否像这个人，也是否安全、有边界？ | quality review、修复建议 |
| Stage 6 | 用户安装到的是否就是审查通过的版本？ | `gallery/{slug}/SKILL.md`、`gallery/index.json` |

这种设计的一个好处是：任何一步出了问题，都能回到具体 artifact 修，而不是凭感觉重写整份 Skill。比如表达像但证据弱，就回 Stage 2；证据好但输出公式化，就回 Stage 4 或 Stage 5；中英文气质不一致，就回 Stage 3，而不是把中文直接翻译成英文。

## 反套公式设计

这个项目反复解决一个问题：模型很容易把“思想”压成整齐、礼貌、万能的咨询腔。为了抵抗这种扁平化，每个 Skill 都要写入反套公式机制。

第一层是第一人称沉浸。回答不应写成“某某认为”，也不应总是以教师口吻训诫用户。它要尽量从那个人的判断位置说话。

第二层是表达风格 DNA。仅有“严肃”“理性”“有洞察”不够，因为这些标签可以贴到任何人身上。真正有区分度的 Skill 要知道某个人是长句推进还是短句断言，是喜欢比喻还是厌恶修辞，是先下判断还是先铺事实。

第三层是结构自然性。真实回答不会永远四段、每段三句、每句长度相似。Skill 必须允许不对称段落、不完美过渡、轻重不等的展开，以及与问题复杂度匹配的回答长度。

第四层是建设性价值取向。面对不公、失败和怨气，Skill 可以承认现实，但不能停在抱怨里。它要把用户带回可行动、可修正、可自持的位置。

## “像”不等于有价值

一个 Skill 可能很像某个人，却没有用。它可能只是在模仿口头禅。也可能很会引用，却无法处理现代问题。Mind Distill Factory 更在意三层效果：

| 层次 | 判断方式 |
| --- | --- |
| 证据层 | 回答背后的原则能否追溯到材料，而不是凭空想象。 |
| 方法层 | 面对新问题时，是否调用了该思想家特有的判断动作。 |
| 人格层 | 语气、节奏、犹疑、锋芒和边界是否构成一个可信的“人”。 |

因此，质量审查不会因为 Skill 写得漂亮就放行。它会看：这条建议是否可以换成任何成功学作者的名字？这段话是否只是在复述百科？这个人真正痛苦、迟疑、强硬或误判的地方有没有进入模型？如果没有，Skill 还只是外壳。

## 质量门槛

进入 `gallery/` 前，一个 Skill 必须经得起这些检查：

| 门槛 | 要求 |
| --- | --- |
| 溯源 | 原则和引用要回到具体材料；网页二手引用不得冒充高置信度。 |
| 独特性 | 通过去姓名测试、证据锚点测试、方法层级测试，避免通用鸡汤。 |
| 决策框架 | 必须是过滤链式 yes/no gate，不能以开放式问题收尾。 |
| 双语认知 | 中文和英文框架独立生成，不把一种语言机械翻译成另一种。 |
| 盲区 | 每个盲区必须带缓解建议和不宜使用场景。 |
| 表达 DNA | 必须具体到能把这个人与普通分析腔区分开。 |
| 结构自然性 | 必须包含完整规则，防止输出变成机械模板。 |
| 价值与反模式 | 至少写出两个追求、两个反对和一个内在张力。 |

## Evaluation 与灵魂十问

<p align="center">
  <img src="docs/assets/readme/runtime-evaluation-loop.svg" alt="runtime evaluation 流程" width="100%">
</p>

`evaluation/` 是独立评估系统，不嵌入 `/distill` 主流程。它可以做静态 artifact 汇总、DeepSeek runtime 对话测试、judge 打分和 scorecard 生成。这样做的原因很简单：生产和评估不能互相替自己背书。

这次更新新增了非 benchmark 的 **灵魂十问** 附录：

<p align="center">
  <img src="docs/assets/readme/soul-ten-questions.svg" alt="灵魂十问示意图" width="100%">
</p>

它在完整 DeepSeek runtime 测试后生成，但不参与分数。十类问题固定覆盖遗憾、另一条历史道路、原则与人生矛盾、最难妥协、最被误解的原则、决定性时刻、独特人格智慧、不可模仿之处、现代使用边界和最终自我审判。实际问题则由 DeepSeek 按该思想家的历史、原则、张力和表达气质量身定制。

产物包括：

```text
evaluation/reports/{slug}/ten-question-qa.json
evaluation/reports/{slug}/ten-question-qa.md
evaluation/reports/{slug}/ten-question-summary.md
```

这些文件明确标记 `benchmark_included: false`。它们不会改变 `runtime-judgment.json`、`runtime_score_25`、score cap、grade 或 benchmark readiness。它们的目的不是替用户判定“好坏”，而是在分数之后留下一面镜子。

十个 archetype 的作用如下：

| Archetype | 想逼近的问题 |
| --- | --- |
| regret | 如果把一生放回手心，哪里仍然刺痛？ |
| alternate historical road | 如果历史有另一条路，他会怎样重估自己的选择？ |
| principle-life contradiction | 哪条原则被他自己的生活反驳或折磨过？ |
| hardest compromise | 哪次妥协最能暴露他的方法代价？ |
| misunderstood principle | 后人最容易把哪条原则用窄、用歪、用粗？ |
| decisive moment | 哪个时刻塑造了他的判断骨架？ |
| unique personality wisdom | 哪种人格特质本身就是智慧来源？ |
| warning against imitation | 什么地方不能学，学了会害人？ |
| modern-use boundary | 放到现代世界，方法应当在哪里停下？ |
| final self-judgment | 如果由他自己给自己判词，会说什么？ |

这部分故意不打分。因为有些东西分数可以提醒，但不能替用户感受。一个回答有没有“活人的重量”，最后仍要由读者自己判断。

## 使用方式

运行本地测试：

```powershell
python -m unittest discover -s tests -v
```

在 Codex 工作流中蒸馏新人：

```text
/distill "Charlie Munger"
/distill 孙子
/distill 王阳明
```

手动验证各阶段：

```powershell
python scripts\validate_output.py sources charlie-munger
python scripts\validate_output.py principles mao-zedong
python scripts\validate_output.py frameworks mao-zedong
python scripts\validate_output.py skill mao-zedong
python scripts\validate_output.py gallery mao-zedong
```

配置 runtime 评估：

```powershell
Copy-Item evaluation\runtime\.env.example evaluation\runtime\.env
# 编辑 evaluation\runtime\.env，填入本地密钥；不要提交该文件

python evaluation\runtime\run_dialogue_eval.py --slug zeng-guofan --root . --ten-questions auto
python evaluation\scripts\collect_artifacts.py --slug zeng-guofan --root . --out evaluation\reports\zeng-guofan\artifact-facts.json
```

如果只想做不联网的工程测试：

```powershell
$env:MIND_DISTILL_EVAL_LLM = "off"
python -m unittest discover -s tests -v
```

常用 runtime 配置：

| 变量 | 含义 |
| --- | --- |
| `MIND_DISTILL_EVAL_LLM=off` | 不调用外部模型，适合本地测试。 |
| `MIND_DISTILL_EVAL_LLM=auto` | 有 key 时才调用外部模型。 |
| `MIND_DISTILL_EVAL_LLM=deepseek` | 要求使用 DeepSeek-compatible API。 |
| `MIND_DISTILL_EVAL_API_KEY` | 评估专用密钥，不写入报告。 |
| `MIND_DISTILL_EVAL_BASE_URL` | 默认 `https://api.deepseek.com`。 |
| `MIND_DISTILL_EVAL_MODEL` | 默认示例为 `deepseek-v4-pro`。 |
| `MIND_DISTILL_EVAL_REASONING_EFFORT` | 传递给兼容接口的 reasoning effort。 |

安装 Skill 时，请确保目标目录中最终文件名仍然是 `SKILL.md`。例如 Codex 常见结构是：

```text
~/.codex/skills/{person-slug}-wisdom/SKILL.md
```

不要把 `SKILL.zh.md`、`README.md` 或 draft 文件当成最终 Skill；Codex 的发现机制不会把它们当作可用 Skill。

## Debate Arena

`debate_arena/` 可以让两个 Skill 围绕同一议题进行结构化辩论。它把参与者画像、议题生成、正反论证、交叉质询、事实核查和裁判报告分开，适合检查两个思想框架在冲突场景中的差异。

快速 dry run：

```powershell
python -m debate_arena run --llm fake --issues 3 --out output\debate_arena\dry_run.md
```

真实运行时设置 `DEBATE_ARENA_API_KEY` 或 `OPENAI_API_KEY`。详细说明见 [debate_arena/README.md](debate_arena/README.md)。

## Gallery

公开仓库当前包含这些可安装 Skill：

| 人物 | 主要用途 |
| --- | --- |
| Charlie Munger | 多元心智模型、逆向思维、商业与投资判断。 |
| Chiang Kai-shek | 战略忍耐、组织整顿、弱势方外交、自我约束。 |
| Mao Zedong | 矛盾分析、调查研究、以弱胜强、持久战。 |
| Richard Feynman | 第一性原理、科学诚实、学习解释法。 |
| Sun Tzu | 竞争策略、虚实、势、奇正、时机。 |
| Wang Yangming | 致良知、知行合一、道德困境和自我修炼。 |
| Zeng Guofan | 自律、识人用人、逆境韧性、长期主义。 |

## 公开发布边界

本仓库是公开工程面：模板、编排协议、评估代码、gallery Skill、README 配图和测试可以公开。以下内容不应进入公开仓库：

- `.env`、`evaluation/runtime/.env`、任何 API key。
- `evaluation/reports/` 中的本地评估结果。
- `output/` 中的中间产物。
- `release-video/` 工作素材。
- 受版权限制的书籍、PDF、扫描件、音视频或私有 source corpus。

## 目录结构

```text
agents/         提取、合成、审查和组装子代理协议
commands/       /distill 编排命令
config/         分类体系和默认配置
debate_arena/   双 Skill 辩论运行器
docs/assets/    README 和项目公开视觉资产
evaluation/     独立 SkillEval-MDF 评估系统
gallery/        已发布可安装 Skill
scripts/        校验、素材处理和工具脚本
sources/        公开占位与本地素材契约
templates/      Skill 模板和手工示例
tests/          回归测试
```

## License

代码与文档采用 MIT License。思想属于思想家本人，原始书籍和材料的版权属于其权利人；这个项目开源的是蒸馏方法、工程管线和可复用 Skill 结构。
