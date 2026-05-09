# Q1 Readiness Report

This report is generated from repository artifacts and uses conservative language by default.

## Artifact Provenance

- Proper evaluation timestamp: `2026-04-25T15:12:22.287599`
- Test cases: `68`
- Strategies: `bm25_only, naive_rag, hyde, basic, h2l-bm25, h2l-naive_rag, h2l-hyde, h2l-hybrid`
- Problem source: `detected`

## Main Pairwise Evidence

| Pair | Metric | Baseline | H2L | Delta | p-value | Verdict |
|---|---|---:|---:|---:|---:|---|
| bm25_only vs h2l-bm25 | MAP | 0.2196 | 0.2289 | +0.0093 | 0.9612 | practically_tied |
| bm25_only vs h2l-bm25 | MRR | 0.2697 | 0.2687 | -0.0010 | 0.4061 | practically_tied |
| bm25_only vs h2l-bm25 | nDCG@5 | 0.2079 | 0.2437 | +0.0359 | 0.0131 | supported |
| naive_rag vs h2l-naive_rag | MAP | 0.2003 | 0.1936 | -0.0067 | 0.1330 | practically_tied |
| naive_rag vs h2l-naive_rag | MRR | 0.2635 | 0.2703 | +0.0068 | 0.6002 | practically_tied |
| naive_rag vs h2l-naive_rag | nDCG@5 | 0.2034 | 0.1962 | -0.0072 | 0.1156 | practically_tied |
| hyde vs h2l-hyde | MAP | 0.1113 | 0.1479 | +0.0366 | 0.1443 | trend_only |
| hyde vs h2l-hyde | MRR | 0.1224 | 0.1697 | +0.0473 | 0.0800 | trend_only |
| hyde vs h2l-hyde | nDCG@5 | 0.1120 | 0.1405 | +0.0284 | 0.2894 | trend_only |
| basic vs h2l-hybrid | MAP | 0.2250 | 0.2362 | +0.0112 | 0.2668 | trend_only |
| basic vs h2l-hybrid | MRR | 0.2710 | 0.2893 | +0.0183 | 0.1230 | trend_only |
| basic vs h2l-hybrid | nDCG@5 | 0.2270 | 0.2290 | +0.0019 | 0.8590 | practically_tied |

## Safety And Validity Checks

- Polarity accuracy: `0.8824`
- Polarity F1: `0.7647`
- Negation detection rate: `0.7222`
- Negated cases: `18`
- Ground-truth audit risk flags: `['generated_cases_present_report_separately']`
- Cross-split families: `0`
- Near-duplicate train/test pairs: `0`

## V6 Ablation Evidence

> **Note on data source and reconciliation with thesis Table 4.5:**
> The aggregates in this section are derived from an earlier ablation snapshot
> retained for provenance. They differ from the numbers reported in the thesis
> Chapter 4, Table 4.5 because:
> - **Thesis Table 4.5** is computed from `ablation_results/rq6_results.csv`
>   (full 197-case dataset, n=197 per variant), used for score-level analysis
>   on `h2l_mean_top5` with adequate statistical power.
> - The 68-case leakage-safe test split runs
>   (`ablation_results/rq6_v6_final*/rq6_results.csv`) all produce identical
>   rank-aware metrics (`nDCG@5 = 0.4031`, `MAP = 0.4020`) across every
>   variant, confirming that on the test split component effects are observable
>   only at the score level, not at the rank level.
> - The numbers in the table below (`nDCG@5 = 0.3609`, `MAP = 0.3935`) reflect
>   the snapshot at the time this readiness report was generated and do not
>   match either run; treat **Table 4.5 in the thesis as the canonical
>   source** for component-level effect sizes.

- RQ6 ablation rows: `160`
- RQ6 variants: `8`
- Max |Δ nDCG@5| vs Full V6: `0.0000`

| Variant | MAP | MRR | nDCG@5 | rank_changed@5 | mean score delta |
|---|---:|---:|---:|---:|---:|
| Full V6 | 0.3935 | 0.4467 | 0.3609 | 15.0% | 0.5163 |
| Product Feature Mode | 0.3935 | 0.4467 | 0.3609 | 15.0% | 0.0230 |
| w/o Adaptive Alpha | 0.3935 | 0.4467 | 0.3609 | 15.0% | 0.2572 |
| w/o Bayesian Prior | 0.3935 | 0.4467 | 0.3609 | 15.0% | 0.6098 |
| w/o IDF Specificity | 0.3935 | 0.4467 | 0.3609 | 15.0% | 0.4330 |
| w/o KL Penalty | 0.3935 | 0.4467 | 0.3609 | 15.0% | 0.5172 |
| w/o Margin Activation | 0.3935 | 0.4467 | 0.3609 | 15.0% | 0.5117 |
| w/o Negation Gate | 0.3935 | 0.4467 | 0.3609 | 15.0% | 0.5197 |

Interpretation: this fixed-candidate ablation shows score/rank sensitivity through `rank_changed@5` and score deltas, but it still does not show component-level effectiveness differences on MAP/MRR/nDCG@5. Treat it as component sensitivity evidence rather than causal evidence.

## Conservative Claim Guidance

Do not claim broad superiority yet. Current evidence is best framed as trend-level or slice-specific, with explicit limitations around significance, generated cases, and keyword-derived relevance judgments.

Recommended next empirical steps:

1. Complete blinded expert relevance scoring with at least 3 domain experts.
2. Rerun family-level split audit and keep augmented/paraphrase cases as stress-test slices.
3. Extend V6 component ablation to the full leakage-safe test split and add rank-distance / score-calibration diagnostics.
4. Add an external holdout set before making generalization claims.

## Summary Counts

- Supported H2L metric comparisons: `1`
- Trend-only comparisons: `5`
- Practical ties: `6`
- Baseline-supported comparisons: `0`
