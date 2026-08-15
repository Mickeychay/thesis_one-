# Ground Truth Audit

- Source: `data/expanded_ground_truth.json`
- Total cases: 225
- Split counts: `{'train': 125, 'test': 100}`
- Augmentation counts: `{'original': 105, 'paraphrase': 44, 'complexity_escalation': 10, 'complexity_reduction': 10, 'adversarial': 20, 'polarity': 36}`
- Risk flags: `['generated_cases_present_report_separately']`

## Cross-Split Families

No train/test family overlap detected.

## Exact Duplicate Descriptions

No identical normalized case descriptions detected.

## Near Duplicates Across Splits

No near-duplicate train/test pairs above threshold.

## Recommendation

Use group/family-level splits and report generated/adversarial/polarity cases as separate stress-test slices before making Q1-level generalization claims.
