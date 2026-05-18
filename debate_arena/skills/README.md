# Debate Participants

Put the two Skills you want to debate in this folder:

```text
skills/
  skill_a/
    SKILL.md
  skill_b/
    SKILL.md
```

Then run from the project root:

```powershell
python -m debate_arena run
```

`skill_a` becomes Side A and `skill_b` becomes Side B. Keep the filename exactly `SKILL.md`.

The prompt templates in `debate_arena/prompts/` are internal runtime prompts. Do not put participating Skills there.

