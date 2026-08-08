# Adversarial Stress-Test Slice

Generated: 2026-08-08T16:27:15+07:00
Matrix: `evaluation_results/model_comparison/l2_full_matrix_95cases_3models_3repeats_8strategies.json` (`2d116b0fe998d6588d48f466076755751d0c72322ef60b0a4525f6dbc737da73`)
Ground truth: `expanded_ground_truth.json` (`158891430e1b2353e4ab11f5077ae79c23dbbae3302dae7610d2e5bbd5c53832`)

Pass criteria: preserve every expected target code, suppress the annotated false-trigger code, and satisfy both for joint pass.
Other unexpected predictions do not alter joint pass. Degraded rows remain in every denominator.

## Detector

| Model | Rows | Target hits/opportunities | Target recall | Complete targets | False trigger suppressed | Joint pass | Degraded |
|---|---:|---:|---:|---:|---:|---:|---:|
| Overall (descriptive) | 180 | 162/189 | 0.8571 | 153/180 (0.8500) | 27/180 (0.1500) | 18/180 (0.1000) | 0/180 |
| qwen2.5:7b | 60 | 54/63 | 0.8571 | 51/60 (0.8500) | 9/60 (0.1500) | 6/60 (0.1000) | 0/60 |
| scb10x/llama3.1-typhoon2-8b-instruct:latest | 60 | 54/63 | 0.8571 | 51/60 (0.8500) | 9/60 (0.1500) | 6/60 (0.1000) | 0/60 |
| h2l/typhoon-gemma3-4b-templatefix-v2:latest | 60 | 54/63 | 0.8571 | 51/60 (0.8500) | 9/60 (0.1500) | 6/60 (0.1000) | 0/60 |

## Retrieval

Retrieval values first average repeats within each case, then average the case means across the adversarial slice.

| Model | Strategy | Cases | nDCG@5 | nDCG@10 | MAP | MRR |
|---|---|---:|---:|---:|---:|---:|
| qwen2.5:7b | bm25_only | 20 | 0.0631 | 0.0631 | 0.0500 | 0.0500 |
| qwen2.5:7b | naive_rag | 20 | 0.0500 | 0.0651 | 0.0556 | 0.0556 |
| qwen2.5:7b | hyde | 20 | 0.0000 | 0.0158 | 0.0096 | 0.0096 |
| qwen2.5:7b | basic | 20 | 0.0500 | 0.0667 | 0.0571 | 0.0571 |
| qwen2.5:7b | h2l-bm25 | 20 | 0.0565 | 0.0710 | 0.0467 | 0.0467 |
| qwen2.5:7b | h2l-naive_rag | 20 | 0.0500 | 0.0678 | 0.0583 | 0.0583 |
| qwen2.5:7b | h2l-hyde | 20 | 0.0500 | 0.0500 | 0.0500 | 0.0500 |
| qwen2.5:7b | h2l-hybrid | 20 | 0.0500 | 0.0500 | 0.0574 | 0.0574 |
| scb10x/llama3.1-typhoon2-8b-instruct:latest | bm25_only | 20 | 0.0631 | 0.0631 | 0.0500 | 0.0500 |
| scb10x/llama3.1-typhoon2-8b-instruct:latest | naive_rag | 20 | 0.0500 | 0.0651 | 0.0556 | 0.0556 |
| scb10x/llama3.1-typhoon2-8b-instruct:latest | hyde | 20 | 0.0000 | 0.0158 | 0.0096 | 0.0096 |
| scb10x/llama3.1-typhoon2-8b-instruct:latest | basic | 20 | 0.0500 | 0.0667 | 0.0571 | 0.0571 |
| scb10x/llama3.1-typhoon2-8b-instruct:latest | h2l-bm25 | 20 | 0.0565 | 0.0710 | 0.0467 | 0.0467 |
| scb10x/llama3.1-typhoon2-8b-instruct:latest | h2l-naive_rag | 20 | 0.0500 | 0.0678 | 0.0583 | 0.0583 |
| scb10x/llama3.1-typhoon2-8b-instruct:latest | h2l-hyde | 20 | 0.0500 | 0.0500 | 0.0500 | 0.0500 |
| scb10x/llama3.1-typhoon2-8b-instruct:latest | h2l-hybrid | 20 | 0.0500 | 0.0500 | 0.0574 | 0.0574 |
| h2l/typhoon-gemma3-4b-templatefix-v2:latest | bm25_only | 20 | 0.0631 | 0.0631 | 0.0500 | 0.0500 |
| h2l/typhoon-gemma3-4b-templatefix-v2:latest | naive_rag | 20 | 0.0500 | 0.0651 | 0.0556 | 0.0556 |
| h2l/typhoon-gemma3-4b-templatefix-v2:latest | hyde | 20 | 0.0000 | 0.0158 | 0.0096 | 0.0096 |
| h2l/typhoon-gemma3-4b-templatefix-v2:latest | basic | 20 | 0.0500 | 0.0667 | 0.0571 | 0.0571 |
| h2l/typhoon-gemma3-4b-templatefix-v2:latest | h2l-bm25 | 20 | 0.0565 | 0.0710 | 0.0467 | 0.0467 |
| h2l/typhoon-gemma3-4b-templatefix-v2:latest | h2l-naive_rag | 20 | 0.0500 | 0.0678 | 0.0583 | 0.0583 |
| h2l/typhoon-gemma3-4b-templatefix-v2:latest | h2l-hyde | 20 | 0.0500 | 0.0500 | 0.0500 | 0.0500 |
| h2l/typhoon-gemma3-4b-templatefix-v2:latest | h2l-hybrid | 20 | 0.0500 | 0.0500 | 0.0574 | 0.0574 |

## Per Case

| Case | Target | False trigger | Target hits/opportunities | Target recall | False-trigger suppression | Joint pass |
|---|---|---|---:|---:|---:|---:|
| ADV_001 | 1003 | X60-X84 | 9/9 | 1.0000 | 0.0000 | 0.0000 |
| ADV_002 | 1104 | 1602 | 0/9 | 0.0000 | 0.0000 | 0.0000 |
| ADV_003 | 1201 | F20-F29 | 0/9 | 0.0000 | 0.0000 | 0.0000 |
| ADV_004 | 1101 | T74 | 9/9 | 1.0000 | 1.0000 | 1.0000 |
| ADV_005 | 1001, 1104 | T74 | 9/18 | 0.5000 | 1.0000 | 0.0000 |
| ADV_006 | 1201 | X60-X84 | 9/9 | 1.0000 | 0.0000 | 0.0000 |
| ADV_007 | 0804 | 1602 | 9/9 | 1.0000 | 0.0000 | 0.0000 |
| ADV_008 | 1201 | F20-F29 | 9/9 | 1.0000 | 0.0000 | 0.0000 |
| ADV_009 | 1002 | T74 | 9/9 | 1.0000 | 0.0000 | 0.0000 |
| ADV_010 | 1401 | T74 | 9/9 | 1.0000 | 1.0000 | 1.0000 |
| ADV_011 | 0701 | 1601 | 9/9 | 1.0000 | 0.0000 | 0.0000 |
| ADV_012 | 0702 | 1602 | 9/9 | 1.0000 | 0.0000 | 0.0000 |
| ADV_013 | 1401 | F20-F29 | 9/9 | 1.0000 | 0.0000 | 0.0000 |
| ADV_014 | 1301 | 0601 | 9/9 | 1.0000 | 0.0000 | 0.0000 |
| ADV_015 | 1003 | T74.1 | 9/9 | 1.0000 | 0.0000 | 0.0000 |
| ADV_016 | 0801 | Z65.1 | 9/9 | 1.0000 | 0.0000 | 0.0000 |
| ADV_017 | 1003 | 1701 | 9/9 | 1.0000 | 0.0000 | 0.0000 |
| ADV_018 | 0702 | C34 | 9/9 | 1.0000 | 0.0000 | 0.0000 |
| ADV_019 | 1002 | E11 | 9/9 | 1.0000 | 0.0000 | 0.0000 |
| ADV_020 | 1201 | A15 | 9/9 | 1.0000 | 0.0000 | 0.0000 |
