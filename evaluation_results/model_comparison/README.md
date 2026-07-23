# Local L2 model comparison

## Decision

Keep `qwen2.5:7b` as the default L2 model and expose `scb10x/llama3.1-typhoon2-8b-instruct:latest` as an optional Thai-focused comparator. The full 76-case paired run does not show a material quality winner: only 4 cases produced different final code sets, Qwen was better on case-level F1 in 1 case, Typhoon in 2 cases, and 73 cases had equal F1.

This experiment changed only the request-scoped L2 model. The prompt, taxonomy, L1 rules, `intfloat/multilingual-e5-base`, `BAAI/bge-reranker-v2-m3`, temperature `0.2`, seed `42`, and H2L Bayesian V6 source hash were fixed.

## Full detector result (76 cases)

| Metric | Qwen 2.5 7B | Typhoon 2 8B |
|---|---:|---:|
| Parameters / quantization | 7.6B / Q4_K_M | 8.0B / Q4_K_M |
| Local model size | 4.36 GiB | 4.58 GiB |
| L2-triggered cases | 55/76 (72.37%) | 55/76 (72.37%) |
| Micro precision | 0.3255 | 0.3286 |
| Micro recall | 0.4286 | 0.4286 |
| Micro F1 | 0.3700 | 0.3720 |
| Macro F1 | 0.3401 | 0.3392 |
| Exact match | 0.1711 | 0.1711 |
| L2-subset macro F1 | 0.2858 | 0.2846 |
| Median L2 latency | 13.17 s | 13.85 s |
| P95 L2 latency | 23.56 s | 25.07 s |
| Degraded L2 calls | 0% | 0% |

The tiny metric deltas point in different directions: Typhoon is +0.0020 on micro F1, while Qwen is +0.0009 on macro F1 and is about 0.67 seconds faster at median L2 latency. These differences are too small for a superiority claim from one run.

## Where the models differed

Final predicted code sets differed in 4/76 cases:

- `MENTAL_008_PAR_01`: Qwen retained an extra `X60-X84`; both had F1 0.
- `NEG_SH_POS`: Typhoon retained an extra `0102`; Qwen had higher F1 (0.667 vs 0.500).
- `NEG_LH_POS_V2`: Qwen retained an extra `0201`; Typhoon had higher F1 (0.250 vs 0.222).
- `NEG_LM_POS_V2`: Qwen retained an extra `0102`; Typhoon had higher F1 (0.571 vs 0.500).

This shows that model choice mostly affects borderline validation/filtering. Taxonomy and evidence-anchor guards reject many model-proposed codes before they reach the final problem set, so the guarded system is substantially less variable than raw LLM output.

## Gemma pilot exclusion

`scb10x/typhoon2.1-gemma3-4b:latest` was tested first because it is smaller, but every L2 call degraded in the local Ollama OpenAI-compatible path with the template error `selectattr: unknown test 'tool_calls'`. Native generation failed as well. It was excluded for runtime incompatibility, not because this pilot established inferior semantic quality. The failed pilot remains in `smoke_detector_3cases.json` for auditability.

## Retrieval smoke result

The 3-case end-to-end smoke run loaded the fixed E5 embedder and BGE reranker and exercised semantic H2L scoring. Both L2 models produced identical retrieval metrics: MAP `0.3840`, MRR `0.5000`, nDCG@5 `0.3295`, nDCG@10 `0.3929`, and P@5 `0.2000`. This is a pipeline/provenance check, not enough cases for a retrieval-quality superiority claim.

## Artifacts

- `l2_model_comparison_full_76cases.json`: full paired detector run
- `smoke_detector_3cases_typhoon2.json`: successful preflight
- `smoke_detector_3cases.json`: failed Gemma adapter preflight
- `smoke_retrieval_3cases.json`: small end-to-end retrieval smoke test (when present)

## Interpretation limit

The reported detector metrics are end-to-end results after L1 rules, L2 validation, crisis safety net, taxonomy validation, and evidence anchoring. They do not measure isolated raw language-model understanding. In particular, a crisis safety rule may temporarily retain a negated high-severity code; the API polarity layer and human review still apply afterward.
