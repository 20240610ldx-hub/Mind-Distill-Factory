# Mind Distill Factory

A universal factory for distilling famous thinkers' wisdom into structured Codex Skills.

## Project Purpose

This project systematically extracts decision-making frameworks, reasoning patterns, and actionable principles from historical and contemporary figures, producing installable Codex Skills.

**Core philosophy:** Extract executable reasoning algorithms through **first-person immersive perspective** — the AI internalizes a thinker's cognitive framework and responds as if that thinker is directly conversing with the user ("I believe...", "In my experience..."). This is NOT theatrical roleplay, but deep embodiment of their reasoning patterns, expression style, and value orientation. The response must carry the **expressive texture** of each thinker's communication style (sentence patterns, rhetoric, tone) and their **constructive value orientation** (emphasizing self-empowerment and practical action over grievance).

## Key Directories

- `config/` — Taxonomy, defaults, and post-review tuning guide
- `templates/` — Skill templates (`skill-template.v6.zh.md` for v6, legacy zh/en), attachment templates in `templates/refs/`, and hand-crafted examples
- `commands/` — The `/distill` orchestrator command
- `agents/` — Subagent definitions for the distillation pipeline
- `scripts/` — Validation and utility scripts (JSON Schema checks, installation)
- `sources/{slug}/raw/` — User-provided source materials (TXT, MD, PDF; nested folders allowed). Local-only, never committed
- `sources/{slug}/processed/` — Source registry, PDF extraction sidecars, shard/sampling/dispatch plans, cost estimate, and structured extracts. See `sources/README.md`
- `output/{slug}/` — Generated intermediate artifacts and draft Skills
- `gallery/{slug}/` — Symlinks to finalized Skills (single source of truth in templates/examples/)

## Running the Pipeline (any harness)

- **Single entry point:** `python scripts/mdf.py` (`doctor`, `init`, `status`, `next`, `acquire`, `index`, `clean`, `reduce`, `validate`, `brief`, `run`, `publish`, `ocr`, `harness`). Stage tree: `config/pipeline_stages.json`.
- **Orchestrator:** Codex uses `$mdf-distill`, pi uses `/skill:mdf-distill` (`.agents/skills/mdf-distill/SKILL.md`); the full protocol is `commands/distill.md`. Where this file and `CLAUDE.md` disagree, `CLAUDE.md` wins.
- **Agent steps without subagents:** `python scripts/mdf.py run <slug> [step] --harness <codex|pi>` hands the step to a fresh process with a self-contained brief. It prints a plan first; add `--yes` only after the user agrees (paid model calls). Stage 5 review must run this way or in a real subagent, never in the orchestrator's own context. The process (or subagent) running a brief must not spawn subagents of its own: it already is the isolated context. When `mdf run` warns that it did (`⚠️ 新进程又派了 N 个子代理`), tell the user and check the output against the checkpoint before rerunning or moving on. When `mdf index` leaves a single shard, `mdf run` folds shard extraction, reduce and principle extraction into one unit, `small-corpus`: one brief, one process, all three checkpoints run. Open the stage 1 heading before it and the stage 2 heading after, and review both stages' results.
- **Progress the user can follow (three beats per phase, in Chinese):** open with a chapter label (an H2 such as `## 阶段 2 · 原则提取` when the harness has no chapter tool) and the stage card from `mdf next <slug> --card`; speak mid-phase only when something new happens; close with the result line. Track the phases in the harness's native task list (one item per phase, titled like the chapter; Codex: its plan tool), created once at the start from `mdf status <slug> --json` and updated as gates pass; without a task list, close each phase with the progress bar from `mdf status <slug>`. No HTML board.
- **Ethics and law:** see `docs/ethics-and-legal.md` (quote length, living-person notice, source rights, TDMRep). Acquire only through `mdf acquire`.

## Critical Platform Constraint

**Codex skill discovery requires exactly `SKILL.md`** (case-sensitive) in each skill directory. Files like `SKILL.zh.md`, `SKILL.en.md`, `SKILLzh.md`, or `README.md` are invisible to the skill loader. A skill directory MAY also contain sub-files (e.g. `references/*.md`); the model reads those on demand via relative paths written into `SKILL.md`. See Rule 4 and the v6 package format below.

## Distillation Rules

1. Every principle MUST trace back to a specific source (book, speech, letter, documented statement)
2. Every Skill MUST include a "Known Blind Spots" section with **mitigation advice** — no thinker is infallible
3. Decision frameworks MUST be step-by-step **filter chains** (each step is a yes/no gate), not open-ended questions
4. **Language: Chinese-only by default.** Each Skill produces `frameworks.zh.json` and a Chinese-only `SKILL.md` carrying `format_version: 6`. No `## English` block, no language-detection header. After the Chinese package is installed, the orchestrator asks whether to also generate an English version; only on a yes does it run the EN branch (reusing the language-neutral `framework_core.json`) and publish it as a **separate skill directory** `{person-slug}-wisdom-en`. The English version is an independent cognitive reconstruction, NOT a translation. The EN branch currently produces a legacy-format single-file `SKILL.md` (no `format_version`, no `references/`, not subject to gates P1–P6)
5. Each person maps to 1 primary + up to 2 secondary categories from `config/taxonomy.json`
6. Source truthfulness: quotes from web search only are capped at `confidence: medium`. Only user-provided first-hand sources or verified publications can be `confidence: high`
7. Pipeline checkpoints: `python scripts/validate_output.py <stage> <slug>` MUST pass between each Stage
8. Local sources: index before dispatching workers (`python scripts/mdf.py index <slug>`). Respect the sampling and dispatch plans, and if `cost_estimate.json` exceeds the configured budget, ask the user (exhaustive / stratified sampling / reduce scope / cancel) before starting expensive workers or network supplementation. PDF/OCR backends are optional extras in `pyproject.toml` (`pdf`, `ocr`, `ocr-high-accuracy`); OCR text is kept as a separate provenance layer and never replaces native text

## Skill Package Format (v6)

A distilled Skill ships as a **package**, not a single file:

```
{slug}-wisdom/
├── SKILL.md              # always-loaded, Chinese, self-sufficient, ≤500 lines
└── references/
    ├── cases.md          # on demand — worked cases, ≥2 per cluster, ≥1 counter-case
    ├── evidence.md       # on demand — verbatim source excerpts, machine-checked
    └── voice.md          # on demand — ≥20 annotated voice samples
```

`SKILL.md` is **never a dispatcher**. Deleting `references/` must leave a complete, working framework — gate P6 enforces this. The case *index* lives in the core so the model always knows what exists; only case *bodies* live in the attachment.

`人物档案.md` is a human-readable dossier. It goes to `output/` and `gallery/` but **never** into the install directory.

Gates P1–P6 (`python scripts/validate_output.py package {slug}`) are all rule-based — no LLM scoring — because an LLM reviewer graded 7/7 quotes "EXACT" on a set where 4 of 15 were not verbatim. P1 quote → evidence closure, P2 evidence → corpus closure, P3 backticked paths resolve, P4 case coverage, P5 case index ↔ `cases.md` one-to-one, P6 core self-sufficiency.

Legacy Skills (no `format_version` in frontmatter: the older gallery entries and the EN branch) keep the legacy single-file validation path; `validate_output.py skill` dispatches on `format_version`.

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

After a Skill passes quality review and is installed, it should be **stress-tested in real conversations** (≥8 turns covering all input types). The test log is then reviewed against `config/post-review-tuning-guide.md`, which documents runtime checkpoints, standard fix recipes for common AI default-behavior regressions, rules for syncing fixes to `output/`, `gallery/`, and the installed skill directory, and the template feedback loop (fixes proven across ≥2 Skills get upstreamed into `templates/`).

## Quality Gates

Before a Skill enters `gallery/`:
- Quotes must be verified against known sources — web-only quotes marked as `confidence: low/medium`
- Principles must pass the three-tier uniqueness test (de-name test + input-evidence anchor + methodology-level check)
- The decision framework must consist entirely of filter-type steps (no open-ended final steps)
- **v6 packages must pass gates P1–P6** (`python scripts/validate_output.py package {slug}`)
- If an English branch was requested (`{person-slug}-wisdom-en`), both language versions must be reviewed for cultural-cognitive accuracy
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
