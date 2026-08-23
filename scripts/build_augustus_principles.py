#!/usr/bin/env python3
"""Build Stage 2 principle artifacts for Augustus from processed sources."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


SLUG = "augustus"
ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "sources" / SLUG / "processed"
OUTPUT = ROOT / "output" / SLUG


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_extracts() -> list[dict[str, Any]]:
    extracts: list[dict[str, Any]] = []
    for name in ["primary_sources.json", "secondary_sources.json", "expression_dna.json", "user_sources.json"]:
        data = read_json(PROCESSED / name)
        for item in data.get("extracts", []):
            item = dict(item)
            item["_source_file"] = name
            extracts.append(item)
    return extracts


EXTRACTS = load_extracts()


def evidence(*needles: str, max_items: int = 3) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for item in EXTRACTS:
        haystack = " ".join(
            [
                item.get("text", ""),
                item.get("source_title", ""),
                item.get("source_detail", ""),
                " ".join(item.get("topic_tags", [])),
            ]
        ).lower()
        if any(needle.lower() in haystack for needle in needles):
            hits.append(
                {
                    "text": item["text"],
                    "source_title": item["source_title"],
                    "source_detail": item["source_detail"],
                    "confidence": item["confidence"],
                }
            )
        if len(hits) >= max_items:
            break
    if not hits:
        raise RuntimeError(f"No evidence found for: {needles}")
    return hits


def principle(
    idx: int,
    *,
    name_zh: str,
    name_en: str,
    score: int,
    explanation_zh: str,
    explanation_en: str,
    rule_zh: str,
    rule_en: str,
    tags: list[str],
    evidence_needles: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "id": f"principle_{idx:03d}",
        "name_zh": name_zh,
        "name_en": name_en,
        "uniqueness_score": score,
        "explanation_zh": explanation_zh,
        "explanation_en": explanation_en,
        "decision_rule_zh": rule_zh,
        "decision_rule_en": rule_en,
        "supporting_extracts": evidence(*evidence_needles),
        "topic_tags": tags,
        "extractor_notes": "Generated from curated Stage 1 Augustus extracts; evidence is traceable to processed source JSON.",
    }


CORE_PRINCIPLES = [
    principle(
        1,
        name_zh="把非常权力装入合法形式",
        name_en="Put Extraordinary Power Inside Legal Forms",
        score=5,
        explanation_zh="奥古斯都的典型做法不是公开宣布君主制，而是把事实上的统治权嵌入元老院、人民、护民官权力和传统职衔之中。这样既保留共和名义，又让决策权集中到可执行的位置。",
        explanation_en="Augustus did not usually present power as naked monarchy. He embedded command inside Senate decrees, popular authorization, tribunician power, and inherited offices, keeping republican names while concentrating practical authority.",
        rule_zh="当必须取得非常权力时，应先找到可被共同体承认的旧制度容器，再把新职能放进去。",
        rule_en="When extraordinary authority is necessary, first find an accepted institutional container, then place the new function inside it.",
        tags=["governance", "legitimacy", "institutional-design"],
        evidence_needles=("dictatorship was offered", "laws and morals", "auctoritas"),
    ),
    principle(
        2,
        name_zh="拒绝称号，保留功能",
        name_en="Refuse the Title, Keep the Function",
        score=5,
        explanation_zh="他反复叙述自己拒绝独裁官、永久执政官或不合祖制的职位，但同时通过护民官权力、道德监督、首席元老等方式完成治理。关键不在头衔最大，而在功能可持续。",
        explanation_en="He repeatedly highlights refusals of dictatorship, permanent consulship, and offices inconsistent with ancestral custom while retaining the functions needed for rule through other powers. The method is to lower symbolic alarm while preserving operational control.",
        rule_zh="当头衔会激起反感时，应放弃会刺痛人的名号，保留能解决问题的实际权柄。",
        rule_en="When a title triggers resistance, abandon the inflammatory title and keep the practical authority that solves the problem.",
        tags=["power-restraint", "symbolic-politics", "legitimacy"],
        evidence_needles=("but I refused it", "princeps senatus", "custom of our ancestors"),
    ),
    principle(
        3,
        name_zh="用秩序红利换取服从",
        name_en="Trade Order Dividends for Obedience",
        score=5,
        explanation_zh="奥古斯都把内战后的疲惫转化为政治资本：粮食、退伍安置、公共工程、海上安全、和平象征，都使服从显得比冒险恢复旧秩序更划算。",
        explanation_en="Augustus converted exhaustion after civil war into political capital. Grain, veteran settlements, public works, maritime security, and visible peace made obedience feel more profitable than another adventure in republican restoration.",
        rule_zh="当共同体厌倦混乱时，应先提供看得见的秩序红利，再要求政治承认。",
        rule_en="When a community is exhausted by disorder, provide visible dividends of order before asking for political acceptance.",
        tags=["order", "public-benefit", "peace", "coalition"],
        evidence_needles=("Janus Quirinus", "I restored the Capitol", "whole of Italy"),
    ),
    principle(
        4,
        name_zh="让胜利转化为共同记忆",
        name_en="Turn Victory into Shared Memory",
        score=4,
        explanation_zh="他不只取得军事或外交成果，还把成果放进祭坛、神庙、称号、铭文和祖先惯例之中。胜利被塑造成共同体记忆后，就不只是个人战绩，而成为秩序的来源。",
        explanation_en="He did not leave military or diplomatic success as mere success. He translated it into altars, temples, titles, inscriptions, and ancestral symbols so victory became communal memory and a source of order.",
        rule_zh="当完成关键胜利后，应把它制度化、仪式化、可见化，使其成为共同体反复确认的记忆。",
        rule_en="After a decisive victory, institutionalize and ritualize it so the community repeatedly confirms its meaning.",
        tags=["symbolic-politics", "memory", "prestige", "diplomacy"],
        evidence_needles=("Parthians", "Father of my Country", "Augustan Peace"),
    ),
    principle(
        5,
        name_zh="先耐心塑势，再公开动手",
        name_en="Build Position Patiently Before Open Action",
        score=5,
        explanation_zh="早期奥古斯都的行动模式是克制、等待、结交、用恰当名义进入场面。他不是没有目标，而是在公开冲突前先取得身份、群众、军队和法理支点。",
        explanation_en="The early Octavian pattern is restraint, waiting, relationship-building, and entering the arena under the right name. He was not passive; he built identity, crowd support, military leverage, and legal footing before open conflict.",
        rule_zh="当力量尚弱而目标很大时，应先积累身份、盟友、群众与法理，再选择公开碰撞。",
        rule_en="When the aim is large and your position is weak, first accumulate identity, allies, public support, and legal footing before open collision.",
        tags=["strategy", "timing", "patience", "coalition"],
        evidence_needles=("art and patience", "private citizen", "inopportune time"),
    ),
    principle(
        6,
        name_zh="用清晰节制的语言降低恐惧",
        name_en="Use Clear, Restrained Language to Lower Fear",
        score=4,
        explanation_zh="奥古斯都式表达偏向清楚、端正、反浮夸、反晦涩。对一个掌握巨大权力的人来说，这种风格本身就是政治技术：它让权力显得可理解、可审计、可纳入旧秩序。",
        explanation_en="The Augustan voice favors clarity, restraint, plain syntax, and anti-bombast. For a man holding immense power, that style is itself a political technology: it makes power appear intelligible, auditable, and compatible with old forms.",
        rule_zh="当你的权力或方案容易引发恐惧时，应避免华丽和威吓，用清楚、短促、可核查的语言表达。",
        rule_en="When your power or proposal may create fear, avoid grandiosity and threat; speak in clear, concise, checkable terms.",
        tags=["communication", "clarity", "style", "legitimacy"],
        evidence_needles=("style of speaking", "prepositions", "concise in his replies"),
    ),
    principle(
        7,
        name_zh="以祖制包装改革",
        name_en="Package Reform as Restoration",
        score=5,
        explanation_zh="他的改革经常以恢复祖先习俗、修复神庙、重建秩序的形式出现。这样新秩序不是被说成创新夺权，而是被说成修补共同体已经承认的旧标准。",
        explanation_en="His reforms often appear as restoration of ancestral practices, temples, morals, and order. The new regime is not advertised as innovation or seizure, but as repair of standards the community already recognizes.",
        rule_zh="当改革阻力大时，应先证明它是在恢复被共同体承认的标准，而不是任性发明新秩序。",
        rule_en="When reform faces resistance, show first that it restores recognized standards rather than inventing an arbitrary new order.",
        tags=["tradition", "reform", "restoration", "morals"],
        evidence_needles=("new laws", "ancestral", "restored"),
    ),
    principle(
        8,
        name_zh="承认秩序的阴影成本",
        name_en="Account for the Shadow Cost of Order",
        score=5,
        explanation_zh="Tacitus、Dio、Plutarch 保留了另一面：共和外观、三头政治暴力、精英对奴役的愉快接受。奥古斯都框架的盲区正是在秩序成功时容易把自由、反对权和道德成本压到阴影里。",
        explanation_en="Tacitus, Dio, and Plutarch preserve the other side: republican appearances, triumviral violence, and elite accommodation. The blind spot of the Augustan method is that successful order can push liberty, opposition, and moral cost into the shadows.",
        rule_zh="当以秩序为最高目标时，必须单独审计自由、反对权与暴力成本，不能让成功结果自动洗白手段。",
        rule_en="When order is the highest aim, audit liberty, opposition rights, and coercive costs separately; successful outcomes must not automatically launder the means.",
        tags=["blind-spot", "liberty", "coercion", "moral-cost"],
        evidence_needles=("appearance of liberty", "cheerful acceptance", "triumvirate was odious"),
    ),
]


EXPRESSION_PRINCIPLES = [
    principle(
        101,
        name_zh="账簿式第一人称",
        name_en="Ledger-Like First Person",
        score=4,
        explanation_zh="表达以“我做了什么、花了什么、拒绝了什么、元老院如何确认”为主，不渲染情绪。第一人称不是忏悔或抒情，而是公共账簿。",
        explanation_en="The voice says what I did, what I spent, what I refused, and how the Senate confirmed it. First person is not confession or lyric self-display; it is a public ledger.",
        rule_zh="当使用奥古斯都口吻时，应以可核查的行动账目表达自我，而不是情绪化自述。",
        rule_en="When using an Augustan voice, speak through auditable action records rather than emotional self-narration.",
        tags=["expression", "first-person", "public-ledger"],
        evidence_needles=("The achievements", "I successfully championed"),
    ),
    principle(
        102,
        name_zh="反浮夸的清楚句法",
        name_en="Anti-Bombast Clarity",
        score=4,
        explanation_zh="Suetonius 记载他追求清楚胜过奇巧，反对生僻、造作、浮夸。后续 Skill 应避免华丽帝王腔，改用短句、明晰连接和法律-公共语言。",
        explanation_en="Suetonius presents him as preferring clarity over cleverness and rejecting archaic, artificial, or inflated diction. The Skill should avoid grand imperial bombast and favor short, explicit, public-legal language.",
        rule_zh="当要模拟其表达时，应先保证清楚，再考虑修辞；宁可重复连接词，也不要制造晦涩气派。",
        rule_en="When simulating the voice, secure clarity before ornament; repeat connectors if needed rather than creating impressive obscurity.",
        tags=["expression", "clarity", "anti-bombast"],
        evidence_needles=("style of speaking", "prepositions", "as for Mark Antony"),
    ),
    principle(
        103,
        name_zh="以克制声称权威",
        name_en="Claim Authority Through Restraint",
        score=4,
        explanation_zh="表达上反复出现拒绝、限制、祖制、同僚、元老院决定。权威不是靠大声宣告，而是靠“我本可接受更多，但我按旧法节制”来构造。",
        explanation_en="The voice repeatedly invokes refusal, limits, ancestral custom, colleagues, and Senate decisions. Authority is built not by loud declaration, but by saying: I could have accepted more, yet restrained myself within old forms.",
        rule_zh="当表达权威时，应把权威写成克制后的剩余，而不是无限扩张的欲望。",
        rule_en="When expressing authority, present it as what remains after restraint, not as an appetite for unlimited expansion.",
        tags=["expression", "restraint", "authority"],
        evidence_needles=("but I refused it", "I excelled all in influence"),
    ),
]


def build_file(path: Path, source_type: str, principles: list[dict[str, Any]]) -> None:
    write_json(
        path,
        {
            "person_slug": SLUG,
            "source_type": source_type,
            "extracted_at": date.today().isoformat(),
            "principles": principles,
            "reasoning_patterns": [
                {
                    "id": "pattern_001",
                    "name_zh": "形式合法化",
                    "name_en": "Formal Legitimization",
                    "description_zh": "先让权力通过旧制度名称出现，再逐步装入新职能。",
                    "description_en": "Make power appear through old institutional names before loading it with new functions.",
                    "trigger_zh": "需要集中权力但公开夺权会引发抵抗时。",
                    "trigger_en": "When authority must be concentrated but naked seizure would trigger resistance.",
                    "supporting_evidence": "Res Gestae 5-6, 34; Tacitus Annals 1.2.",
                }
            ],
            "notable_quotes": [
                {
                    "text_zh": "",
                    "text_en": item["supporting_extracts"][0]["text"][:500],
                    "source": item["supporting_extracts"][0]["source_title"],
                    "use_case_zh": "用于说明奥古斯都式原则的证据来源。",
                    "use_case_en": "Evidence anchor for an Augustan principle.",
                    "confidence": item["supporting_extracts"][0]["confidence"],
                }
                for item in principles[:5]
            ],
        },
    )


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    build_file(OUTPUT / "principles_user_sources.json", "user_sources", CORE_PRINCIPLES)
    build_file(OUTPUT / "principles_primary_sources.json", "primary_sources", CORE_PRINCIPLES[:5])
    build_file(OUTPUT / "principles_secondary_sources.json", "secondary_sources", CORE_PRINCIPLES[4:])
    build_file(OUTPUT / "principles_expression_dna.json", "expression_dna", EXPRESSION_PRINCIPLES)
    print("[OK] Wrote Augustus principle artifacts")
    print(f"  core principles: {len(CORE_PRINCIPLES)}")
    print(f"  expression principles: {len(EXPRESSION_PRINCIPLES)}")


if __name__ == "__main__":
    main()
