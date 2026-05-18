# Mind Distill Factory

A universal factory for distilling the decision-making frameworks of history's greatest thinkers into installable **Claude Code Skills**. Each Skill encodes a thinker's cognitive architecture as an executable reasoning algorithm — the AI internalizes their mental models, expression patterns, and value orientation, then responds in a first-person immersive voice as if that thinker is conversing directly with you.

> "I don't want a biography. I want to think like them." — every reader of *Poor Charlie's Almanack*

---

## What This Is

This is not a quote collection. It's not a biography generator. It's a **cognitive cloning pipeline**. Each Skill produced by this factory contains:

| Component | Description |
|-----------|-------------|
| **Filter-chain decision framework** | Sequential yes/no gates — not open-ended questions. Every step is a binary filter that narrows the decision space. |
| **Expression DNA (8 dimensions)** | Sentence patterns, signature rhetoric, tonal baseline, certainty expression, humor style, taboo expressions, paragraph rhythm, conversational markers — with good/bad calibration examples. |
| **Core principles (5–8)** | Each with source attribution, a decision rule ("When X, then Y"), a modern application scenario, and outcome logic. |
| **Reasoning patterns (3–5)** | Characteristic cognitive moves — triggers, mental operations, and historical examples. |
| **Blind spots with mitigations (2–4)** | Specific failure modes, not vague caveats. Each includes concrete mitigation advice and "when NOT to use" guidance. |
| **Values & anti-patterns** | What the thinker actively pursues (≥2), what they actively reject (≥2), and unresolved internal tensions (≥1). |
| **Signature quotes (5–10)** | Verbatim, source-anchored, each tagged with the conversational context where it lands hardest. |
| **Source lineage** | Full attribution chain with confidence levels — user-provided first-hand sources get `high`, web-only quotes are capped at `medium`. |

---

## The Pipeline (7 Stages)

Every Skill travels through a gated pipeline. Between each stage, `validate_output.py` runs — if it fails, the pipeline stops.

```
 Stage 0       Stage 1          Stage 2         Stage 3          Stage 4       Stage 5       Stage 6
 ┌───────┐    ┌────────────┐   ┌───────────┐   ┌─────────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐
 │Intent │ →  │  Source    │ → │ Principle  │ → │  Framework  │ → │ Skill   │ → │ Quality │ → │ Install │
 │Clarify│    │Collection  │   │Extraction  │   │  Synthesis  │   │Assembly │   │ Review  │   │ & Ship  │
 └───────┘    └────────────┘   └───────────┘   └─────────────┘   └─────────┘   └─────────┘   └─────────┘
     ✓              ✓                ✓               ✓               ✓             ✓             ✓
 checkpoint    checkpoint       checkpoint      checkpoint      checkpoint     checkpoint    user-facing
```

### Stage 0 — Intent Clarification

**Actor: Orchestrator (you)**

Parses the thinker's name, detects user-provided source files in `sources/{slug}/raw/`, recommends a primary + secondary taxonomy category from the 10-category system, and initializes the output directory tree. If no user sources exist, asks whether to proceed via web search or wait for materials.

### Stage 1 — Source Collection

**Actors: 4 parallel source-researcher sub-agents**

| Agent | Task | Output |
|-------|------|--------|
| A — User sources | Read all files in `sources/{slug}/raw/`; extract quotes, principles, and behavioral records | `user_sources.json` |
| B — Primary sources | Web search for the thinker's own writings, speeches, interviews, letters | `primary_sources.json` |
| C — Secondary sources | Web search for authoritative biographies, academic analyses, deep profiles | `secondary_sources.json` |
| D — Expression DNA | Search for speech transcripts, interview verbatims, original correspondence — focus on *how* they speak/write, not *what* they say. Uses `content_type: "expression_sample"`. | `expression_dna.json` |

Agent D is **mandatory and non-skippable** — it's the foundation for anti-formula quality. If web search fails entirely, expression samples are extracted from user-provided PDFs.

Search tool fallback chain: `WebSearch` → `Tavily MCP` → `WebFetch` direct → annotate failure.

### Stage 2 — Principle Extraction

**Actors: 2–4 parallel principle-extractor sub-agents (one per source file)**

Each extracts candidate principles, reasoning patterns, and notable quotes from its assigned source file. Every candidate passes a **three-tier uniqueness test**:

1. **De-name test**: If you strip the thinker's name, is this still recognizably *their* idea — or just generic advice?
2. **Input-evidence anchor**: Must have ≥2 supporting extracts from the *actual input files* (not the model's training data memory).
3. **Methodology-level check**: Does it describe a concrete *how* (method), not just a *what* (value)?

Outputs `principles_{source_type}.json` files (8–12 candidate principles per agent).

### Stage 3 — Framework Synthesis

**Actor: 1 framework-synthesizer sub-agent**

This is the architecture step. The synthesizer:

1. Cross-file deduplication (merge functionally identical principles)
2. Distinctiveness ranking (by uniqueness score, evidence richness, actionability, cross-context applicability)
3. Selection of 5–8 core principles
4. Construction of a **sequential filter-chain** decision framework (4–5 steps, each a binary gate)
5. Extraction of 3–5 characteristic reasoning patterns
6. Identification of 2–4 blind spots with mitigation recommendations
7. Synthesis of the 8-dimension Expression DNA
8. Extraction of Values & Anti-Patterns (pursued / rejected / tensions)
9. Compilation of 5–10 signature quotes with usage scenarios
10. Calculation of overall `distill_confidence` score (1–5)

Produces **two independent files**: `frameworks.zh.json` and `frameworks.en.json`. These are NOT translations — they may have different principle counts, different framework step orders, and different quote selections, each optimized for its target language and cultural context. They only share: person identity, category assignments, and equivalent blind-spot coverage.

### Stage 4 — Skill Assembly

**Actor: 1 skill-assembler sub-agent**

Fills both language templates independently from their respective frameworks, then merges them into a single `SKILL.md` with a language-detection header. This constraint exists because **Claude Code's skill loader recognizes exactly `SKILL.md`** (case-sensitive) — files like `SKILL.zh.md` or `SKILL.en.md` are invisible.

Merged file structure:
```markdown
---
name: {person-slug}-wisdom
description: >- (bilingual, with trigger keywords in both languages)
argument-hint: <describe your situation / 描述你的决策场景>
---

# Language Detection · 语言检测

CRITICAL: detect user's language → route to matching section

---

## English
(full English skill content from draft.en.md)

---

## 中文版
(full Chinese skill content from draft.zh.md)
```

### Stage 5 — Quality Review

**Actor: 1 quality-reviewer sub-agent**

A 7-dimension red-team review producing a PASS / REVISE / FAIL verdict:

| Dimension | Weight | What it checks |
|-----------|--------|----------------|
| Accuracy | 25% | Source attribution correctness; hallucination detection |
| Distinctiveness | 20% | De-name test; uniqueness scores ≥ 3 for ≥4/5 principles |
| Actionability | 15% | Decision rules are concrete; filter steps are binary gates |
| Expression Authenticity | 15% | First-person voice; all 8 DNA dimensions populated; calibration examples show meaningful ✅/❌ contrast |
| Values Completeness | 10% | ≥2 pursued, ≥2 rejected, ≥1 tension; anti-patterns complement blind spots |
| Bilingual Consistency | 10% | Equivalent blind-spot coverage; no missing sections in either language |
| Format Compliance | 5% | Correct section titles; no unfilled placeholders; anti-formula + structural naturalness rules present |

**PASS threshold**: composite score ≥ 3.5, accuracy ≥ 3, expression authenticity ≥ 3.

**REVISE**: retries are limited to 2 rounds before escalation to FAIL.

### Stage 6 — Installation

The orchestrator presents a summary (thinker info, principle list, review result), then offers four options: install, view-only, modify-then-install, or regenerate. Installation copies the merged `SKILL.md` to `~/.claude/skills/{slug}-wisdom/`, updates the gallery and `gallery/index.json`, then runs `validate_output.py gallery` to confirm sync.

---

## Key Directories

```
mind-distill-factory/
│
├── config/
│   ├── taxonomy.json          # 10-category thinker classification system
│   └── defaults.json          # Pipeline constraints & quality thresholds
│
├── commands/
│   └── distill.md             # The /distill orchestrator (Stages 0–6)
│
├── agents/                    # 5 specialized sub-agent definitions
│   ├── source-researcher.md   #   Stage 1: search→fetch→extract, 4 task types
│   ├── principle-extractor.md #   Stage 2: extract + three-tier uniqueness test
│   ├── framework-synthesizer.md # Stage 3: merge, rank, synthesize bilingual frameworks
│   ├── skill-assembler.md     #   Stage 4: fill templates, merge into single SKILL.md
│   └── quality-reviewer.md    #   Stage 5: 7-dimension red-team review
│
├── scripts/
│   ├── validate_output.py     # Pipeline gatekeeper — validates at every stage
│   ├── extract_pdf_text.py    # PDF → plain text (PyMuPDF / pypdf)
│   ├── extract_pdf_with_cmap.py # PDF extraction with CMap handling for CJK fonts
│   ├── extract_user_sources.py  # Structured passage extraction from PDF texts
│   ├── build_user_sources.py    # Targeted key-passage extraction (used for Mao)
│   └── fix_frameworks_schema.py # Schema migration / repair tool
│
├── templates/
│   ├── skill-template.en.md   # English Skill template (with all section markers)
│   ├── skill-template.zh.md   # Chinese Skill template
│   └── examples/
│       ├── charlie-munger.en.md # Hand-crafted English Skill (quality benchmark)
│       └── charlie-munger.zh.md # Hand-crafted Chinese Skill
│
├── sources/{slug}/
│   ├── raw/                   # User-provided source materials (PDF, TXT, MD, EPUB)
│   └── processed/             # Structured extracts from Stage 1 sub-agents
│       ├── user_sources.json
│       ├── primary_sources.json
│       ├── secondary_sources.json
│       └── expression_dna.json  # ⚠️ Mandatory — drives anti-formula quality
│
├── output/{slug}/             # Development artifacts (intermediate + drafts)
│   ├── principles_*.json      # Stage 2 output
│   ├── frameworks.{zh,en}.json # Stage 3 output
│   ├── draft.{zh,en}.md       # Stage 4 intermediate drafts
│   ├── SKILL.md               # Stage 4 final merged deliverable
│   └── review.md              # Stage 5 quality review report
│
├── gallery/{slug}/            # Installed Skills (single source of truth)
│   └── SKILL.md
├── gallery/index.json         # Gallery registry
│
└── CLAUDE.md                  # Project handbook — the authoritative spec
```

---

## The 10-Category Taxonomy

Every thinker maps to **1 primary + up to 2 secondary** categories:

| ID | Category | Description | Example Thinkers |
|----|----------|-------------|-----------------|
| `strategy` | Strategy & Decision | Competitive thinking, risk assessment, decisive action under uncertainty | Sun Tzu, Clausewitz, John Boyd |
| `philosophy` | Philosophy & Worldview | Epistemology, ethics as framework, meaning-making | Nietzsche, Zhuangzi, Seneca, Wittgenstein |
| `governance` | Governance & Power | Political philosophy, institutional design, legitimacy | Machiavelli, Han Feizi, Lincoln, Lee Kuan Yew |
| `enterprise` | Enterprise & Wealth | Business strategy, investment thinking, capital allocation | Charlie Munger, Rockefeller, Buffett, Andrew Grove |
| `inquiry` | Inquiry & Discovery | Scientific method, intellectual rigor, paradigm shifts | Feynman, Darwin, Marie Curie, Ibn al-Haytham |
| `creation` | Creation & Craft | Artistic process, aesthetic judgment, innovation | Da Vinci, Steve Jobs, Miyamoto Musashi, Coco Chanel |
| `conduct` | Conduct & Character | Personal ethics, habit formation, integrity | Marcus Aurelius, Confucius, Franklin, Gandhi |
| `resilience` | Adversity & Resilience | Crisis response, perseverance, suffering as teacher | Viktor Frankl, Mandela, Epictetus, Dostoevsky |
| `pedagogy` | Teaching & Influence | Rhetoric, persuasion, mentorship, cultural transmission | Socrates, Maria Montessori, Dale Carnegie, Dewey |
| `lifedesign` | Life Design & Balance | Health, relationships, daily routines, practical wisdom | Montaigne, Thoreau, Epicurus, Lin Yutang |

---

## Anti-Formula Design (v4)

The central quality problem with AI-generated Skills is that they read like templated reports — symmetrical paragraphs, numbered lists, uniform sentence length, perfect transitions. This project attacks that problem at three levels:

### Level 1 — First-Person Immersion

Skills respond in the thinker's voice ("I believe...", "In my experience..."), not third-person narration. This creates conversational texture and prevents the detached-analyst tone.

### Level 2 — Expression DNA (8 Dimensions)

| Dimension | What it captures |
|-----------|-----------------|
| Sentence patterns | Short vs. long; declarative vs. rhetorical; parallel structures |
| Signature rhetoric | Analogies, reductio ad absurdum, quoting classics, data bombardment |
| Tonal baseline | Direct / ironic / combative / calm / colloquial |
| Certainty expression | "No doubt" type vs. "I suspect but am unsure" type |
| Humor style | Deadpan / self-deprecating / satirical / black humor / none |
| Taboo expressions | Words and sentence patterns this thinker would *never* use |
| **Paragraph rhythm** | Alternation pattern between long analytical passages and short declarative paragraphs; single-sentence paragraph habits |
| **Conversational markers** | Characteristic discourse markers, interjections, verbal tics — distinct from generic filler words |

### Level 3 — Structural Naturalness Rules (5 mandatory instructions)

1. **Vary sentence length >30%** — adjacent sentences must differ noticeably; every 3–5 sentences, insert a punchy short line (<15 chars) or a developed long one (>50 chars)
2. **Uneven paragraphs** — length ranges 1–6 sentences; allow single-sentence paragraphs; never have 3+ consecutive paragraphs of similar length
3. **Break symmetric structures** — no "First... Second... Third..."; max 2 parallel items; connect through semantic logic, not ordinal markers
4. **Diversify paragraph entry points** — don't start every paragraph with its topic sentence; sometimes lead with an example, a verdict, or a concrete scenario
5. **Allow imperfect transitions** — real conversation has slight jumps, "coming back to the point" moments, brief digressions that circle back

Together, these three levels ensure that Skill outputs have the texture of human thought, not AI uniformity.

---

## Quality Gates

Before a Skill enters the gallery, it must pass these gates — each enforced by `validate_output.py` and the quality-reviewer sub-agent:

| Gate | Requirement | Enforced by |
|------|-------------|-------------|
| Source attribution | Every principle traces to a specific source (book, speech, letter) | Stage 5 accuracy review |
| Filter framework | Decision steps are binary gates, not open questions | Stage 3 synthesis + Stage 5 review |
| Blind spots | ≥2 limitations, each with concrete mitigation advice | Stage 3 synthesis + validator schema |
| Expression DNA | All 8 dimensions filled; good ✅ / bad ❌ calibration pair provided | Validator schema + Stage 5 expression review |
| Structural naturalness | 5 rules present in Response Strategy | Stage 4 assembly + Stage 5 format review |
| Anti-formula rules | 5 rules present in Response Strategy | Stage 4 assembly + Stage 5 format review |
| Values completeness | ≥2 pursued, ≥2 rejected, ≥1 unresolved tension | Validator schema |
| Bilingual description | Frontmatter description contains both Chinese and English trigger keywords | Validator schema |
| Distill confidence | `score` ≥ 3 (on 1–5 scale) | Stage 3 synthesis + validator schema |
| Gallery sync | `gallery/{slug}/SKILL.md` byte-identical to `output/{slug}/SKILL.md` | Validator `gallery` stage |

---

## Gallery

| Skill | Era | Taxonomy | Distilled | Method | Score |
|-------|-----|----------|-----------|--------|-------|
| **charlie-munger-wisdom** | 1924–2023 | Enterprise + Inquiry + Conduct | 2026-05-01 | hand-crafted | PASS |
| **mao-zedong-wisdom** | 1893–1976 | Strategy + Governance + Philosophy | 2026-05-02 | pipeline | PASS · 4.35/5 |

**mao-zedong-wisdom** notes: 4 user-provided PDFs (55 MB, 8,400+ pages), 13 core works extracted (330K+ characters), 7 principles (zh) / 6 principles (en) with independent framework structures.

---

## Usage

### Distill a New Thinker

```
/distill "Charlie Munger"
/distill 孙子
/distill Seneca
```

The orchestrator walks through source detection, taxonomy recommendation, and all 7 pipeline stages.

### Manual Validation

```bash
python scripts/validate_output.py sources charlie-munger
python scripts/validate_output.py principles mao-zedong
python scripts/validate_output.py frameworks mao-zedong
python scripts/validate_output.py skill mao-zedong
python scripts/validate_output.py gallery mao-zedong
```

### Prerequisites

- **Claude Code** — for skill execution and sub-agent orchestration
- **Python 3.9+** — for validation scripts (standard library only; no pip dependencies required)
- **PyMuPDF** or **pypdf** (optional) — only needed for PDF source extraction

---

## Design Principles

1. **First-person immersion** — "I've always maintained X", not "Munger said X"
2. **Filter chains, not questionnaires** — every decision step narrows the space with a yes/no gate
3. **Independent bilingual framing** — zh and en versions are separate cognitive constructions, not translations
4. **Anti-formula by construction** — structural naturalness is mandatory, not aspirational
5. **User sources over web search** — first-hand materials always outrank web-collected quotes in confidence
6. **Constructive value orientation** — briefly acknowledge adversity, then pivot to self-empowerment and actionable paths
7. **No thinker is infallible** — every Skill carries its own blind spots and anti-patterns
8. **Validation at every gate** — no bad intermediate artifact can poison downstream stages

---

## Naming Conventions

- **Person slugs**: lowercase, hyphenated — `charlie-munger`, `sun-tzu`, `wang-yangming`
- **Skill names**: `{person-slug}-wisdom` — `charlie-munger-wisdom`, `mao-zedong-wisdom`
- **Source files**: `{source-abbrev}_{content-type}.{ext}` — `poor_charlies_almanack_quotes.txt`

---

## License

MIT — the wisdom belongs to the thinkers; the distillation methodology belongs to everyone.
