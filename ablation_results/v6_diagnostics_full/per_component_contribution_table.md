# V6 Component Ablation — Rank-Distance Diagnostics

**Generated:** 2026-04-25 19:39  
**Protocol:** Scoring-layer ablation; L1 detection held constant across all variants

---

## 1. Per-Component Contribution Table

Positive Δ = component **helps** (removing it hurts performance).

| component_disabled | Δ_P@5 | Δ_nDCG@5 | Δ_MAP | Δ_MRR | avg_score_perturbation | pct_rank_changed |
| --- | --- | --- | --- | --- | --- | --- |
| w/o Adaptive Alpha | 0.0 | 0.0 | 0.0 | 0.0 | 0.062802 | 98.5 |
| w/o Bayesian Prior | 0.0 | 0.0 | 0.0 | 0.0 | 0.062802 | 98.5 |
| w/o IDF Specificity | 0.0 | 0.0 | 0.0 | 0.0 | 0.062802 | 98.5 |
| w/o Margin Activation | 0.0 | 0.0 | 0.0 | 0.0 | 0.062802 | 98.5 |
| w/o KL Penalty | 0.0 | 0.0 | 0.0 | 0.0 | 0.062802 | 98.5 |
| w/o Negation Gate | 0.0 | 0.0 | 0.0 | 0.0 | 0.062802 | 98.5 |
| Product Feature Mode | 0.0 | 0.0 | 0.0 | 0.0 | 0.062802 | 98.5 |

---

## 2. Statistical Significance (Full V6 vs Variant)

| variant | metric | p_value | significant |
| --- | --- | --- | --- |
| w/o Adaptive Alpha | nDCG@5 | 1.0 | False |
| w/o Bayesian Prior | nDCG@5 | 1.0 | False |
| w/o IDF Specificity | nDCG@5 | 1.0 | False |
| w/o Margin Activation | nDCG@5 | 1.0 | False |
| w/o KL Penalty | nDCG@5 | 1.0 | False |
| w/o Negation Gate | nDCG@5 | 1.0 | False |
| Product Feature Mode | nDCG@5 | 1.0 | False |

---

## 3. Score-Level Distance (Full V6 vs Ablated)

| variant | mean_score_diff | max_score_diff | n_cases_changed | pct_cases_changed | n_cases |
| --- | --- | --- | --- | --- | --- |
| w/o Adaptive Alpha | 0.0 | 0.0 | 0 | 0.0 | 68 |
| w/o Bayesian Prior | 0.0 | 0.0 | 0 | 0.0 | 68 |
| w/o IDF Specificity | 0.0 | 0.0 | 0 | 0.0 | 68 |
| w/o Margin Activation | 0.0 | 0.0 | 0 | 0.0 | 68 |
| w/o KL Penalty | 0.0 | 0.0 | 0 | 0.0 | 68 |
| w/o Negation Gate | 0.0 | 0.0 | 0 | 0.0 | 68 |
| Product Feature Mode | 0.0 | 0.0 | 0 | 0.0 | 68 |

---

## 3. Top-5 Rank Swap Summary

| variant | n_rank_changed | n_total | pct_rank_changed |
| --- | --- | --- | --- |
| w/o Adaptive Alpha | 67 | 68 | 98.5 |
| w/o Bayesian Prior | 67 | 68 | 98.5 |
| w/o IDF Specificity | 67 | 68 | 98.5 |
| w/o Margin Activation | 67 | 68 | 98.5 |
| w/o KL Penalty | 67 | 68 | 98.5 |
| w/o Negation Gate | 67 | 68 | 98.5 |
| Product Feature Mode | 67 | 68 | 98.5 |

---

## 4. Score Perturbation by Variant

| variant | mean_abs_delta | std_delta | max_delta | n_nonzero |
| --- | --- | --- | --- | --- |
| w/o Adaptive Alpha | 0.062802 | 0.021911 | 0.144863 | 68 |
| w/o Bayesian Prior | 0.062802 | 0.021911 | 0.144863 | 68 |
| w/o IDF Specificity | 0.062802 | 0.021911 | 0.144863 | 68 |
| w/o Margin Activation | 0.062802 | 0.021911 | 0.144863 | 68 |
| w/o KL Penalty | 0.062802 | 0.021911 | 0.144863 | 68 |
| w/o Negation Gate | 0.062802 | 0.021911 | 0.144863 | 68 |
| Product Feature Mode | 0.062802 | 0.021911 | 0.144863 | 68 |

---

## 5. Slice Analysis

| slice | variant | metric | Full_V6_mean | ablated_mean | delta | n_cases |
| --- | --- | --- | --- | --- | --- | --- |
| high_severity | w/o Adaptive Alpha | nDCG@5 | 0.3252 | 0.3252 | 0.0 | 19 |
| high_severity | w/o Adaptive Alpha | MAP | 0.2976 | 0.2976 | 0.0 | 19 |
| high_severity | w/o Adaptive Alpha | MRR | 0.3242 | 0.3242 | 0.0 | 19 |
| high_severity | w/o Bayesian Prior | nDCG@5 | 0.3252 | 0.3252 | 0.0 | 19 |
| high_severity | w/o Bayesian Prior | MAP | 0.2976 | 0.2976 | 0.0 | 19 |
| high_severity | w/o Bayesian Prior | MRR | 0.3242 | 0.3242 | 0.0 | 19 |
| high_severity | w/o IDF Specificity | nDCG@5 | 0.3252 | 0.3252 | 0.0 | 19 |
| high_severity | w/o IDF Specificity | MAP | 0.2976 | 0.2976 | 0.0 | 19 |
| high_severity | w/o IDF Specificity | MRR | 0.3242 | 0.3242 | 0.0 | 19 |
| high_severity | w/o Margin Activation | nDCG@5 | 0.3252 | 0.3252 | 0.0 | 19 |
| high_severity | w/o Margin Activation | MAP | 0.2976 | 0.2976 | 0.0 | 19 |
| high_severity | w/o Margin Activation | MRR | 0.3242 | 0.3242 | 0.0 | 19 |
| high_severity | w/o KL Penalty | nDCG@5 | 0.3252 | 0.3252 | 0.0 | 19 |
| high_severity | w/o KL Penalty | MAP | 0.2976 | 0.2976 | 0.0 | 19 |
| high_severity | w/o KL Penalty | MRR | 0.3242 | 0.3242 | 0.0 | 19 |
| high_severity | w/o Negation Gate | nDCG@5 | 0.3252 | 0.3252 | 0.0 | 19 |
| high_severity | w/o Negation Gate | MAP | 0.2976 | 0.2976 | 0.0 | 19 |
| high_severity | w/o Negation Gate | MRR | 0.3242 | 0.3242 | 0.0 | 19 |
| high_severity | Product Feature Mode | nDCG@5 | 0.3252 | 0.3252 | 0.0 | 19 |
| high_severity | Product Feature Mode | MAP | 0.2976 | 0.2976 | 0.0 | 19 |
| high_severity | Product Feature Mode | MRR | 0.3242 | 0.3242 | 0.0 | 19 |
| complex_cases | w/o Adaptive Alpha | nDCG@5 | 0.5174 | 0.5174 | 0.0 | 20 |
| complex_cases | w/o Adaptive Alpha | MAP | 0.5186 | 0.5186 | 0.0 | 20 |
| complex_cases | w/o Adaptive Alpha | MRR | 0.5889 | 0.5889 | 0.0 | 20 |
| complex_cases | w/o Bayesian Prior | nDCG@5 | 0.5174 | 0.5174 | 0.0 | 20 |
| complex_cases | w/o Bayesian Prior | MAP | 0.5186 | 0.5186 | 0.0 | 20 |
| complex_cases | w/o Bayesian Prior | MRR | 0.5889 | 0.5889 | 0.0 | 20 |
| complex_cases | w/o IDF Specificity | nDCG@5 | 0.5174 | 0.5174 | 0.0 | 20 |
| complex_cases | w/o IDF Specificity | MAP | 0.5186 | 0.5186 | 0.0 | 20 |
| complex_cases | w/o IDF Specificity | MRR | 0.5889 | 0.5889 | 0.0 | 20 |
| complex_cases | w/o Margin Activation | nDCG@5 | 0.5174 | 0.5174 | 0.0 | 20 |
| complex_cases | w/o Margin Activation | MAP | 0.5186 | 0.5186 | 0.0 | 20 |
| complex_cases | w/o Margin Activation | MRR | 0.5889 | 0.5889 | 0.0 | 20 |
| complex_cases | w/o KL Penalty | nDCG@5 | 0.5174 | 0.5174 | 0.0 | 20 |
| complex_cases | w/o KL Penalty | MAP | 0.5186 | 0.5186 | 0.0 | 20 |
| complex_cases | w/o KL Penalty | MRR | 0.5889 | 0.5889 | 0.0 | 20 |
| complex_cases | w/o Negation Gate | nDCG@5 | 0.5174 | 0.5174 | 0.0 | 20 |
| complex_cases | w/o Negation Gate | MAP | 0.5186 | 0.5186 | 0.0 | 20 |
| complex_cases | w/o Negation Gate | MRR | 0.5889 | 0.5889 | 0.0 | 20 |
| complex_cases | Product Feature Mode | nDCG@5 | 0.5174 | 0.5174 | 0.0 | 20 |
| complex_cases | Product Feature Mode | MAP | 0.5186 | 0.5186 | 0.0 | 20 |
| complex_cases | Product Feature Mode | MRR | 0.5889 | 0.5889 | 0.0 | 20 |
| simple_cases | w/o Adaptive Alpha | nDCG@5 | 0.0894 | 0.0894 | 0.0 | 16 |
| simple_cases | w/o Adaptive Alpha | MAP | 0.0781 | 0.0781 | 0.0 | 16 |
| simple_cases | w/o Adaptive Alpha | MRR | 0.0781 | 0.0781 | 0.0 | 16 |
| simple_cases | w/o Bayesian Prior | nDCG@5 | 0.0894 | 0.0894 | 0.0 | 16 |
| simple_cases | w/o Bayesian Prior | MAP | 0.0781 | 0.0781 | 0.0 | 16 |
| simple_cases | w/o Bayesian Prior | MRR | 0.0781 | 0.0781 | 0.0 | 16 |
| simple_cases | w/o IDF Specificity | nDCG@5 | 0.0894 | 0.0894 | 0.0 | 16 |
| simple_cases | w/o IDF Specificity | MAP | 0.0781 | 0.0781 | 0.0 | 16 |
| simple_cases | w/o IDF Specificity | MRR | 0.0781 | 0.0781 | 0.0 | 16 |
| simple_cases | w/o Margin Activation | nDCG@5 | 0.0894 | 0.0894 | 0.0 | 16 |
| simple_cases | w/o Margin Activation | MAP | 0.0781 | 0.0781 | 0.0 | 16 |
| simple_cases | w/o Margin Activation | MRR | 0.0781 | 0.0781 | 0.0 | 16 |
| simple_cases | w/o KL Penalty | nDCG@5 | 0.0894 | 0.0894 | 0.0 | 16 |
| simple_cases | w/o KL Penalty | MAP | 0.0781 | 0.0781 | 0.0 | 16 |
| simple_cases | w/o KL Penalty | MRR | 0.0781 | 0.0781 | 0.0 | 16 |
| simple_cases | w/o Negation Gate | nDCG@5 | 0.0894 | 0.0894 | 0.0 | 16 |
| simple_cases | w/o Negation Gate | MAP | 0.0781 | 0.0781 | 0.0 | 16 |
| simple_cases | w/o Negation Gate | MRR | 0.0781 | 0.0781 | 0.0 | 16 |
| simple_cases | Product Feature Mode | nDCG@5 | 0.0894 | 0.0894 | 0.0 | 16 |
| simple_cases | Product Feature Mode | MAP | 0.0781 | 0.0781 | 0.0 | 16 |
| simple_cases | Product Feature Mode | MRR | 0.0781 | 0.0781 | 0.0 | 16 |

---

## Interpretation Notes

- Binary relevance metrics (P@5, nDCG@5) may show **zero difference** when top-5 documents remain identical
- Score-level delta and rank swap count capture **finer-grained** component effects
- Components with Δ ≈ 0 may have synergistic effects — removing them alone doesn't capture interaction
- Slice analysis is exploratory for n_cases < 10
- Protocol: L1 detection is held constant; only scoring-layer V6 components are toggled