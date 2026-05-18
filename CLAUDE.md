# Mind Distill Factory

A universal factory for distilling famous thinkers' wisdom into structured Claude Code Skills.

## Project Purpose

This project systematically extracts decision-making frameworks, reasoning patterns, and actionable principles from historical and contemporary figures, producing installable Claude Code Skills.

**Core philosophy:** Extract executable reasoning algorithms through **first-person immersive perspective** — the AI internalizes a thinker's cognitive framework and responds as if that thinker is directly conversing with the user ("I believe...", "In my experience..."). This is NOT theatrical roleplay, but deep embodiment of their reasoning patterns, expression style, and value orientation. The response must carry the **expressive texture** of each thinker's communication style (sentence patterns, rhetoric, tone) and their **constructive value orientation** (emphasizing self-empowerment and practical action over grievance).

## Key Directories

- `config/` — Taxonomy, defaults, and post-review tuning guide
- `templates/` — Skill templates (zh/en) and hand-crafted examples
- `commands/` — The `/distill` orchestrator command
- `agents/` — Subagent definitions for the distillation pipeline
- `scripts/` — Validation and utility scripts (JSON Schema checks, installation)
- `sources/{slug}/raw/` — User-provided source materials (PDF, TXT, MD)
- `sources/{slug}/processed/` — Structured extracts from subagents
- `output/{slug}/` — Generated intermediate artifacts and draft Skills
- `gallery/{slug}/` — Symlinks to finalized Skills (single source of truth in templates/examples/)

## Critical Platform Constraint

**Claude Code skill discovery requires exactly `SKILL.md`** (case-sensitive) in each skill directory. Files like `SKILL.zh.md`, `SKILL.en.md`, `SKILLzh.md`, or `README.md` are invisible to the skill loader. This means: even though we generate independent bilingual frameworks, the final deliverable MUST be a single `SKILL.md` with both languages inline. See Rule 4 for implementation details.

## Distillation Rules

1. Every principle MUST trace back to a specific source (book, speech, letter, documented statement)
2. Every Skill MUST include a "Known Blind Spots" section with **mitigation advice** — no thinker is infallible
3. Decision frameworks MUST be step-by-step **filter chains** (each step is a yes/no gate), not open-ended questions
4. Bilingual output: each Skill produces separate `frameworks.{zh,en}.json` files with **independent cognitive framings** (NOT translations — they may have different numbers of principles and different framework step orders). However, Claude Code's skill system only recognizes a single `SKILL.md` per directory — so the final deliverable MUST be one `SKILL.md` containing both languages, structured with a language-detection header (`## English` + `## 中文版`) so the model auto-selects the matching section based on user language. The intermediate `.zh.md` / `.en.md` drafts live in `output/{slug}/` as development artifacts, but the installed file is always `SKILL.md`
5. Each person maps to 1 primary + up to 2 secondary categories from `config/taxonomy.json`
6. Source truthfulness: quotes from web search only are capped at `confidence: medium`. Only user-provided first-hand sources or verified publications can be `confidence: high`
7. Pipeline checkpoints: `python scripts/validate_output.py <stage> <slug>` MUST pass between each Stage

## Anti-Formula Design (v5) — Immersive Perspective + Structural Naturalness + Boundary Awareness

Skills must NOT produce formulaic, checklist-style responses. Key mechanisms:
- **First-Person Immersion**: Respond in the thinker's first-person voice ("I believe...", "my experience shows..."), NOT third-person narration ("Munger said...") or second-person lecturing ("you should..."). The user should feel they are conversing with the thinker, not reading a report about them
- **Expression DNA**: Every Skill includes **8-dimension** voice profile (sentence patterns, rhetoric, tone, certainty, humor, taboos, **paragraph rhythm**, **conversational markers**) with calibration examples. The two new dimensions address output-level structure, not just sentence-level style
- **Structural Naturalness Rules**: 5 mandatory instructions targeting AI-structural uniformity — vary sentence length >30%, make paragraphs uneven (1-6 sentences), break symmetric enumeration, diversify paragraph entry points, allow imperfect transitions. Complements Anti-Formula Rules: anti-formula governs *content arrangement*, structural naturalness governs *output shape*
- **Response Strategy**: Replaces rigid Frame→Diagnose→Prescribe→Caveat with flexible input-type adaptation (practical decision / conceptual confusion / emotional sharing / idea sparring / **fact-checking** / **methodology inquiry**)
- **Anti-Formula Rules**: 6 mandatory instructions embedded in every Skill (no sequential listing, match depth to complexity, use expression DNA, don't number principles, brief caveats, **no closing-slogan repetition**)
- **Boundary Rules**: 5 graduated rules governing temporal/factual boundaries — lifetime events (full first-person), posthumous events (methodology-based analysis with temporal flag), living figures (decline to evaluate), data/statistics (flag for verification), structural hardship (acknowledge systemic factors, don't reduce to individual effort)
- **Values & Anti-Patterns**: What the thinker actively pursues AND rejects, plus unresolved internal tensions — prevents one-dimensional advice
- **Constructive Value Orientation**: When users raise grievances, unfairness, or adversity, the response should (1) **fully** acknowledge structural difficulty as real, (2) shift to locally actionable strategies (risk mitigation, skill-building, changing battlefields, mutual-aid networks), (3) channel the thinker's characteristic optimism or resilience. Don't collapse structural problems into "just work harder" — acknowledge the structural reality, then focus on what agency exists within those constraints

## Post-Review Tuning (Stage 7)

After a Skill passes quality review and is installed, it should be **stress-tested in real conversations** (≥8 turns covering all input types). The test log is then reviewed against `config/post-review-tuning-guide.md`, which documents:
- 8 runtime-specific checkpoints (ordinal enumeration, closing repetition, structural uniformity, length mismatch, etc.)
- Standard fix recipes for the 5 most common AI default-behavior regressions
- Rules for syncing fixes to `output/`, `gallery/`, and `~/.claude/skills/`
- Template feedback loop: fixes proven across ≥2 Skills get upstreamed into `templates/`

This guide is referenced by both `quality-reviewer` (for second-pass reviews) and `skill-assembler` (for targeted patches). See `config/post-review-tuning-guide.md` for the full protocol.

## Quality Gates

Before a Skill enters `gallery/`:
- Quotes must be verified against known sources — web-only quotes marked as `confidence: low/medium`
- Principles must pass the three-tier uniqueness test (de-name test + input-evidence anchor + methodology-level check)
- The decision framework must consist entirely of filter-type steps (no open-ended final steps)
- Both language versions must be reviewed for cultural-cognitive accuracy
- Each blind spot must include a mitigation recommendation
- `distill_confidence.score` must be ≥ 3 (on a 1-5 scale)
- **Expression DNA must be specific enough to differentiate from generic analytical tone** (quality-reviewer score ≥ 3) — must include all 8 dimensions including paragraph rhythm and conversational markers
- **Structural Naturalness Rules must be present and complete** (5 rules) in every Skill's Response Strategy
- **Boundary Rules must be present** (5 graduated rules for temporal/factual boundaries)
- **Anti-Formula Rules must include rule #6** (no closing-slogan repetition)
- **Values & Anti-Patterns section must have ≥2 pursued, ≥2 rejected, ≥1 tension**

## Naming Conventions

- Person slugs: lowercase, hyphenated (e.g., `charlie-munger`, `sun-tzu`, `wang-yangming`)
- Skill names: `{person-slug}-wisdom` (e.g., `charlie-munger-wisdom`)
- Source files: `{source-abbrev}_{content-type}.{ext}` (e.g., `poor_charlies_almanack_quotes.txt`)
