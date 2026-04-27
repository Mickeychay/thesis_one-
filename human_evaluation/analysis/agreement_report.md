# Expert Evaluation — Agreement Analysis Report

**Generated:** 2026-04-25 18:17  
**Evaluators:** 3 (E01, E02, E03)  
**Unique cases:** 8  

---

## 1. Cohen's κ (Pairwise, Linear-Weighted)

| evaluator_1 | evaluator_2 | metric | n_cases | cohen_kappa_linear | interpretation |
| --- | --- | --- | --- | --- | --- |
| E01 | E02 | relevance_score | 16 | 0.2993 | fair |
| E01 | E03 | relevance_score | 16 | 0.2571 | fair |
| E02 | E03 | relevance_score | 16 | 0.0256 | slight |

**Average κ across pairs:** 0.1940 (slight)

---

## 2. Fleiss' κ (Multi-Rater Overall)

| metric | n_subjects | n_raters | fleiss_kappa | interpretation |
| --- | --- | --- | --- | --- |
| relevance_score | 16 | 3 | 0.0577 | slight |

---

## 3. ICC(2,1) — Two-Way Mixed, Single Measures

_Not computed (need pingouin)_

---

## 4. System A vs System B

| metric | System_A_mean | System_B_mean | delta_A_minus_B | wilcoxon_stat | p_value | effect_r | n_cases | significant_p05 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| relevance_score | 2.875 | 3.4167 | -0.5417 | 6.5 | 0.2344 | 1.0833 | 8 | False |
| completeness_score | 3.5704 | 3.8471 | -0.2767 | 14.0 | 0.6406 | 2.3333 | 8 | False |
| clinical_usefulness_score | 3.862 | 3.4985 | 0.3634 | 12.0 | 0.4609 | 2.0 | 8 | False |

**No significant differences at p<.05**

---

## 5. Slice Analysis — Delta (System A − System B)

| slice | metric | n_cases | delta_A_minus_B_mean |
| --- | --- | --- | --- |
| non_negation_cases | relevance_score | 6 | -1.0 |
| non_negation_cases | completeness_score | 6 | -1.0227 |
| non_negation_cases | clinical_usefulness_score | 6 | 0.5312 |
| high_severity_cases | relevance_score | 3 | -1.0 |
| high_severity_cases | completeness_score | 3 | -0.7018 |
| high_severity_cases | clinical_usefulness_score | 3 | 0.6257 |
| other_cases | relevance_score | 5 | -0.2667 |
| other_cases | completeness_score | 5 | -0.0216 |
| other_cases | clinical_usefulness_score | 5 | 0.2061 |

---

## Interpretation Notes

- **κ ≥ 0.61** (substantial) is the minimum acceptable threshold for clinical annotation tasks (Landis & Koch, 1977)
- **ICC ≥ 0.75** (good) is recommended for clinical measurement tools
- Wilcoxon signed-rank (two-sided, α=0.05) used for System A vs B comparison
- Slice analysis is exploratory; interpret with caution for n_cases < 10