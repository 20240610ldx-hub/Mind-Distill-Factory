# SkillEval-MDF-v1.1 Evaluation Report

Skill: `{skill_name}`
Slug: `{slug}`
Evaluation Type: `{evaluation_type}`
Evaluation Date: `{evaluation_date}`
Evaluator: `mind-skill-evaluator`

## Executive Review

Overall Score: `{total_score}/100`
Grade: `{grade}` - `{grade_label}`
Release Recommendation: `{release_recommendation}`

One-line Judgment:
`{one_line_judgment}`

Strongest Advantage:
`{strongest_advantage}`

Largest Risk:
`{largest_risk}`

Next Priority:
`{next_priority}`

## Visual Scorecard

| Metric | Score | Weight | Grade | Evidence | Bar |
|---|---:|---:|---|---|---|
| Source Fidelity | `{source_fidelity}` | 12 | `{source_fidelity_grade}` | `{source_fidelity_evidence}` | `{source_fidelity_bar}` |
| Cognitive Distillation Depth | `{cognitive_distillation_depth}` | 12 | `{cognitive_distillation_depth_grade}` | `{cognitive_distillation_depth_evidence}` | `{cognitive_distillation_depth_bar}` |
| Operational Decision Utility | `{operational_decision_utility}` | 12 | `{operational_decision_utility_grade}` | `{operational_decision_utility_evidence}` | `{operational_decision_utility_bar}` |
| Voice & Embodiment Authenticity | `{voice_embodiment_authenticity}` | 12 | `{voice_embodiment_authenticity_grade}` | `{voice_embodiment_authenticity_evidence}` | `{voice_embodiment_authenticity_bar}` |
| Boundary & Misuse Resistance | `{boundary_misuse_resistance}` | 12 | `{boundary_misuse_resistance_grade}` | `{boundary_misuse_resistance_evidence}` | `{boundary_misuse_resistance_bar}` |
| Runtime Robustness & Generalization | `{runtime_robustness_generalization}` | 25 | `{runtime_robustness_generalization_grade}` | `{runtime_robustness_generalization_evidence}` | `{runtime_robustness_generalization_bar}` |
| Cross-Lingual & Cultural Fit | `{cross_lingual_cultural_fit}` | 8 | `{cross_lingual_cultural_fit_grade}` | `{cross_lingual_cultural_fit_evidence}` | `{cross_lingual_cultural_fit_bar}` |
| Engineering Reusability & Artifact Integrity | `{engineering_reusability_artifact_integrity}` | 7 | `{engineering_reusability_artifact_integrity_grade}` | `{engineering_reusability_artifact_integrity_evidence}` | `{engineering_reusability_artifact_integrity_bar}` |

## Detailed Metric Review

For each metric, include:

```text
Score:
Evidence:
Deductions:
Fix Priority:
```

## Initial Post-Distillation Assessment

State whether the artifact is `Design-Only`, `Initial`, `Legacy Dialogue Evidence`, `Imported Runtime Evaluation`, or `Full Runtime Evaluation`. If no DeepSeek runtime judgment exists, mark runtime conclusions as provisional and apply the score cap.
If only one automated runtime judge is used, cap perfection claims and state whether human audit is still required.

## Failure Modes

List at least three:

```text
Failure Mode:
Symptom:
Risk:
Repair:
```

## Release Recommendation

```text
Release Status:
Packaging:
README Selling Points:
Example Prompts:
Disclaimers:
```

## P0/P1/P2 Roadmap

```text
P0 Must Fix:
P1 Strongly Recommended:
P2 Later:
```
