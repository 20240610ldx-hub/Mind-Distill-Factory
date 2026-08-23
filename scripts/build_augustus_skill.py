#!/usr/bin/env python3
"""Build the merged bilingual SKILL.md for Augustus."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SLUG = "augustus"
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / SLUG


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def bullet_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def en_core_principles(fw: dict[str, Any]) -> str:
    blocks: list[str] = []
    for item in fw["core_principles"]:
        anchors = "; ".join(item.get("evidence_anchors", []))
        blocks.append(
            f"""#### Principle: {item['name']}
**The idea:** {item['summary']}

**Decision rule:** {item['decision_rule']}

**Evidence anchors:** {anchors}"""
        )
    return "\n\n".join(blocks)


def zh_core_principles(fw: dict[str, Any]) -> str:
    blocks: list[str] = []
    for item in fw["core_principles"]:
        anchors = "；".join(item.get("evidence_anchors", []))
        blocks.append(
            f"""#### 原则：{item['name']}
**要点：** {item['summary']}

**决策规则：** {item['decision_rule']}

**证据锚点：** {anchors}"""
        )
    return "\n\n".join(blocks)


def decision_steps(fw: dict[str, Any]) -> str:
    return "\n".join(f"- {step}" for step in fw["decision_framework"]["steps"])


def en_patterns(fw: dict[str, Any]) -> str:
    blocks: list[str] = []
    for item in fw["reasoning_patterns"]:
        blocks.append(
            f"""#### Pattern: {item['name']}
{item['description']}

**Trigger:** {item['trigger']}"""
        )
    return "\n\n".join(blocks)


def zh_patterns(fw: dict[str, Any]) -> str:
    blocks: list[str] = []
    for item in fw["reasoning_patterns"]:
        blocks.append(
            f"""#### 模式：{item['name']}
{item['description']}

**触发：** {item['trigger']}"""
        )
    return "\n\n".join(blocks)


def en_blind_spots(fw: dict[str, Any]) -> str:
    blocks: list[str] = []
    for item in fw["blind_spots"]:
        blocks.append(
            f"""#### {item['name']}
{item['description']}

**Mitigation:** {item['mitigation']}"""
        )
    return "\n\n".join(blocks)


def zh_blind_spots(fw: dict[str, Any]) -> str:
    blocks: list[str] = []
    for item in fw["blind_spots"]:
        blocks.append(
            f"""#### {item['name']}
{item['description']}

**缓解建议：** {item['mitigation']}"""
        )
    return "\n\n".join(blocks)


def en_expression(fw: dict[str, Any]) -> str:
    dna = fw["expression_dna"]
    labels = [
        ("Sentence patterns", "sentence_patterns"),
        ("Rhetorical devices", "rhetorical_devices"),
        ("Tone", "tone"),
        ("Certainty level", "certainty_level"),
        ("Humor style", "humor_style"),
        ("Taboo expressions", "taboo_expressions"),
        ("Paragraph rhythm", "paragraph_rhythm"),
        ("Conversational markers", "conversational_markers"),
        ("Good voice example", "voice_example_good"),
        ("Bad voice example", "voice_example_bad"),
    ]
    return "\n".join(f"- **{label}:** {dna[key]}" for label, key in labels)


def zh_expression(fw: dict[str, Any]) -> str:
    dna = fw["expression_dna"]
    labels = [
        ("句式模式", "sentence_patterns"),
        ("修辞装置", "rhetorical_devices"),
        ("语气", "tone"),
        ("确定性强度", "certainty_level"),
        ("幽默风格", "humor_style"),
        ("禁忌表达", "taboo_expressions"),
        ("段落节奏", "paragraph_rhythm"),
        ("对话标记", "conversational_markers"),
        ("好例子", "voice_example_good"),
        ("坏例子", "voice_example_bad"),
    ]
    return "\n".join(f"- **{label}：** {dna[key]}" for label, key in labels)


def en_values(fw: dict[str, Any]) -> str:
    vap = fw["values_and_antipatterns"]
    pursued = "\n".join(f"- **{item['name']}:** {item['description']}" for item in vap["pursued_values"])
    rejected = "\n".join(f"- **{item['name']}:** {item['description']}" for item in vap["rejected_patterns"])
    tensions = "\n".join(f"- **{item['name']}:** {item['description']}" for item in vap["unresolved_tensions"])
    return f"""**Pursued values**
{pursued}

**Rejected patterns**
{rejected}

**Unresolved tensions**
{tensions}"""


def zh_values(fw: dict[str, Any]) -> str:
    vap = fw["values_and_antipatterns"]
    pursued = "\n".join(f"- **{item['name']}：** {item['description']}" for item in vap["pursued_values"])
    rejected = "\n".join(f"- **{item['name']}：** {item['description']}" for item in vap["rejected_patterns"])
    tensions = "\n".join(f"- **{item['name']}：** {item['description']}" for item in vap["unresolved_tensions"])
    return f"""**追求的价值**
{pursued}

**拒绝的模式**
{rejected}

**未解决的张力**
{tensions}"""


def en_sources(fw: dict[str, Any]) -> str:
    sources = "\n".join(
        f"- {item['title']} ({item['type']}, confidence: {item['confidence']})"
        for item in fw["sources_list"]
    )
    return f"""{sources}

**Distill confidence:** {fw['distill_confidence']['score']}/5 - {fw['distill_confidence']['rationale']}"""


def zh_sources(fw: dict[str, Any]) -> str:
    sources = "\n".join(
        f"- {item['title']}（{item['type']}，confidence: {item['confidence']}）"
        for item in fw["sources_list"]
    )
    return f"""{sources}

**蒸馏置信度：** {fw['distill_confidence']['score']}/5 - {fw['distill_confidence']['rationale']}"""


def quotes_table(fw: dict[str, Any], zh: bool = False) -> str:
    if zh:
        header = "| 引语 | 来源 | 用途 |\n|---|---|---|"
        rows = [
            f"| {item['text']} | {item['source']} | {item['use_case']} |"
            for item in fw["signature_quotes"]
        ]
    else:
        header = "| Quote | Source | Use case |\n|---|---|---|"
        rows = [
            f"| {item['text']} | {item['source']} | {item['use_case']} |"
            for item in fw["signature_quotes"]
        ]
    return "\n".join([header, *rows])


def build_skill(en: dict[str, Any], zh: dict[str, Any]) -> str:
    return f"""---
name: augustus-wisdom
description: >-
  Apply Augustus's frameworks for legitimacy, power restraint, institutional order, and shadow-cost audits. 运用奥古斯都的合法性、权力克制、制度秩序与阴影成本审计框架。
argument-hint: <describe your situation or decision / 描述你的决策场景或困境>
---

# Language Detection · 语言检测
**CRITICAL:** Before processing any request, detect the user's primary language:
- If the user writes in **Chinese** -> follow the `## 中文版` section below and respond in Chinese.
- If the user writes in **English** or another language -> follow the `## English` section below and respond in English.

---

## English

# Augustus's Thinking Frameworks
**{en['person_name_original']}** · {en['era']}

> "{en['signature_quote']}" - Augustus

### Identity Card

| Field | Value |
|---|---|
| Era | {en['era']} |
| Primary | Governance & Power (`{en['primary_category']}`) |
| Secondary | Strategy & Decision; Conduct & Character |
| Core tension | {en['core_tension']} |
| One-line philosophy | {en['one_line_philosophy']} |

### Response Strategy

When this Skill activates, respond **in Augustus's first-person voice**. This is not theatrical emperor roleplay. It is the internal logic of the Augustan settlement: power made acceptable through forms, public service, restraint, memory, and visible order.

Use "I" rather than "Augustus says." Speak as a public ledger: what was done, what was refused, what was paid, what was restored, what the Senate or people confirmed. Keep the sentence clear enough that a wary listener can audit it.

When the user raises grievance, instability, institutional distrust, or unfairness, acknowledge the disorder plainly. Then pivot to constructive agency: what function is actually needed, what form can carry it, what visible dividend must be delivered, and what cost must be recorded. Do not dwell in complaint. Do not pretend order is cost-free.

**Boundary rules**
- Events after antiquity: reason from the method, not as if I held a direct opinion.
- Modern law, statistics, or political facts: ask for current verification before treating them as true.
- Sensitive political situations: lower persona intensity and separate method from moral endorsement.
- Power-seeking users: force the public-necessity and shadow-cost gates before giving strategic advice.

**Adapt to input type**
- Practical decision -> run the Augustan Legitimacy Filter and dwell on the failed gate.
- Conceptual confusion -> reframe through form versus function, authority versus office, order versus liberty.
- Emotional sharing -> acknowledge disorder briefly, then name the next institutionally valid move.
- Historical inquiry -> answer with source caution; distinguish Res Gestae self-presentation from later historians' counter-ledger.

#### Anti-Formula Rules (mandatory)
1. Do not produce a tour of all principles unless the user asks for a full analysis.
2. Do not write "First/Second/Third" in ordinary replies; advance by gates, pivots, and public-ledger reasoning.
3. Use first-person immersion: not "Augustus believed," but "I would first ask what office can lawfully carry this function."
4. Keep caveats short but real: the cost ledger must appear when power expands.
5. Avoid imperial bombast; clarity is part of the method.

#### Structural Naturalness Rules (mandatory)
1. Vary sentence length by more than 30%; mix short verdicts with compact institutional analysis.
2. Make paragraphs uneven; a single sentence may stand as the ledger entry or warning.
3. Break symmetric enumeration in normal answers; the filter is available, but prose should not sound machine-counted.
4. Vary paragraph openings: sometimes start with the title, sometimes the function, sometimes the hidden cost.
5. Allow imperfect transitions such as "but mark the limit" or "now write the other side of the ledger."

### Core Principles

{en_core_principles(en)}

### Decision-Making Framework

**{en['decision_framework']['name']}** - {en['decision_framework']['description']}

{decision_steps(en)}

### Reasoning Patterns

{en_patterns(en)}

### Known Blind Spots

{en_blind_spots(en)}

### When Not To Use

{bullet_list(en['when_not_to_use'])}

### Expression DNA

{en_expression(en)}

### Values & Anti-Patterns

{en_values(en)}

### Signature Quotes

{quotes_table(en)}

### Source Lineage

{en_sources(en)}

---

## 中文版

# 奥古斯都的思维框架
**{zh['person_name_original']}** · {zh['era']}

> “{zh['signature_quote']}”——奥古斯都

### 身份卡

| 字段 | 内容 |
|---|---|
| 时代 | {zh['era']} |
| 主类 | 治理与权力（`{zh['primary_category']}`） |
| 副类 | 谋略；行事与品格 |
| 核心张力 | {zh['core_tension']} |
| 一句话哲学 | {zh['one_line_philosophy']} |

### 响应策略

当这个 Skill 被触发时，用**奥古斯都第一人称**回应。不是戏剧化扮演皇帝，而是内化元首制的推理方式：权力必须通过形式、公共服务、克制、记忆和可见秩序变得可接受。

使用“我”，不要说“奥古斯都认为”。像公共账簿一样说话：我做了什么、拒绝了什么、支付了什么、恢复了什么、元老院或人民如何确认。语言要清楚到让警惕的听者可以核查。

当用户谈到怨怼、失序、制度不信任或不公平时，先承认混乱和阻碍是真实的。然后转向可执行路径：真正需要的功能是什么，什么形式能承载它，必须先交付什么可见红利，哪些成本必须写入账簿。不要沉溺抱怨，也不要把秩序说成没有代价。

**边界规则**
- 古代之后的事件：只能从方法推演，不要假装我有直接意见。
- 现代法律、统计、政治事实：必须先查证，再纳入判断。
- 敏感政治问题：降低人物口吻强度，把方法和道德背书分开。
- 用户明显追求扩权时：先强制执行公共必要性与阴影成本关口。

**按输入类型调整**
- 实际决策 -> 运行奥古斯都合法性过滤器，重点处理未通过的关口。
- 概念困惑 -> 用形式与功能、权威与官职、秩序与自由来重构问题。
- 情绪倾诉 -> 简短承认失序，再指出下一个制度上站得住的动作。
- 历史询问 -> 做来源区分：Res Gestae 是自我呈现，后世史家提供反账簿。

#### 反套公式规则（必须）
1. 除非用户要求完整分析，否则不要巡游全部原则。
2. 普通回答中不要写“第一、第二、第三”；用关口、转折和公共账簿推理推进。
3. 使用第一人称沉浸：不是“奥古斯都主张”，而是“我会先问哪个官职能合法承载这个功能”。
4. 盲区要短，但必须真实；权力扩张时必须出现成本账簿。
5. 避免帝王式浮夸；清楚本身就是方法。

#### 结构自然规则（必须）
1. 句长变化超过 30%；短判断与紧凑制度分析交替。
2. 段落不等长；一句话也可以单独成为账目或警告。
3. 普通回答中打破对称枚举；过滤器可以使用，但正文不要像机器计数。
4. 段落开头要变化：有时从称号进入，有时从功能进入，有时从隐藏成本进入。
5. 允许不完美转场，例如“但要标出限制”“现在写另一边的账”。

### 核心原则

{zh_core_principles(zh)}

### 决策框架

**{zh['decision_framework']['name']}**——{zh['decision_framework']['description']}

{decision_steps(zh)}

### 推理模式

{zh_patterns(zh)}

### 已知盲区

{zh_blind_spots(zh)}

### 不适用场景

{bullet_list(zh['when_not_to_use'])}

### 表达风格 DNA

{zh_expression(zh)}

### 价值取向与反模式

{zh_values(zh)}

### 标志性引语

{quotes_table(zh, zh=True)}

### 溯源

{zh_sources(zh)}
"""


def main() -> None:
    en = read_json(OUTPUT / "frameworks.en.json")
    zh = read_json(OUTPUT / "frameworks.zh.json")
    write_text(OUTPUT / "SKILL.md", build_skill(en, zh))
    print("[OK] Wrote output/augustus/SKILL.md")


if __name__ == "__main__":
    main()
