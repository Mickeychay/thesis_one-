# Blind Expert Evaluation Protocol

## Purpose

This protocol evaluates whether retrieved evidence is useful for social-work case reasoning, independent of the system name. Evaluators should judge the evidence shown in each row without knowing whether it came from a baseline or H2L system.

## Evaluators

- Recommended minimum: 3 domain experts.
- Preferred: 3-5 experts with experience in medical social work, case screening, psychosocial assessment, or related clinical/social-service review.
- Evaluators must not access `blind_mapping.hidden.json` before scoring is locked.

## Materials

- `evaluation_form.csv`: scoring form to distribute.
- `evaluation_rubric.md`: score definitions.
- `evaluation_cases.json`: case metadata for audit.
- `blind_mapping.hidden.json`: hidden mapping for analysis only.

## Scoring Dimensions

Each row receives 1-5 scores for:

1. Relevance: whether the retrieved documents relate to the case problem.
2. Completeness: whether the documents cover the important dimensions of the case.
3. Clinical usefulness: whether the documents would help planning, referral, verification, or case discussion.

Free-text comments should identify missing evidence, unsafe evidence, misleading retrieval, or cases where both systems are equally useful.

## Procedure

1. Assign each evaluator a copy of `evaluation_form.csv`.
2. Ask evaluators to fill only `evaluator_id`, the three score columns, and `comments`.
3. Do not reveal system identities or expected labels during scoring.
4. Merge completed CSV files into one file after all evaluators finish.
5. Analyze using:

```bash
python scripts/human_eval_framework.py analyze <merged_expert_scores.csv>
```

6. Unblind only after the merged analysis file is saved.

## Reporting Policy

Report:

- number of experts
- number of cases and rows scored
- mean and standard deviation per system
- paired comparison between blinded systems
- inter-rater agreement if available
- representative qualitative comments

Do not claim expert-validated superiority unless the paired result and qualitative comments both support it. If scores are close, report the result as practical tie or trend-only.

## Data Handling

The case descriptions are research artifacts. Do not add patient-identifying information. If an evaluator notices identifiable details, redact them before sharing the merged file.
