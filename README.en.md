# Mind Distill Factory

<p align="center">
  <img src="docs/assets/readme/concept-hero.svg" alt="Mind Distill Factory concept illustration" width="100%">
</p>

Mind Distill Factory turns the sources, judgment habits, expressive texture, value orientation, and failure modes of important thinkers into installable **Codex Skills**.

It is not a quote collection. It is not a biography generator. It is not theatrical roleplay. The goal is to build a small cognitive instrument: a `SKILL.md` that can respond from inside a thinker's way of seeing while remaining source-traceable, practically useful, and honest about its own limits.

[中文说明](README.zh.md) · [Main README](README.md)

## The Idea

Most persona prompts imitate the surface: a few famous phrases, a tone label, and a list of slogans. That breaks quickly when a user asks a difficult second question.

Mind Distill Factory treats a thinker as a method under pressure. It asks:

- What did this person notice that others tended to miss?
- Which principles were used when the stakes were real?
- How did the life contradict, distort, or deepen the doctrine?
- Where should a modern user borrow the method, and where should they stop?

A good Skill should feel less like reading a report about a thinker and more like entering a disciplined conversation with a reconstructed mind.

## What A Skill Contains

<p align="center">
  <img src="docs/assets/readme/skill-anatomy.svg" alt="Anatomy of a distilled SKILL.md" width="100%">
</p>

Codex discovers Skills by looking for exactly one file named `SKILL.md`. Because of that hard platform constraint, the final deliverable is a single file. Chinese and English frameworks are still synthesized independently, then assembled into language-aware sections inside that one discoverable artifact.

| Component | Purpose |
| --- | --- |
| Filter-chain decision framework | Sequential yes/no gates that make the thinker usable in real decisions. |
| Core principles | Source-anchored rules with modern scenarios and outcome logic. |
| Reasoning patterns | Characteristic cognitive moves: triggers, mental operations, and historical examples. |
| Expression DNA | Eight dimensions of voice: sentence patterns, rhetoric, tone, certainty, humor, taboos, paragraph rhythm, and conversational markers. |
| Structural naturalness rules | Instructions that prevent template-shaped AI answers and preserve uneven, human-like response shape. |
| Values and anti-patterns | What the thinker pursues, rejects, and leaves unresolved. |
| Blind spots with mitigation | Failure modes, when not to use the Skill, and how to counterbalance it. |
| Source lineage | Confidence-aware attribution. First-hand user materials can be high confidence; web-only quotes are capped. |

## Pipeline

<p align="center">
  <img src="docs/assets/readme/source-to-skill-pipeline.svg" alt="Source to Skill pipeline" width="100%">
</p>

The pipeline is gated because a beautiful answer is not enough. Each stage produces reviewable artifacts, and `scripts/validate_output.py` enforces structural checks between stages.

1. Clarify the thinker, slug, target language, taxonomy category, and source availability.
2. Collect primary and secondary sources, including user-provided local files when present.
3. Shard large local corpora through an indexer, bounded workers, and a reducer.
4. Extract principles, quotes, reasoning patterns, blind spots, and evidence anchors.
5. Build a shared evidence core, then synthesize Chinese and English frameworks independently.
6. Assemble the final `SKILL.md`.
7. Run quality review, validation, gallery sync, and optional runtime evaluation.

The stable local-source contract is:

```text
sources/{slug}/raw/                 # source files supplied by the user
sources/{slug}/processed/           # structured intermediate artifacts
sources/{slug}/processed/user_sources.json
```

### Artifact Flow

| Stage | Question | Typical artifacts |
| --- | --- | --- |
| Stage 0 | Who is being distilled, and what kind of wisdom is this? | slug, taxonomy category, source plan, target language |
| Stage 1 | Are the materials reliable enough? | primary and secondary source findings, quote candidates |
| Stage 1A | How do we process a large local corpus without overloading one context? | shard manifest, worker outputs, `user_sources.json` |
| Stage 2 | Which claims are executable judgment rules? | principles, reasoning patterns, quotes, blind spots |
| Stage 3 | How do the evidence anchors become a full cognitive framework? | framework core, `frameworks.zh.json`, `frameworks.en.json` |
| Stage 4 | Can Codex discover and use it? | one final `SKILL.md` |
| Stage 5 | Does it sound, reason, and self-limit correctly? | quality review and repair notes |
| Stage 6 | Is the released copy the same artifact that passed review? | `gallery/{slug}/SKILL.md`, `gallery/index.json` |

This makes repair local. If the voice is strong but evidence is weak, return to Stage 2. If evidence is good but output shape is formulaic, repair Stage 4 or Stage 5. If Chinese and English versions feel cognitively mismatched, return to Stage 3 rather than translating one into the other.

## Anti-Formula Design

The factory is built against a specific failure: AI tends to flatten every thinker into a neat, polite, consulting-style answer. Mind Distill Factory uses several mechanisms to resist that.

First-person immersion means the Skill should not constantly say "Munger believed" or "Sun Tzu would advise." It should answer from the thinker's method, while staying within documented boundaries.

Expression DNA forces specificity. "Analytical," "strategic," and "direct" are not enough. The Skill must capture sentence shape, rhetorical habits, baseline tone, certainty, humor, taboos, paragraph rhythm, and conversational markers.

Structural naturalness prevents every response from becoming four balanced sections with equal-length paragraphs. The Skill is instructed to vary length, break symmetry, adapt depth to the prompt, and allow less polished transitions when that better fits the voice.

Constructive value orientation keeps the output useful. When a user brings grievance, failure, or unfairness, the Skill may acknowledge reality, but it should move toward agency, repair, discipline, or action instead of staying in complaint.

## Resemblance Is Not Enough

A Skill can sound like a thinker and still be weak. It may imitate catchphrases while failing to reason. It may quote accurately while being unable to handle a modern case. The factory therefore evaluates three layers:

| Layer | What it checks |
| --- | --- |
| Evidence | Whether the advice traces back to sources rather than invented authority. |
| Method | Whether new answers use the thinker's distinctive judgment moves. |
| Personhood | Whether rhythm, hesitation, force, restraint, and limits form a credible presence. |

The reviewer should ask hard questions. Could this paragraph be attributed to any generic productivity writer? Is the answer only an encyclopedia summary? Did the thinker's pain, hesitation, force, misjudgment, or unresolved tension actually enter the artifact? If not, the Skill is still a shell.

## Quality Gates

Before a Skill enters `gallery/`, it must pass checks for:

| Gate | Requirement |
| --- | --- |
| Source traceability | Principles and quotes point to named materials. Web-only quotes cannot be high confidence. |
| Uniqueness | The method must survive a de-name test, evidence-anchor test, and methodology-level test. |
| Decision framework | Steps must be filter-type yes/no gates, not open-ended prompts. |
| Bilingual cognition | Chinese and English frameworks are independently framed, not mechanically translated. |
| Blind spots | Each failure mode includes mitigation advice and "when not to use" guidance. |
| Expression DNA | The voice profile must distinguish this thinker from generic analytical prose. |
| Structural naturalness | Anti-template response-shape rules must be present and complete. |
| Values and anti-patterns | At least two pursued values, two rejected patterns, and one unresolved tension. |

## Evaluation And Soul Ten Questions

<p align="center">
  <img src="docs/assets/readme/runtime-evaluation-loop.svg" alt="Runtime evaluation loop" width="100%">
</p>

The `evaluation/` subtree is deliberately separate from the distillation pipeline. It can collect artifact facts, run DeepSeek-compatible runtime dialogue tests, judge outputs, and produce scorecards without changing the target Skill.

The newest runtime extension is the non-benchmark **Soul Ten Questions** appendix:

<p align="center">
  <img src="docs/assets/readme/soul-ten-questions.svg" alt="Soul Ten Questions appendix" width="100%">
</p>

After a full generated runtime test, DeepSeek can create a separate human-reading appendix. Ten fixed archetypes constrain coverage: regret, alternate historical road, principle-life contradiction, hardest compromise, misunderstood principle, decisive moment, unique personality wisdom, warning against imitation, modern-use boundary, and final self-judgment. The actual questions are tailored to the thinker's history, tensions, blind spots, principles, and expressive personality.

The appendix writes:

```text
evaluation/reports/{slug}/ten-question-qa.json
evaluation/reports/{slug}/ten-question-qa.md
evaluation/reports/{slug}/ten-question-summary.md
```

These files are explicitly non-scored. They do not alter `runtime-judgment.json`, `runtime_score_25`, score caps, grades, release language, or benchmark readiness. Their job is to leave the user with something more human than a number.

The ten archetypes are:

| Archetype | What it tries to reveal |
| --- | --- |
| regret | The wound that remains when the life is reconsidered. |
| alternate historical road | How the thinker would re-evaluate a different path through history. |
| principle-life contradiction | Where a doctrine was contradicted or strained by the life behind it. |
| hardest compromise | The bargain that exposes the cost of the method. |
| misunderstood principle | The teaching later users are most likely to flatten or misuse. |
| decisive moment | The moment that formed the judgment architecture. |
| unique personality wisdom | A personality trait that is itself a source of wisdom. |
| warning against imitation | What should not be copied, because copying it would harm the user. |
| modern-use boundary | Where the method should stop in contemporary use. |
| final self-judgment | What the thinker might say if asked to render a verdict on himself. |

This part is deliberately not scored. Scores can warn, but they cannot replace the user's own reading of whether an answer has the weight of a living mind.

## Usage

Run local tests:

```powershell
python -m unittest discover -s tests -v
```

Use the `/distill` command in a Codex workflow:

```text
/distill "Charlie Munger"
/distill Sun Tzu
/distill 王阳明
```

Validate stages manually:

```powershell
python scripts\validate_output.py sources charlie-munger
python scripts\validate_output.py principles mao-zedong
python scripts\validate_output.py frameworks mao-zedong
python scripts\validate_output.py skill mao-zedong
python scripts\validate_output.py gallery mao-zedong
```

Configure runtime evaluation:

```powershell
Copy-Item evaluation\runtime\.env.example evaluation\runtime\.env
# Edit evaluation\runtime\.env locally. Do not commit it.

python evaluation\runtime\run_dialogue_eval.py --slug zeng-guofan --root . --ten-questions auto
python evaluation\scripts\collect_artifacts.py --slug zeng-guofan --root . --out evaluation\reports\zeng-guofan\artifact-facts.json
```

For offline engineering checks:

```powershell
$env:MIND_DISTILL_EVAL_LLM = "off"
python -m unittest discover -s tests -v
```

Common runtime settings:

| Variable | Meaning |
| --- | --- |
| `MIND_DISTILL_EVAL_LLM=off` | Never call an external model. Best for local tests. |
| `MIND_DISTILL_EVAL_LLM=auto` | Call an external model only when a key exists. |
| `MIND_DISTILL_EVAL_LLM=deepseek` | Require a DeepSeek-compatible API. |
| `MIND_DISTILL_EVAL_API_KEY` | Evaluation-only API key. It should not appear in reports. |
| `MIND_DISTILL_EVAL_BASE_URL` | Defaults to `https://api.deepseek.com`. |
| `MIND_DISTILL_EVAL_MODEL` | Example default is `deepseek-v4-pro`. |
| `MIND_DISTILL_EVAL_REASONING_EFFORT` | Forwarded to compatible model APIs. |

When installing a Skill, keep the final filename as `SKILL.md`. A common Codex layout is:

```text
~/.codex/skills/{person-slug}-wisdom/SKILL.md
```

Do not install `SKILL.zh.md`, `README.md`, or draft files as the final Skill. Codex will not discover those as the active Skill entrypoint.

## Debate Arena

`debate_arena/` lets two Skills argue through structured roles: profiler, topic generator, debaters, fact checker, and judge. It is useful for seeing how two distilled methods diverge when they face the same problem.

Dry run:

```powershell
python -m debate_arena run --llm fake --issues 3 --out output\debate_arena\dry_run.md
```

For real runs, set `DEBATE_ARENA_API_KEY` or `OPENAI_API_KEY`. See [debate_arena/README.md](debate_arena/README.md).

## Gallery

The public gallery currently includes:

| Thinker | Primary use |
| --- | --- |
| Charlie Munger | Multidisciplinary mental models, inversion, business and investment judgment. |
| Chiang Kai-shek | Strategic endurance, organizational reform, weak-side diplomacy, self-discipline. |
| Mao Zedong | Contradiction analysis, investigation, underdog strategy, protracted struggle. |
| Richard Feynman | First principles, scientific honesty, learning by explanation. |
| Sun Tzu | Competitive strategy, positioning, deception, timing, force economy. |
| Wang Yangming | Innate knowing, unity of knowledge and action, moral self-cultivation. |
| Zeng Guofan | Self-discipline, talent judgment, resilience, strategic patience. |

## Public Release Boundary

This repository is the public engineering surface. It includes templates, orchestration contracts, evaluator code, gallery Skills, README visuals, and tests. It intentionally excludes:

- `.env`, `evaluation/runtime/.env`, and all API keys.
- Local evaluation reports under `evaluation/reports/`.
- Intermediate outputs under `output/`.
- Release-video working files.
- Copyrighted books, PDFs, scans, recordings, private archives, or local source corpora.

## Repository Map

```text
agents/         Subagent contracts for extraction, synthesis, review, and assembly
commands/       The /distill orchestration command
config/         Taxonomy and defaults
debate_arena/   Two-Skill debate runner
docs/assets/    Public README and project images
evaluation/     Standalone SkillEval-MDF evaluator
gallery/        Released installable Skills
scripts/        Validators, source processing, and utility scripts
sources/        Public placeholder plus local-source contract
templates/      Skill templates and hand-crafted examples
tests/          Regression tests
```

## License

Code and documentation are released under the MIT License. The thinkers' works belong to their authors and rights holders; the open-source contribution here is the distillation method, engineering pipeline, and reusable Skill structure.
