# Ground Truth Audit

- Source: `expanded_ground_truth.json`
- Total cases: 197
- Split counts: `{'train': 129, 'test': 68}`
- Augmentation counts: `{'original': 92, 'paraphrase': 44, 'complexity_escalation': 10, 'complexity_reduction': 10, 'adversarial': 5, 'polarity': 36}`
- Risk flags: `['generated_cases_present_report_separately']`

## Cross-Split Families

No train/test family overlap detected.

## Near Duplicates Across Splits

No near-duplicate train/test pairs above threshold.

## Recommendation

Use group/family-level splits and report generated/adversarial/polarity cases as separate stress-test slices before making Q1-level generalization claims.
