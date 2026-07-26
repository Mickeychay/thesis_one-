# Local L2 model comparison

## Decision

For the guarded detector and retrieval pipeline, use
`scb10x/typhoon2.1-gemma3-4b:latest` as the leading efficiency candidate. Its
detector quality was practically tied with the 7B-8B models, while its median
L2 latency was 32.5% lower than Qwen and 36.6% lower than Typhoon 8B. Its local
model file was also 44.1% smaller than Qwen and 46.8% smaller than Typhoon 8B.

Use `scb10x/llama3.1-typhoon2-8b-instruct:latest` as the strict-schema fallback:
it was the only model with no degraded L2 calls. Qwen had the highest nominal
H2L-hybrid nDCG@5, but the difference from Gemma occurred in one of 76 cases
and was not statistically significant. The experiment does not justify a
quality-superiority claim for any model.

This recommendation applies to structured problem detection and downstream
retrieval. It does not directly measure the quality of generated narrative
summaries. A prose-summary benchmark must separately score factual consistency,
key-issue coverage, hallucination, Thai fluency, actionability, and format/length
compliance.

## Full matrix

The completed experiment contains 6,156 logical evaluations:

- 76 unseen test cases
- 3 local models
- 3 repeats
- 684 detector evaluations
- 8 retrieval strategies and 5,472 retrieval evaluations

The prompt, taxonomy, L1 rules, `intfloat/multilingual-e5-base`,
`BAAI/bge-reranker-v2-m3`, detector temperature `0.2`, detector seed `42`, and
H2L Bayesian V6 source hash were fixed. Standalone retrieval baselines were
cached once per strategy/case because they do not consume model-specific
detected problems. HyDE generation used fixed `qwen2.5:7b`, temperature `0.3`,
and seed `42` for all models.

## Detector result

| Metric | Qwen 2.5 7B | Typhoon 2 8B | Typhoon 2.1 Gemma 3 4B |
|---|---:|---:|---:|
| Parameters / quantization | 7.6B / Q4_K_M | 8.0B / Q4_K_M | 3.9B / Q4_K_M |
| Local model size | 4.36 GiB | 4.58 GiB | 2.44 GiB |
| Micro F1 | 0.3700 | 0.3720 | **0.3740** |
| Macro F1 | 0.3401 | 0.3392 | **0.3414** |
| Micro recall | 0.4286 | 0.4286 | 0.4286 |
| Exact match | 0.1711 | 0.1711 | 0.1711 |
| L2-subset macro F1 | 0.2858 | 0.2846 | **0.2876** |
| High-severity false negatives | 15/run | 15/run | 15/run |
| Stable final-code cases | 76/76 | 76/76 | 76/76 |
| Degraded L2 calls | 3/165 | **0/165** | 3/165 |
| Median L2 latency | 12.34 s | 13.14 s | **8.33 s** |
| P95 L2 latency | 22.01 s | 25.09 s | **15.19 s** |

All detector metrics and final code sets were identical across the three
repeats for each model. Qwen degraded on `REHAB_002` in all repeats, and Gemma
degraded on `BEDRIDDEN_004` in all repeats, because their responses did not
satisfy the nested JSON schema. Guarded fallback processing still produced
stable final code sets.

Paired case-level F1 differences were sparse and not significant by two-sided
Wilcoxon signed-rank tests on 76 independent cases:

- Gemma versus Qwen: Gemma higher in 2 cases, Qwen higher in 0, 74 equal;
  mean delta `+0.0013`, `p=0.180`.
- Gemma versus Typhoon 8B: Gemma higher in 1 case, Typhoon higher in 0, 75
  equal; mean delta `+0.0022`, `p=0.317`.
- Typhoon 8B versus Qwen: Typhoon higher in 2 cases, Qwen higher in 1, 73
  equal; mean delta `-0.0009` in macro case F1, `p=1.000`.

## Retrieval result

The table reports mean nDCG@5 over 228 rows per model/strategy. Standalone
baselines are identical across model columns by design; H2L rows use each
model's detected problem list.

| Baseline -> H2L strategy | Qwen 7B baseline -> H2L | Typhoon 8B baseline -> H2L | Gemma 4B baseline -> H2L |
|---|---:|---:|---:|
| BM25 -> H2L-BM25 | 0.2611 -> **0.2813** | 0.2611 -> **0.2738** | 0.2611 -> **0.2738** |
| Naive RAG -> H2L-Naive | 0.2392 -> 0.2390 | 0.2392 -> 0.2400 | 0.2392 -> 0.2396 |
| HyDE -> H2L-HyDE | **0.0915** -> 0.0771 | **0.0915** -> 0.0875 | **0.0915** -> 0.0794 |
| Hybrid -> H2L-Hybrid | 0.2807 -> **0.2975** | 0.2807 -> **0.2915** | 0.2807 -> **0.2909** |

H2L-Hybrid was the best strategy for every model. Relative to the fixed Hybrid
baseline, nDCG@5 increased by 6.0% for Qwen, 3.8% for Typhoon 8B, and 3.6% for
Gemma. H2L also improved BM25, had little effect on Naive RAG, and reduced
nDCG@5 for HyDE. None of the baseline-to-H2L nDCG@5 changes reached `p<0.05`
after collapsing repeats to 76 case means; Qwen H2L-Hybrid was the closest at
`p=0.064`.

Retrieval ranking was stable in all 76 cases for every strategy except
H2L-HyDE. H2L-HyDE stability was 65/76 for Qwen, 75/76 for Typhoon 8B, and
76/76 for Gemma. HyDE therefore should not be selected for this dataset based
on either quality or repeat stability.

## Summary-writing implication

Adding the models has little effect on the guarded structured content that
feeds a summary: Gemma and Qwen differed in final code sets for 4/76 cases,
while Gemma and Typhoon 8B differed for 2/76. Retrieval differences between
models were similarly concentrated in very few cases. The main demonstrated
effect is operational: Gemma provides comparable structured quality with lower
latency and memory/storage cost.

Do not interpret these results as proof that the models write equally good Thai
prose. The current ground truth contains problem codes and relevant-document
signals, not reference summaries or human ratings of generated text.

## Runtime compatibility

Gemma's embedded template uses Jinja filters that Ollama's automatic
llama-server parser cannot compile (`selectattr: unknown test 'tool_calls'`).
The successful comparison ran all models through the same isolated Ollama
server with `OLLAMA_GO_TEMPLATE=1`. This bypasses the incompatible parser
without changing model weights.

## Artifacts

- `l2_full_matrix_76cases_3models_3repeats_8strategies.json`: completed full
  detector, retrieval, repeat-stability, and paired-comparison artifact
- `l2_model_comparison_full_76cases_3models.json`: earlier one-repeat detector
  comparison
- `l2_model_stability_5cases_3repeats.json`: earlier five-case stability subset
- `smoke_detector_3models_compatible.json`: successful three-model preflight
- `smoke_retrieval_3cases.json`: earlier three-case retrieval smoke test, when
  present

## Interpretation limit

Detector metrics are end-to-end results after L1 rules, L2 validation, crisis
safety net, taxonomy validation, and evidence anchoring. They do not measure
isolated raw language-model understanding. A crisis safety rule may temporarily
retain a negated high-severity code; the API polarity layer and human review
still apply afterward.
