# V6 Component Ablation — Rank-Distance Diagnostics

**Generated:** 2026-04-27 14:26  
**Protocol:** Scoring-layer ablation; L1 detection held constant across all variants

---

## 1. Per-Component Contribution Table

Positive Δ = component **helps** (removing it hurts performance).

| component_disabled | Δ_P@5 | Δ_nDCG@5 | Δ_MAP | Δ_MRR | avg_score_perturbation | pct_rank_changed |
| --- | --- | --- | --- | --- | --- | --- |
| w/o Margin Activation | -0.001015 | -0.001118 | -0.000671 | -0.000423 | 0.324747 | 15.7 |
| Product Feature Mode | -0.001015 | -0.000767 | -0.000127 | 0.0 | 0.020859 | 12.7 |
| w/o Adaptive Alpha | 0.0 | 0.0 | 0.0 | 0.0 | 0.179009 | 12.2 |
| w/o Bayesian Prior | 0.0 | 0.0 | 0.0 | 0.0 | 0.353307 | 12.7 |
| w/o IDF Specificity | 0.0 | 0.0 | 0.0 | 0.0 | 0.251216 | 12.7 |
| w/o KL Penalty | 0.0 | 0.0 | 0.0 | 0.0 | 0.33057 | 12.7 |
| w/o Negation Gate | 0.0 | 0.0 | 0.0 | 0.0 | 0.258053 | 12.7 |

---

## 2. Statistical Significance (Full V6 vs Variant)

| variant | metric | p_value | significant | effect_size_d | mean_diff |
| --- | --- | --- | --- | --- | --- |
| w/o Adaptive Alpha | nDCG@5 | 1.0 | False | 0.0 | 0.0 |
| w/o Bayesian Prior | nDCG@5 | 1.0 | False | 0.0 | 0.0 |
| w/o IDF Specificity | nDCG@5 | 1.0 | False | 0.0 | 0.0 |
| w/o Margin Activation | nDCG@5 | 0.1797 | False | -0.0949 | -0.001118 |
| w/o KL Penalty | nDCG@5 | 1.0 | False | 0.0 | 0.0 |
| w/o Negation Gate | nDCG@5 | 1.0 | False | 0.0 | 0.0 |
| Product Feature Mode | nDCG@5 | 0.3173 | False | -0.0714 | -0.000767 |
| w/o Adaptive Alpha | h2l_mean_top5 | 0.0 | True | 0.565 | 0.757022 |
| w/o Bayesian Prior | h2l_mean_top5 | 0.0 | True | -0.3954 | -0.119928 |
| w/o IDF Specificity | h2l_mean_top5 | 0.0 | True | 0.6788 | 0.40177 |
| w/o Margin Activation | h2l_mean_top5 | 0.0 | True | 0.5176 | 0.02166 |
| w/o KL Penalty | h2l_mean_top5 | 0.0 | True | -0.5064 | -0.004795 |
| w/o Negation Gate | h2l_mean_top5 | 0.0 | True | 0.7005 | 0.367363 |
| Product Feature Mode | h2l_mean_top5 | 0.0 | True | 0.7103 | 1.566416 |

---

## 3. Score-Level Distance (Full V6 vs Ablated)

| variant | mean_score_diff | max_score_diff | n_cases_changed | pct_cases_changed | n_cases |
| --- | --- | --- | --- | --- | --- |
| Product Feature Mode | 1.566416 | 11.54189 | 175 | 88.8 | 197 |
| w/o Adaptive Alpha | 0.775026 | 6.868152 | 163 | 82.7 | 197 |
| w/o IDF Specificity | 0.40177 | 2.837532 | 162 | 82.2 | 197 |
| w/o Negation Gate | 0.367363 | 2.446946 | 160 | 81.2 | 197 |
| w/o Bayesian Prior | 0.12511 | 1.853979 | 168 | 85.3 | 197 |
| w/o Margin Activation | 0.02166 | 0.254623 | 125 | 63.5 | 197 |
| w/o KL Penalty | 0.004795 | 0.072613 | 78 | 39.6 | 197 |

---

## 3. Top-5 Rank Swap Summary

| variant | n_rank_changed | n_total | pct_rank_changed |
| --- | --- | --- | --- |
| w/o Margin Activation | 31 | 197 | 15.7 |
| w/o Bayesian Prior | 25 | 197 | 12.7 |
| w/o IDF Specificity | 25 | 197 | 12.7 |
| w/o KL Penalty | 25 | 197 | 12.7 |
| w/o Negation Gate | 25 | 197 | 12.7 |
| Product Feature Mode | 25 | 197 | 12.7 |
| w/o Adaptive Alpha | 24 | 197 | 12.2 |

---

## 4. Score Perturbation by Variant

| variant | mean_abs_delta | std_delta | max_delta | n_nonzero |
| --- | --- | --- | --- | --- |
| w/o Bayesian Prior | 0.353307 | 0.529619 | 3.535951 | 193 |
| w/o KL Penalty | 0.33057 | 0.476403 | 3.069978 | 193 |
| w/o Margin Activation | 0.324747 | 0.470107 | 3.069978 | 193 |
| w/o Negation Gate | 0.258053 | 0.408908 | 3.069978 | 193 |
| w/o IDF Specificity | 0.251216 | 0.400035 | 3.069978 | 193 |
| w/o Adaptive Alpha | 0.179009 | 0.207352 | 1.328902 | 193 |
| Product Feature Mode | 0.020859 | 0.016615 | 0.086035 | 186 |

---

## 5. Slice Analysis

| slice | variant | metric | Full_V6_mean | ablated_mean | delta | n_cases |
| --- | --- | --- | --- | --- | --- | --- |
| negation | w/o Adaptive Alpha | nDCG@5 | 0.1159 | 0.1159 | 0.0 | 36 |
| negation | w/o Adaptive Alpha | MAP | 0.1291 | 0.1291 | 0.0 | 36 |
| negation | w/o Adaptive Alpha | MRR | 0.172 | 0.172 | 0.0 | 36 |
| negation | w/o Bayesian Prior | nDCG@5 | 0.1159 | 0.1159 | 0.0 | 36 |
| negation | w/o Bayesian Prior | MAP | 0.1291 | 0.1291 | 0.0 | 36 |
| negation | w/o Bayesian Prior | MRR | 0.172 | 0.172 | 0.0 | 36 |
| negation | w/o IDF Specificity | nDCG@5 | 0.1159 | 0.1159 | 0.0 | 36 |
| negation | w/o IDF Specificity | MAP | 0.1291 | 0.1291 | 0.0 | 36 |
| negation | w/o IDF Specificity | MRR | 0.172 | 0.172 | 0.0 | 36 |
| negation | w/o Margin Activation | nDCG@5 | 0.1159 | 0.1201 | -0.0042 | 36 |
| negation | w/o Margin Activation | MAP | 0.1291 | 0.1298 | -0.0007 | 36 |
| negation | w/o Margin Activation | MRR | 0.172 | 0.172 | 0.0 | 36 |
| negation | w/o KL Penalty | nDCG@5 | 0.1159 | 0.1159 | 0.0 | 36 |
| negation | w/o KL Penalty | MAP | 0.1291 | 0.1291 | 0.0 | 36 |
| negation | w/o KL Penalty | MRR | 0.172 | 0.172 | 0.0 | 36 |
| negation | w/o Negation Gate | nDCG@5 | 0.1159 | 0.1159 | 0.0 | 36 |
| negation | w/o Negation Gate | MAP | 0.1291 | 0.1291 | 0.0 | 36 |
| negation | w/o Negation Gate | MRR | 0.172 | 0.172 | 0.0 | 36 |
| negation | Product Feature Mode | nDCG@5 | 0.1159 | 0.1201 | -0.0042 | 36 |
| negation | Product Feature Mode | MAP | 0.1291 | 0.1298 | -0.0007 | 36 |
| negation | Product Feature Mode | MRR | 0.172 | 0.172 | 0.0 | 36 |
| non_negation | w/o Adaptive Alpha | nDCG@5 | 0.3914 | 0.3914 | 0.0 | 161 |
| non_negation | w/o Adaptive Alpha | MAP | 0.3937 | 0.3937 | 0.0 | 161 |
| non_negation | w/o Adaptive Alpha | MRR | 0.4487 | 0.4487 | 0.0 | 161 |
| non_negation | w/o Bayesian Prior | nDCG@5 | 0.3914 | 0.3914 | 0.0 | 161 |
| non_negation | w/o Bayesian Prior | MAP | 0.3937 | 0.3937 | 0.0 | 161 |
| non_negation | w/o Bayesian Prior | MRR | 0.4487 | 0.4487 | 0.0 | 161 |
| non_negation | w/o IDF Specificity | nDCG@5 | 0.3914 | 0.3914 | 0.0 | 161 |
| non_negation | w/o IDF Specificity | MAP | 0.3937 | 0.3937 | 0.0 | 161 |
| non_negation | w/o IDF Specificity | MRR | 0.4487 | 0.4487 | 0.0 | 161 |
| non_negation | w/o Margin Activation | nDCG@5 | 0.3914 | 0.3918 | -0.0004 | 161 |
| non_negation | w/o Margin Activation | MAP | 0.3937 | 0.3943 | -0.0007 | 161 |
| non_negation | w/o Margin Activation | MRR | 0.4487 | 0.4493 | -0.0005 | 161 |
| non_negation | w/o KL Penalty | nDCG@5 | 0.3914 | 0.3914 | 0.0 | 161 |
| non_negation | w/o KL Penalty | MAP | 0.3937 | 0.3937 | 0.0 | 161 |
| non_negation | w/o KL Penalty | MRR | 0.4487 | 0.4487 | 0.0 | 161 |
| non_negation | w/o Negation Gate | nDCG@5 | 0.3914 | 0.3914 | 0.0 | 161 |
| non_negation | w/o Negation Gate | MAP | 0.3937 | 0.3937 | 0.0 | 161 |
| non_negation | w/o Negation Gate | MRR | 0.4487 | 0.4487 | 0.0 | 161 |
| non_negation | Product Feature Mode | nDCG@5 | 0.3914 | 0.3914 | 0.0 | 161 |
| non_negation | Product Feature Mode | MAP | 0.3937 | 0.3937 | 0.0 | 161 |
| non_negation | Product Feature Mode | MRR | 0.4487 | 0.4487 | 0.0 | 161 |
| high_severity | w/o Adaptive Alpha | nDCG@5 | 0.3024 | 0.3024 | 0.0 | 32 |
| high_severity | w/o Adaptive Alpha | MAP | 0.2916 | 0.2916 | 0.0 | 32 |
| high_severity | w/o Adaptive Alpha | MRR | 0.3259 | 0.3259 | 0.0 | 32 |
| high_severity | w/o Bayesian Prior | nDCG@5 | 0.3024 | 0.3024 | 0.0 | 32 |
| high_severity | w/o Bayesian Prior | MAP | 0.2916 | 0.2916 | 0.0 | 32 |
| high_severity | w/o Bayesian Prior | MRR | 0.3259 | 0.3259 | 0.0 | 32 |
| high_severity | w/o IDF Specificity | nDCG@5 | 0.3024 | 0.3024 | 0.0 | 32 |
| high_severity | w/o IDF Specificity | MAP | 0.2916 | 0.2916 | 0.0 | 32 |
| high_severity | w/o IDF Specificity | MRR | 0.3259 | 0.3259 | 0.0 | 32 |
| high_severity | w/o Margin Activation | nDCG@5 | 0.3024 | 0.3046 | -0.0022 | 32 |
| high_severity | w/o Margin Activation | MAP | 0.2916 | 0.2942 | -0.0026 | 32 |
| high_severity | w/o Margin Activation | MRR | 0.3259 | 0.3285 | -0.0026 | 32 |
| high_severity | w/o KL Penalty | nDCG@5 | 0.3024 | 0.3024 | 0.0 | 32 |
| high_severity | w/o KL Penalty | MAP | 0.2916 | 0.2916 | 0.0 | 32 |
| high_severity | w/o KL Penalty | MRR | 0.3259 | 0.3259 | 0.0 | 32 |
| high_severity | w/o Negation Gate | nDCG@5 | 0.3024 | 0.3024 | 0.0 | 32 |
| high_severity | w/o Negation Gate | MAP | 0.2916 | 0.2916 | 0.0 | 32 |
| high_severity | w/o Negation Gate | MRR | 0.3259 | 0.3259 | 0.0 | 32 |
| high_severity | Product Feature Mode | nDCG@5 | 0.3024 | 0.3024 | 0.0 | 32 |
| high_severity | Product Feature Mode | MAP | 0.2916 | 0.2916 | 0.0 | 32 |
| high_severity | Product Feature Mode | MRR | 0.3259 | 0.3259 | 0.0 | 32 |
| complex_cases | w/o Adaptive Alpha | nDCG@5 | 0.4055 | 0.4055 | 0.0 | 58 |
| complex_cases | w/o Adaptive Alpha | MAP | 0.4197 | 0.4197 | 0.0 | 58 |
| complex_cases | w/o Adaptive Alpha | MRR | 0.4808 | 0.4808 | 0.0 | 58 |
| complex_cases | w/o Bayesian Prior | nDCG@5 | 0.4055 | 0.4055 | 0.0 | 58 |
| complex_cases | w/o Bayesian Prior | MAP | 0.4197 | 0.4197 | 0.0 | 58 |
| complex_cases | w/o Bayesian Prior | MRR | 0.4808 | 0.4808 | 0.0 | 58 |
| complex_cases | w/o IDF Specificity | nDCG@5 | 0.4055 | 0.4055 | 0.0 | 58 |
| complex_cases | w/o IDF Specificity | MAP | 0.4197 | 0.4197 | 0.0 | 58 |
| complex_cases | w/o IDF Specificity | MRR | 0.4808 | 0.4808 | 0.0 | 58 |
| complex_cases | w/o Margin Activation | nDCG@5 | 0.4055 | 0.4067 | -0.0012 | 58 |
| complex_cases | w/o Margin Activation | MAP | 0.4197 | 0.4212 | -0.0014 | 58 |
| complex_cases | w/o Margin Activation | MRR | 0.4808 | 0.4822 | -0.0014 | 58 |
| complex_cases | w/o KL Penalty | nDCG@5 | 0.4055 | 0.4055 | 0.0 | 58 |
| complex_cases | w/o KL Penalty | MAP | 0.4197 | 0.4197 | 0.0 | 58 |
| complex_cases | w/o KL Penalty | MRR | 0.4808 | 0.4808 | 0.0 | 58 |
| complex_cases | w/o Negation Gate | nDCG@5 | 0.4055 | 0.4055 | 0.0 | 58 |
| complex_cases | w/o Negation Gate | MAP | 0.4197 | 0.4197 | 0.0 | 58 |
| complex_cases | w/o Negation Gate | MRR | 0.4808 | 0.4808 | 0.0 | 58 |
| complex_cases | Product Feature Mode | nDCG@5 | 0.4055 | 0.4055 | 0.0 | 58 |
| complex_cases | Product Feature Mode | MAP | 0.4197 | 0.4197 | 0.0 | 58 |
| complex_cases | Product Feature Mode | MRR | 0.4808 | 0.4808 | 0.0 | 58 |
| simple_cases | w/o Adaptive Alpha | nDCG@5 | 0.1476 | 0.1476 | 0.0 | 64 |
| simple_cases | w/o Adaptive Alpha | MAP | 0.1345 | 0.1345 | 0.0 | 64 |
| simple_cases | w/o Adaptive Alpha | MRR | 0.1611 | 0.1611 | 0.0 | 64 |
| simple_cases | w/o Bayesian Prior | nDCG@5 | 0.1476 | 0.1476 | 0.0 | 64 |
| simple_cases | w/o Bayesian Prior | MAP | 0.1345 | 0.1345 | 0.0 | 64 |
| simple_cases | w/o Bayesian Prior | MRR | 0.1611 | 0.1611 | 0.0 | 64 |
| simple_cases | w/o IDF Specificity | nDCG@5 | 0.1476 | 0.1476 | 0.0 | 64 |
| simple_cases | w/o IDF Specificity | MAP | 0.1345 | 0.1345 | 0.0 | 64 |
| simple_cases | w/o IDF Specificity | MRR | 0.1611 | 0.1611 | 0.0 | 64 |
| simple_cases | w/o Margin Activation | nDCG@5 | 0.1476 | 0.1476 | 0.0 | 64 |
| simple_cases | w/o Margin Activation | MAP | 0.1345 | 0.1345 | 0.0 | 64 |
| simple_cases | w/o Margin Activation | MRR | 0.1611 | 0.1611 | 0.0 | 64 |
| simple_cases | w/o KL Penalty | nDCG@5 | 0.1476 | 0.1476 | 0.0 | 64 |
| simple_cases | w/o KL Penalty | MAP | 0.1345 | 0.1345 | 0.0 | 64 |
| simple_cases | w/o KL Penalty | MRR | 0.1611 | 0.1611 | 0.0 | 64 |
| simple_cases | w/o Negation Gate | nDCG@5 | 0.1476 | 0.1476 | 0.0 | 64 |
| simple_cases | w/o Negation Gate | MAP | 0.1345 | 0.1345 | 0.0 | 64 |
| simple_cases | w/o Negation Gate | MRR | 0.1611 | 0.1611 | 0.0 | 64 |
| simple_cases | Product Feature Mode | nDCG@5 | 0.1476 | 0.1476 | 0.0 | 64 |
| simple_cases | Product Feature Mode | MAP | 0.1345 | 0.1345 | 0.0 | 64 |
| simple_cases | Product Feature Mode | MRR | 0.1611 | 0.1611 | 0.0 | 64 |

---

## Interpretation Notes

- Binary relevance metrics (P@5, nDCG@5) may show **zero difference** when top-5 documents remain identical
- Score-level delta and rank swap count capture **finer-grained** component effects
- Components with Δ ≈ 0 may have synergistic effects — removing them alone doesn't capture interaction
- Slice analysis is exploratory for n_cases < 10
- Protocol: L1 detection is held constant; only scoring-layer V6 components are toggled