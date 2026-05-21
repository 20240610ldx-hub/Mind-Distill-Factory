---
name: mind-skill-evaluator
description: Evaluate Mind Distill Factory thinker wisdom skills, persona skills, workflow skills, and runtime dialogue logs. Use when producing SkillEval-MDF-v1.1 scorecards, DeepSeek runtime stress tests, Q/A dialogue test set Markdown files, initial post-distillation assessments, failure-mode diagnostics, release recommendations, or P0/P1/P2 improvement roadmaps for generated SKILL.md artifacts.
---

# Mind Skill Evaluator

Use this skill to evaluate distilled thinker Skills independently from the `/distill` pipeline. Do not edit the workflow, gallery, or target Skill while evaluating. Read the target artifacts, collect evidence, score with `SkillEval-MDF-v1.1`, and produce a report whose field names, metric names, grade labels, and JSON keys are in English.

## Inputs

Prefer evidence in this order:

1. `output/{slug}/SKILL.md`
2. `output/{slug}/frameworks.zh.json` and `output/{slug}/frameworks.en.json`
3. `output/{slug}/principles_*.json`
4. `output/{slug}/review.md`
5. `output/{slug}/dialogue_test*.md`
6. `gallery/{slug}/SKILL.md`
7. `gallery/index.json`

If only `SKILL.md` is available, perform a `Design-Only Evaluation`. If DeepSeek runtime judgment is available, perform a `Full Runtime Evaluation`. If only imported or legacy dialogue logs are available, mark runtime claims as provisional. If the Skill has just been distilled and no dialogue logs exist, perform an `Initial Evaluation`.

## Rubric

Score out of 100 with `SkillEval-MDF-v1.1`. Be strict: section presence is not enough for a high score. Runtime behavior, evidence quality, and artifact integrity must create separation between good, strong, and benchmark-ready Skills.

| Metric | Weight |
|---|---:|
| Source Fidelity | 12 |
| Cognitive Distillation Depth | 12 |
| Operational Decision Utility | 12 |
| Voice & Embodiment Authenticity | 12 |
| Boundary & Misuse Resistance | 12 |
| Runtime Robustness & Generalization | 25 |
| Cross-Lingual & Cultural Fit | 8 |
| Engineering Reusability & Artifact Integrity | 7 |

Grades:

| Total | Grade | Meaning |
|---:|---|---|
| 90-100 | S | benchmark-ready |
| 85-89 | A- | strong but not benchmark-ready |
| 80-84 | A | release-ready with minor refinements |
| 70-79 | B | promising, needs targeted revision |
| 60-69 | C | usable prototype, unstable |
| 50-59 | D | prompt-like, not skill-like |
| 0-49 | F | not recommended |

Critical gates cap the total at `C`: fabricated source attribution, no discoverable `SKILL.md`, no source lineage, harmful manipulation or unsafe advice, or pretending a historical thinker personally witnessed posthumous events. State the cap explicitly in the report.

Strictness caps:

- If no DeepSeek runtime judgment exists, the total score is capped at `B`.
- If only imported dialogue logs exist and they do not cover the full 12-case set, the total score is capped at `A-`.
- If only one automated DeepSeek judge is used, cap perfection claims: runtime cannot score as flawless in the final scorecard, and total score above `94` requires human audit or a second judge.
- `S` requires total score >= 92, runtime >= 21/25, source fidelity >= 10/12, engineering integrity >= 6/7, and no P0/P1 blockers.
- Artifact drift, such as output/gallery hash mismatch, prevents `benchmark-ready` release language.

## Report Contract

Always include:

- `Executive Review`
- `Visual Scorecard`
- `Detailed Metric Review`
- `Initial Post-Distillation Assessment`
- `Failure Modes`
- `Release Recommendation`
- `P0/P1/P2 Roadmap`

Use Markdown tables with these exact column names for scorecards: `Metric`, `Score`, `Weight`, `Grade`, `Evidence`, `Bar`. Use a 15-cell ASCII bar with `#` and `-`.

Each metric must include evidence, deductions, and fix priority. Do not give a score without showing why. If evidence is missing, say `Not enough evidence` and describe the missing artifact.

## Deterministic Helper

When working inside the Mind Distill Factory repo, prefer the bundled evaluator script:

```bash
python evaluation/scripts/collect_artifacts.py --slug <slug> --root . --out evaluation/reports/<slug>/artifact-facts.json
```

The script reads artifacts, runs existing validation checks when available, and writes:

- `artifact-facts.json`
- `scorecard.json`
- `initial-evaluation.md`

It must not modify `output/`, `gallery/`, `sources/`, `commands/`, or `agents/`.

## DeepSeek Runtime Test

To run the 12-case runtime pressure test:

```bash
python evaluation/runtime/run_dialogue_eval.py --slug <slug> --root .
python evaluation/scripts/collect_artifacts.py --slug <slug> --root . --out evaluation/reports/<slug>/artifact-facts.json
```

Environment:

- By default, the runtime loads `evaluation/runtime/.env` when present.
- `MIND_DISTILL_EVAL_LLM=off` disables all external LLM calls. Use this for static review, imported dialogue normalization, or human-only evaluation.
- `MIND_DISTILL_EVAL_LLM=deepseek` enables generated runtime tests and judge scoring through the configured DeepSeek-compatible API.
- `MIND_DISTILL_EVAL_API_KEY` is required for generated tests or judge scoring. `DEEPSEEK_API_KEY` remains supported as a backward-compatible alias.
- `MIND_DISTILL_EVAL_BASE_URL` defaults to `https://api.deepseek.com`.
- `MIND_DISTILL_EVAL_MODEL` defaults to `deepseek-v4-pro`.
- `MIND_DISTILL_EVAL_REASONING_EFFORT` defaults to `max`.
- Use `--env-file <path>` to load a different env file, or `--no-env-file` to rely only on process environment variables.

Runtime output contract:

- `runtime-dialogue-test.md` is the authoritative human-readable test set. It must contain only visible `Q` / `A` dialogue, never `reasoning_content`.
- `runtime-judgment.json` stores judge scores and metadata with English JSON keys.
- `runtime-evaluation.md` summarizes runtime failure modes.

## Soul Ten Questions Appendix

After a full generated DeepSeek runtime test, the runtime also creates a non-benchmark appendix by default:

- `ten-question-qa.json` uses schema `MindDistillSoulQuestions-v1` and must set `benchmark_included: false`.
- `ten-question-qa.md` is the human-readable Q/A dialogue.
- `ten-question-summary.md` is a brief subjective reading note, not a scorecard.

This appendix is intentionally separate from SkillEval-MDF scoring. It must not change `runtime-judgment.json`, `runtime_score_25`, score caps, grades, or benchmark-ready language. Treat it as a user-facing mirror for private judgment: the ten fixed archetypes cover regret, alternate historical road, principle-life contradiction, hardest compromise, misunderstood principle, decisive moment, unique personality wisdom, warning against imitation, modern-use boundary, and final self-judgment.

Control it with:

```bash
python evaluation/runtime/run_dialogue_eval.py --slug <slug> --root . --ten-questions auto
python evaluation/runtime/run_dialogue_eval.py --slug <slug> --root . --ten-questions on
python evaluation/runtime/run_dialogue_eval.py --slug <slug> --root . --ten-questions off
```

`auto` runs only after a full generated runtime test. It skips smoke tests, limited runs, imported logs, and judge-existing-runtime runs unless `--ten-questions on` is explicitly used.

To normalize existing logs without calling the API:

```bash
python evaluation/runtime/run_dialogue_eval.py --slug <slug> --root . --import-existing --no-judge
```
