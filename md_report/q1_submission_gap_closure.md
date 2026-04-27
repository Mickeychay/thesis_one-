# Q1 Submission Gap Closure Plan

This checklist translates the current artifacts into concrete actions before making Q1-level claims.

## Current Evidence Status

| Area | Current status | Q1 interpretation |
|---|---|---|
| Split leakage | Fixed with family-level split; audit reports 0 cross-split families and 0 near-duplicates | Usable |
| Retrieval evaluation | 8/8 strategies completed on 68 leakage-safe test cases | Usable with conservative claims |
| Main supported result | H2L-BM25 improves nDCG@5 over BM25, delta +0.0359, p = 0.0131 | Strongest quantitative claim |
| Hybrid/HyDE results | Positive mean deltas on selected metrics but not significant | Trend-only |
| Sentence polarity | Accuracy 0.8824, NDR 0.7222, FPR 0.0600, F1 0.7650 | Usable as safety evidence, with limitation on long text |
| V6 ablation | Fixed-candidate cached run complete on 20 cases, 160 rows; toggles change H2L scores and top-5 order in 15% of cases, but rank-aware relevance metrics remain identical across variants | Component sensitivity evidence only |
| Blind expert evaluation | Packet generated but not scored | Not yet usable as result |

## Claims Allowed Now

- H2L provides a statistically supported nDCG@5 gain for the BM25 backbone on the leakage-safe split.
- H2L-Hybrid and H2L-HyDE show trend-level improvements on selected MAP/MRR metrics, but broad superiority is not yet supported.
- The polarity gate improves safety-oriented negation handling, but long negated narratives remain a limitation.
- The current system is best framed as a problem-aware scoring and safety layer, not a universal retrieval booster.

## Claims To Avoid Until More Evidence

- Do not claim H2L is superior to all baselines.
- Do not claim V6 component causality from the current fixed-candidate ablation; it supports score sensitivity, not retrieval effectiveness causality.
- Do not claim clinical usability has been validated until blind expert scoring is complete.
- Do not merge generated/paraphrase/adversarial cases into broad real-world generalization claims without reporting them as stress-test slices.

## Required Before Q1 Submission

1. Complete blind expert evaluation with at least 3 domain experts.
2. Analyze expert scores with paired comparison and inter-rater agreement.
3. Extend V6 ablation from 20 cases to the full leakage-safe test split and add rank-distance / score-calibration diagnostics.
4. Add an external holdout set or clearly limit claims to the current benchmark.
5. Report generated, paraphrase, adversarial, and polarity cases as separate slices.
6. Keep `q1_readiness_report.md`, `ground_truth_audit.md`, and `paper_tables.tex` regenerated immediately before submission.

## Manuscript Positioning

Recommended positioning:

> H2L is a transparent, problem-aware scoring and safety layer for Thai social-work case retrieval. It provides a supported gain for BM25 on nDCG@5, trend-level gains for selected semantic/hybrid backbones, and a dedicated polarity gate that reduces negation-related false positives. The system is not claimed to be universally superior across all retrieval backbones.

This framing is much safer for Q1 review than claiming global model superiority.
