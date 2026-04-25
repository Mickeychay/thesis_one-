#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate a conservative Q1-readiness report from real artifacts."""

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, List


PRIMARY_PAIRS = [
    ("bm25_only", "h2l-bm25"),
    ("naive_rag", "h2l-naive_rag"),
    ("hyde", "h2l-hyde"),
    ("basic", "h2l-hybrid"),
]
PRIMARY_METRICS = ["MAP", "MRR", "nDCG@5"]


def load_json(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_rq6_ablation(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}

    metric_sums: Dict[str, Dict[str, float]] = {}
    metric_counts: Dict[str, int] = {}
    with p.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            variant = row.get("variant", "unknown")
            metric_sums.setdefault(variant, {"MAP": 0.0, "MRR": 0.0, "nDCG@5": 0.0})
            metric_counts[variant] = metric_counts.get(variant, 0) + 1
            for metric in metric_sums[variant]:
                metric_sums[variant][metric] += float(row.get(metric) or 0.0)

    variants: Dict[str, Dict[str, float]] = {}
    for variant, sums in metric_sums.items():
        n = metric_counts[variant]
        variants[variant] = {metric: value / n for metric, value in sums.items()}

    full = variants.get("Full V6", {})
    deltas = []
    for variant, metrics in variants.items():
        if variant == "Full V6" or not full:
            continue
        deltas.append(abs(full.get("nDCG@5", 0.0) - metrics.get("nDCG@5", 0.0)))

    return {
        "path": str(p),
        "variants": variants,
        "n_rows": sum(metric_counts.values()),
        "n_variants": len(variants),
        "max_abs_ndcg_delta_vs_full": max(deltas) if deltas else 0.0,
    }


def pair_key(a: str, b: str) -> str:
    return f"{a}_vs_{b}"


def get_metric_mean(summary: Dict[str, Any], strategy: str, metric: str) -> float:
    return float(summary.get("aggregates", {}).get(strategy, {}).get(metric, {}).get("mean", 0.0))


def get_pair_test(summary: Dict[str, Any], baseline: str, h2l: str, metric: str) -> Dict[str, Any]:
    tests = summary.get("statistical_tests", {}).get(metric, {}).get("pairwise", {})
    direct = tests.get(pair_key(baseline, h2l))
    if direct:
        return direct
    reverse = tests.get(pair_key(h2l, baseline))
    if reverse:
        copied = dict(reverse)
        copied["mean_diff"] = -float(copied.get("mean_diff", 0.0))
        return copied
    return {}


def verdict_for_delta(delta: float, p_value: float | None) -> str:
    if p_value is not None and p_value < 0.05 and delta > 0:
        return "supported"
    if p_value is not None and p_value < 0.05 and delta < 0:
        return "baseline_supported"
    if abs(delta) < 0.01:
        return "practically_tied"
    return "trend_only"


def build_report(
    summary: Dict[str, Any],
    polarity: Dict[str, Any],
    audit: Dict[str, Any],
    rq6_ablation: Dict[str, Any],
) -> str:
    metadata = summary.get("metadata", {})
    lines: List[str] = [
        "# Q1 Readiness Report",
        "",
        "This report is generated from repository artifacts and uses conservative language by default.",
        "",
        "## Artifact Provenance",
        "",
        f"- Proper evaluation timestamp: `{metadata.get('timestamp', 'missing')}`",
        f"- Test cases: `{metadata.get('num_cases', 'missing')}`",
        f"- Strategies: `{', '.join(metadata.get('strategies', []))}`",
        f"- Problem source: `{metadata.get('problem_source', 'missing')}`",
        "",
        "## Main Pairwise Evidence",
        "",
        "| Pair | Metric | Baseline | H2L | Delta | p-value | Verdict |",
        "|---|---|---:|---:|---:|---:|---|",
    ]

    supported = 0
    trend = 0
    tied = 0
    baseline_supported = 0

    for baseline, h2l in PRIMARY_PAIRS:
        for metric in PRIMARY_METRICS:
            b_mean = get_metric_mean(summary, baseline, metric)
            h_mean = get_metric_mean(summary, h2l, metric)
            delta = h_mean - b_mean
            test = get_pair_test(summary, baseline, h2l, metric)
            p_value = test.get("p_value")
            p_float = float(p_value) if p_value is not None else None
            verdict = verdict_for_delta(delta, p_float)
            supported += verdict == "supported"
            trend += verdict == "trend_only"
            tied += verdict == "practically_tied"
            baseline_supported += verdict == "baseline_supported"
            p_display = f"{p_float:.4f}" if p_float is not None else "--"
            lines.append(
                f"| {baseline} vs {h2l} | {metric} | {b_mean:.4f} | {h_mean:.4f} | "
                f"{delta:+.4f} | {p_display} | {verdict} |"
            )

    lines.extend(
        [
            "",
            "## Safety And Validity Checks",
            "",
        ]
    )

    polarity_overall = polarity.get("overall", {})
    if polarity_overall:
        lines.extend(
            [
                f"- Polarity accuracy: `{polarity_overall.get('accuracy', 0):.4f}`",
                f"- Polarity F1: `{polarity_overall.get('f1_score', 0):.4f}`",
                f"- Negation detection rate: `{polarity_overall.get('negation_detection_rate', 0):.4f}`",
                f"- Negated cases: `{polarity_overall.get('n_negated', 'missing')}`",
            ]
        )
    else:
        lines.append("- Polarity artifact missing.")

    if audit:
        lines.extend(
            [
                f"- Ground-truth audit risk flags: `{audit.get('risk_flags', [])}`",
                f"- Cross-split families: `{len(audit.get('cross_split_families', []))}`",
                f"- Near-duplicate train/test pairs: `{len(audit.get('near_duplicates', []))}`",
            ]
        )
    else:
        lines.append("- Ground-truth audit missing; run `python scripts/ground_truth_audit.py`.")

    lines.extend(["", "## V6 Ablation Evidence", ""])
    variants = rq6_ablation.get("variants", {})
    if variants:
        lines.extend(
            [
                f"- RQ6 ablation rows: `{rq6_ablation.get('n_rows')}`",
                f"- RQ6 variants: `{rq6_ablation.get('n_variants')}`",
                f"- Max |Δ nDCG@5| vs Full V6: `{rq6_ablation.get('max_abs_ndcg_delta_vs_full', 0.0):.4f}`",
                "",
                "| Variant | MAP | MRR | nDCG@5 |",
                "|---|---:|---:|---:|",
            ]
        )
        for variant, metrics in sorted(variants.items()):
            lines.append(
                f"| {variant} | {metrics.get('MAP', 0.0):.4f} | "
                f"{metrics.get('MRR', 0.0):.4f} | {metrics.get('nDCG@5', 0.0):.4f} |"
            )
        if rq6_ablation.get("n_rows", 0) < 100:
            lines.extend(
                [
                    "",
                    "Interpretation: this is a smoke/sanity ablation, not a final Q1 ablation. "
                    "Identical variant means indicate the current bounded case set is too small "
                    "or the toggled controls are not changing the live scoring path enough to "
                    "support component-level causal claims.",
                ]
            )
    else:
        lines.append("- RQ6 ablation artifact missing; run `python ablation_study.py --rq 6`.")

    lines.extend(
        [
            "",
            "## Conservative Claim Guidance",
            "",
        ]
    )

    if supported >= 3 and not audit.get("cross_split_families"):
        lines.append(
            "Current artifacts support a cautious claim that H2L improves selected retrieval metrics, "
            "but external blind expert evaluation should still be reported before Q1 submission."
        )
    else:
        lines.append(
            "Do not claim broad superiority yet. Current evidence is best framed as trend-level or "
            "slice-specific, with explicit limitations around significance, generated cases, and "
            "keyword-derived relevance judgments."
        )

    lines.extend(
        [
            "",
            "Recommended next empirical steps:",
            "",
            "1. Complete blinded expert relevance scoring with at least 3 domain experts.",
            "2. Rerun family-level split audit and keep augmented/paraphrase cases as stress-test slices.",
            "3. Rerun V6 component ablation on a larger fixed sample and verify each toggle changes live scoring.",
            "4. Add an external holdout set before making generalization claims.",
            "",
            "## Summary Counts",
            "",
            f"- Supported H2L metric comparisons: `{supported}`",
            f"- Trend-only comparisons: `{trend}`",
            f"- Practical ties: `{tied}`",
            f"- Baseline-supported comparisons: `{baseline_supported}`",
            "",
        ]
    )

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Q1-readiness report")
    parser.add_argument("--summary", default="evaluation_results/proper_eval_latest_summary.json")
    parser.add_argument("--polarity", default="evaluation_results/sentence_polarity_latest.json")
    parser.add_argument("--audit", default="evaluation_results/ground_truth_audit.json")
    parser.add_argument("--rq6-ablation", default="ablation_results/v6_component_latest/rq6_results.csv")
    parser.add_argument("--output", default="evaluation_results/q1_readiness_report.md")
    args = parser.parse_args()

    summary = load_json(args.summary)
    polarity = load_json(args.polarity)
    audit = load_json(args.audit)
    rq6_ablation = load_rq6_ablation(args.rq6_ablation)
    report = build_report(summary, polarity, audit, rq6_ablation)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(report, encoding="utf-8")
    print(f"Q1 readiness report: {args.output}")


if __name__ == "__main__":
    main()
