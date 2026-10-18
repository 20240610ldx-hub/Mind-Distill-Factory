<p align="center">
  <img src="docs/assets/readme/concept-hero.svg" alt="Mind Distill Factory concept illustration" width="100%">
</p>

# Mind Distill Factory · 思维蒸馏工厂

Mind Distill Factory turns a thinker's sources, habits of judgment, voice texture, and failure modes into installable **Codex Skills**.

思维蒸馏工厂把思想家的原始材料、判断习惯、表达质感和失效边界，蒸馏成可安装的 **Codex Skill**。

This project is not a quote shelf, not a biography generator, and not a roleplay costume. Its aim is more demanding: build a small cognitive instrument that can answer from inside a thinker's way of seeing, while staying traceable, useful, and honest about its limits.

Detailed docs: [中文说明](README.zh.md) · [English documentation](README.en.md)

## Why It Exists

Most AI persona prompts stop at surface imitation: famous phrases, a few slogans, and a tone that collapses after the second question. Mind Distill Factory treats a thinker as a working method. It asks:

- What did this person repeatedly notice that others missed?
- Which principles were actually used under pressure?
- Where did the method fail, harden, or contradict the life behind it?
- How should a modern user borrow the wisdom without copying the wound?

The finished Skill should feel less like reading a report and more like holding a disciplined conversation with a mind that has been carefully reconstructed.

## What It Produces

<p align="center">
  <img src="docs/assets/readme/skill-anatomy.svg" alt="Anatomy of a distilled SKILL.md" width="100%">
</p>

Skill discovery requires exactly one file named `SKILL.md` per skill directory. Since format v6, a distilled Skill ships as a small **package** rather than a single bilingual file:

```text
{slug}-wisdom/
├── SKILL.md              # always loaded: Chinese-only, format_version: 6, self-sufficient, ≤500 lines
└── references/           # read on demand via relative paths written into SKILL.md
    ├── cases.md          # worked cases, ≥2 per principle cluster, ≥1 counter-case
    ├── evidence.md       # verbatim source excerpts, machine-checked against the corpus
    └── voice.md          # ≥20 annotated voice samples
```

`SKILL.md` is never a dispatcher: deleting `references/` must still leave a complete, working framework. The case *index* lives in `SKILL.md`; only case bodies live in `references/cases.md`. A human-readable dossier, `人物档案.md`, is written to `output/` and `gallery/` but is never copied into the install directory.

**Chinese is the default and only language of the v6 package.** After the Chinese package is installed, `/distill` asks whether to also build an English version. Only on a yes does it run the English branch, which reuses the language-neutral `framework_core.json`, reconstructs the English framework independently (not a translation), and publishes it as a **separate** skill directory, `{slug}-wisdom-en`. That English Skill is currently a legacy-format single file: it has no `references/` and does not go through gates P1–P6.

| Component | What it does |
| --- | --- |
| Filter-chain decision framework | Step-by-step yes/no gates that make the thinker usable for real decisions. |
| Expression DNA | Eight dimensions of voice: sentence patterns, rhetoric, tone, certainty, humor, taboos, paragraph rhythm, and conversational markers. |
| Core principles | Source-anchored rules with modern application scenarios and outcome logic. |
| Reasoning patterns | Repeated cognitive moves: what triggers them, what mental action they perform, and where they appear in the record. |
| Blind spots with mitigation | Known failure modes, when not to use the Skill, and how to counterbalance it. |
| Values and anti-patterns | What the thinker actively pursues, rejects, and never fully resolves. |
| Source lineage | Confidence-aware attribution. User-provided first-hand sources can be high confidence; web-only quotes are capped. |

## How The Factory Works

<p align="center">
  <img src="docs/assets/readme/source-to-skill-pipeline.svg" alt="Source to Skill pipeline" width="100%">
</p>

The distillation pipeline is gated. It does not let an attractive draft skip source accountability or structural review.

1. Clarify the thinker, slug, taxonomy category, and source availability.
2. Collect primary and secondary sources, including local user-provided files when present.
3. Index large local corpora, then process them through bounded worker batches and a reducer.
4. Extract principles, reasoning patterns, quotes, blind spots, and evidence anchors.
5. Build a language-neutral framework core, then synthesize the Chinese framework from it.
6. Assemble the Chinese `SKILL.md` core, then generate `references/` and the dossier.
7. Pass the package gates (P1–P6), quality review, publish to `gallery/`, and install.
8. Optionally build the separate English Skill `{slug}-wisdom-en`.

The stable local-source contract is:

```text
sources/{slug}/raw/                 # local materials you provide
sources/{slug}/processed/           # structured extracts
sources/{slug}/processed/user_sources.json
```

### Local Source Pipeline

Full details live in [sources/README.md](sources/README.md). In short:

- **Source registry.** Indexing (`python scripts/local_source_pipeline.py index <slug>`) accepts `.txt`, `.md`, `.markdown`, and `.pdf`, including nested folders, and writes `processed/source_registry.json`, binding each file to its path, media type, size, SHA-256, role, origin, rights status, and duplicates.
- **PDF page classification.** Each PDF page and document is classified as pure text, mixed text/image, pure image, or empty/unreadable. Only information-rich image pages, or pages with poor text quality, become OCR candidates. Native text and OCR text are kept as separate provenance layers.
- **Optional extras.** PDF and OCR backends are opt-in `pyproject.toml` extras: `pdf` (PyMuPDF, pypdf), `ocr` (RapidOCR, CPU default), and `ocr-high-accuracy` (PaddleOCR escalation).

  ```powershell
  pip install -e ".[pdf,ocr]"
  ```

- **Deterministic sampling.** Large corpora get a `sampling_plan.json` with a stable seed, strata, selected units, token coverage, and omitted strata, plus a `dispatch_plan.json` of bounded worker batches.
- **Budget gate.** `cost_estimate.json` gives token, request, and OCR-page ranges (or `cost_unknown` when pricing is not configured; it never invents a currency amount). If the upper bound exceeds the configured budget, the orchestrator must ask whether to process exhaustively, sample, reduce scope, or cancel **before** any expensive LLM workers or network supplementation start.

## Evaluation

<p align="center">
  <img src="docs/assets/readme/runtime-evaluation-loop.svg" alt="Runtime evaluation loop" width="100%">
</p>

The evaluator is intentionally separate from the distillation pipeline. It can inspect static artifacts, run DeepSeek-compatible dialogue tests, judge runtime behavior, and produce scorecards without mutating the Skill itself.

The newest appendix is the non-benchmark **Soul Ten Questions** artifact. After a full generated runtime test, DeepSeek can ask and answer ten tailored questions about regret, alternate history, contradiction, compromise, misunderstood principles, decisive moments, unique personality wisdom, warnings against imitation, modern-use boundaries, and final self-judgment.

<p align="center">
  <img src="docs/assets/readme/soul-ten-questions.svg" alt="Soul Ten Questions appendix" width="100%">
</p>

This appendix is for private human reading. It does not change `runtime-judgment.json`, `runtime_score_25`, score caps, grades, or benchmark readiness.

## Quick Start

Clone and smoke-test the public toolchain:

```powershell
git clone https://github.com/20240610ldx-hub/Mind-Distill-Factory.git
cd Mind-Distill-Factory
python -m unittest discover -s tests -v
```

Use the `/distill` command from a Codex workflow:

```text
/distill "Sun Tzu"
/distill 王阳明
```

Validate pipeline stages manually:

```powershell
python scripts\validate_output.py sources <person-slug>
python scripts\validate_output.py principles <person-slug>
python scripts\validate_output.py frameworks <person-slug>
python scripts\validate_output.py package <person-slug>
python scripts\validate_output.py gallery <person-slug>
```

`package` runs the v6 gates. All six are rule-based (no LLM scoring), because an LLM reviewer once graded quotes "EXACT" that were not verbatim:

| Gate | Check |
| --- | --- |
| P1 | Every quote in `SKILL.md` appears verbatim in some card in `references/evidence.md`. |
| P2 | Every verbatim excerpt in `evidence.md` appears verbatim in the source corpus. |
| P3 | Every backticked path in `SKILL.md` resolves to a real file. |
| P4 | `cases.md` has ≥2 cases per principle cluster and ≥1 counter-case overall. |
| P5 | The case index in `SKILL.md` and the `case_id`s in `cases.md` match one-to-one. |
| P6 | The core is self-sufficient: ≤500 lines, all required sections present and substantive, enough core principles. |

The `skill` stage dispatches by frontmatter: a `SKILL.md` with `format_version: 6` is validated as a package; one without it (older gallery Skills, and the English `-wisdom-en` branch) keeps the legacy single-file validation path.

Run runtime evaluation when you have configured a DeepSeek-compatible key locally:

```powershell
Copy-Item evaluation\runtime\.env.example evaluation\runtime\.env
# Edit evaluation\runtime\.env locally. Do not commit it.

python evaluation\runtime\run_dialogue_eval.py --slug <person-slug> --root . --ten-questions auto
python evaluation\scripts\collect_artifacts.py --slug <person-slug> --root . --out evaluation\reports\<person-slug>\artifact-facts.json
```

For deterministic local tests, keep external model calls off:

```powershell
$env:MIND_DISTILL_EVAL_LLM = "off"
python -m unittest discover -s tests -v
```

## Gallery

`/distill` publishes a Skill with `python scripts\publish_skill.py --slug <person-slug>`, re-checks it with the `gallery` stage (per-file hash comparison of `output/` and `gallery/`, including `references/`), and only then installs it. Only `SKILL.md` and `references/` go into the install directory (`~/.claude/skills/{person-slug}-wisdom/`; the optional English Skill goes to `~/.claude/skills/{person-slug}-wisdom-en/`). Copy the whole package, not just `SKILL.md`. `人物档案.md` stays in `gallery/`.

The public gallery contains installable Skills for:

| Thinker | Skill focus |
| --- | --- |
| Charlie Munger | Multidisciplinary mental models, inversion, business judgment. |
| Chiang Kai-shek | Strategic endurance, organizational reform, weak-side diplomacy. |
| Mao Zedong | Contradiction analysis, investigation, underdog strategy. |
| Richard Feynman | First principles, scientific honesty, learning by explanation. |
| Sun Tzu | Competitive strategy, positioning, deception, timing. |
| Wang Yangming | Conscience, unity of knowledge and action, moral self-cultivation. |
| Zeng Guofan | Self-discipline, talent judgment, patience under pressure. |
| Zhang Juzheng (`zhang-juzheng-v6`) | Performance accountability, executive follow-through, fiscal discipline. The reference v6 package (`SKILL.md` + `references/` + `人物档案.md`). |

The other seven gallery entries predate v6 and are legacy bilingual single-file Skills.

## Debate Arena

The `debate_arena/` package lets two Skills argue a topic through structured roles: profiler, topic generator, debaters, fact checker, and judge.

```powershell
python -m debate_arena run --llm fake --issues 3 --out output\debate_arena\dry_run.md
```

For real runs, set `DEBATE_ARENA_API_KEY` or `OPENAI_API_KEY`. See [debate_arena/README.md](debate_arena/README.md).

## Public Release Boundary

This repository is the public engineering surface. It includes templates, orchestration contracts, evaluator code, gallery Skills, diagrams, and tests. It intentionally excludes local secrets, private source corpora, generated reports, release-video working files, and paid runtime outputs.

The MIT license applies to the code and documentation in this repository. It does not grant rights to third-party books, PDFs, recordings, scans, or other materials used privately during distillation.

## Repository Map

```text
agents/         Subagent contracts for extraction, synthesis, review, and assembly
commands/       The /distill orchestration command
config/         Taxonomy and defaults
debate_arena/   Two-Skill debate runner
docs/assets/    Public README and project images
evaluation/     Standalone SkillEval-MDF runtime and artifact evaluator
gallery/        Released installable Skills (v6 packages and legacy single files)
scripts/        Validators, package gates, source registry/PDF/sampling, and utility scripts
sources/        Public placeholder plus local-source contract
templates/      Skill templates and hand-crafted examples
tests/          Regression tests
```
