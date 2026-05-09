# Q1 Submission Gap Closure Plan

This checklist translates the current artifacts into concrete actions before making Q1-level claims.

## Current Evidence Status

| Area | Current status | Q1 interpretation |
|---|---|---|
| Split leakage | Fixed with family-level split; audit reports 0 cross-split families and 0 near-duplicates | Usable |
| Retrieval evaluation | 8/8 strategies completed on 68 leakage-safe test cases | Usable with conservative claims |
| Main supported result | H2L-BM25 improves nDCG@5 over BM25, delta +0.0359, p = 0.0131 | Strongest quantitative claim |
| Hybrid/HyDE results | Positive mean deltas on selected metrics but not significant | Trend-only |
| Sentence polarity | Accuracy 0.8824, NDR 0.7222, FPR 0.0600, F1 0.7647 | Usable as safety evidence, with limitation on long text |
| V6 ablation | Fixed-candidate ablation complete on the full 197-case dataset for score-level analysis (rank-aware metrics on the 68-case test split show no variation across variants); only Product Mode (large effect, $d=0.932$) and Adaptive Alpha (small effect, $d=0.409$) reach practical significance, while the remaining toggles show negligible effect sizes despite passing the paired Wilcoxon test | Usable as score-level component sensitivity evidence, with practical effects limited to two components |
| Blind expert evaluation | Packet generated but not scored | Not yet usable as result |

## Claims Allowed Now

- H2L provides a statistically supported nDCG@5 gain for the BM25 backbone on the leakage-safe split.
- H2L-Hybrid and H2L-HyDE show trend-level improvements on selected MAP/MRR metrics, but broad superiority is not yet supported.
- The polarity gate improves safety-oriented negation handling, but long negated narratives remain a limitation.
- The current system is best framed as a problem-aware scoring and safety layer with practical component effects concentrated on the Weighted-Sum architecture and Adaptive Alpha, not a universal retrieval booster.

## Claims To Avoid Until More Evidence

- Do not claim H2L is superior to all baselines.
- Do not claim that V6 component effects automatically prove broad end-to-end retrieval superiority; the ablation supports score-level sensitivity and scoring-layer causality.
- Do not claim clinical usability has been validated until blind expert scoring is complete.
- Do not merge generated/paraphrase/adversarial cases into broad real-world generalization claims without reporting them as stress-test slices.

## Required Before Q1 Submission

1. Complete blind expert scoring with at least 3 domain experts.
2. Analyze expert scores with paired comparison and Human-AI Agreement / inter-rater agreement.

## Operational Housekeeping

- Keep `q1_readiness_report.md`, `ground_truth_audit.md`, `paper_tables.tex`, and `ablation_results/q1_figures/` synchronized immediately before submission.

## Manuscript Positioning

Recommended positioning:

> H2L is a transparent, problem-aware scoring and safety layer for Thai social-work case retrieval. It provides a supported gain for BM25 on nDCG@5, trend-level gains for selected semantic/hybrid backbones, a dedicated polarity gate that reduces negation-related false positives, and fixed-candidate V6 ablation evidence showing score-level sensitivity across toggles. The remaining validation step is blind expert scoring for Human-AI Agreement; the system is not claimed to be universally superior across all retrieval backbones.

This framing is much safer for Q1 review than claiming global model superiority, while reflecting that the fixed-candidate V6 ablation has already been completed (full-dataset score-level analysis, with the 68-case test split showing zero rank-metric variation across variants and therefore acting as a sanity check rather than the primary evidence source).
