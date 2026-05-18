# Debate Arena

Automated two-side debate runner for Mind Distill Factory `SKILL.md` files.

## Run

The easiest workflow is to place the two participating Skills here:

```text
debate_arena/
  skills/
    skill_a/
      SKILL.md
    skill_b/
      SKILL.md
```

Then run:

```powershell
python -m debate_arena run
```

This writes to `output/debate_arena/debate.md` by default. The file `prompts/debater.md` is only the internal prompt template for a debater role; it is not where participating Skills go.

You can still point to any two Skill files explicitly:

```powershell
python -m debate_arena run `
  --skill-a .\gallery\mao-zedong\SKILL.md `
  --skill-b .\gallery\richard-feynman\SKILL.md `
  --issues 4 `
  --language zh-CN `
  --judge true `
  --out .\output\debate_arena\demo_debate.md
```

Or use another participants folder with the same `skill_a/SKILL.md` and `skill_b/SKILL.md` layout:

```powershell
python -m debate_arena run `
  --participants-dir .\my_debate_skills `
  --out .\output\debate_arena\my_debate.md
```

Set `OPENAI_API_KEY` for real runs. Optional runtime variables:

- `DEBATE_ARENA_API_KEY` or `OPENAI_API_KEY`
- `DEBATE_ARENA_MODEL` or `OPENAI_MODEL`
- `DEBATE_ARENA_BASE_URL` or `OPENAI_BASE_URL`
- `DEBATE_ARENA_LLM=fake` for deterministic dry runs

## Env Files

By default the CLI loads `./.env` when it exists. You can also pass a specific env file:

```powershell
python -m debate_arena run `
  --env-file .\debate.local.env `
  --config .\debate_arena\examples\sample_config.yaml
```

Example:

```dotenv
DEBATE_ARENA_LLM=openai
DEBATE_ARENA_API_KEY=
DEBATE_ARENA_BASE_URL=https://api.openai.com/v1
DEBATE_ARENA_MODEL=gpt-4.1-mini
```

The arena currently uses one LLM configuration for all runtime roles: profiler, topic generator, both debaters, fact checker, and judge. The two debaters are separated by prompt, Skill text, profile, side position, and transcript context, not by separate API keys.

Dry run without an API key:

```powershell
python -m debate_arena run `
  --skill-a .\gallery\mao-zedong\SKILL.md `
  --skill-b .\gallery\richard-feynman\SKILL.md `
  --llm fake `
  --issues 3 `
  --fact-check true `
  --out .\output\debate_arena\dry_run.md
```

## Output

The Markdown transcript includes:

- metadata
- generated topic and rationale
- assigned positions
- 3-5 debate issues
- Q/A transcript for opening, issue arguments, rebuttal, cross-examination, and closing
- optional fact-check report
- judge report and Skill improvement suggestions

## Runtime Design

- `loader.py` loads local Skill files and fails clearly on missing or empty input.
- `llm_client.py` provides OpenAI-compatible and fake deterministic clients.
- `orchestrator.py` runs the debate flow.
- `render.py` acts as the deterministic Clerk and writes clean Q/A Markdown.
- `prompts/` contains role prompts for profiler, topic generator, debater, cross-examiner, fact checker, judge, moderator, and clerk.
