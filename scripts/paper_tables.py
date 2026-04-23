#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Paper Tables Generator — LaTeX tables from H2L evaluation results
==================================================================
Generates publication-ready LaTeX tables from evaluation results JSON.

Usage:
    python paper_tables.py evaluation_results/proper_eval_summary_*.json
    python paper_tables.py --combined proper_eval.json external_baselines.json
"""

import json
import argparse
from pathlib import Path
from typing import Dict, List


def latex_bold(text: str) -> str:
    return f"\\textbf{{{text}}}"


def format_mean_std(mean: float, std: float, is_best: bool = False) -> str:
    """Format as mean ± std, bold if best"""
    val = f"{mean:.4f} ± {std:.4f}"
    return latex_bold(val) if is_best else val


def generate_main_comparison_table(aggregates: Dict) -> str:
    """
    Table 1: Main strategy comparison (nDCG@5, P@5, MAP, MRR, Time)
    """
    metrics = ['nDCG@5', 'P@5', 'MAP', 'MRR', 'F1@5', 'retrieval_time']
    metric_labels = {
        'nDCG@5': 'nDCG@5',
        'P@5': 'P@5',
        'MAP': 'MAP',
        'MRR': 'MRR',
        'F1@5': 'F1@5',
        'retrieval_time': 'Time (s)',
    }

    strategies = list(aggregates.keys())

    # Find best per metric
    best = {}
    for m in metrics:
        values = []
        for s in strategies:
            if m in aggregates[s]:
                values.append((s, aggregates[s][m]['mean']))
        if values:
            if m == 'retrieval_time':
                best[m] = min(values, key=lambda x: x[1])[0]
            else:
                best[m] = max(values, key=lambda x: x[1])[0]

    # Build LaTeX
    n_cols = len(metrics)
    col_spec = "l" + "c" * n_cols
    lines = [
        f"\\begin{{table*}}[t]",
        f"\\centering",
        f"\\caption{{Retrieval Quality Comparison Across Strategies}}",
        f"\\label{{tab:main_comparison}}",
        f"\\begin{{tabular}}{{{col_spec}}}",
        f"\\toprule",
    ]

    # Header
    header = "Strategy"
    for m in metrics:
        header += f" & {metric_labels.get(m, m)}"
    header += " \\\\"
    lines.append(header)
    lines.append("\\midrule")

    # Add separator between baseline and H2L groups
    baseline_strategies = [s for s in strategies if not s.startswith('h2l')]
    h2l_strategies = [s for s in strategies if s.startswith('h2l')]

    for group_name, group in [("Baselines", baseline_strategies), ("H2L Strategies", h2l_strategies)]:
        if not group:
            continue
        for s in group:
            row = s.replace('_', '\\_')
            for m in metrics:
                if m in aggregates[s]:
                    mean = aggregates[s][m]['mean']
                    std = aggregates[s][m]['std']
                    is_best_val = best.get(m) == s
                    row += f" & {format_mean_std(mean, std, is_best_val)}"
                else:
                    row += " & --"
            row += " \\\\"
            lines.append(row)
        if group_name == "Baselines" and h2l_strategies:
            lines.append("\\midrule")

    lines.extend([
        "\\bottomrule",
        "\\end{tabular}",
        "\\end{table*}",
    ])

    return "\n".join(lines)


def generate_ablation_table(ablation_results: Dict = None) -> str:
    """
    Table 2: Ablation study results
    """
    lines = [
        "\\begin{table}[t]",
        "\\centering",
        "\\caption{Ablation Study Results}",
        "\\label{tab:ablation}",
        "\\begin{tabular}{lccc}",
        "\\toprule",
        "Configuration & nDCG@5 & P@5 & MAP \\\\",
        "\\midrule",
        "H2L V3 (Full) & -- & -- & -- \\\\",
        "\\quad w/o L2 Filtering & -- & -- & -- \\\\",
        "\\quad w/o Severity Prior & -- & -- & -- \\\\",
        "\\quad w/o Semantic Matching & -- & -- & -- \\\\",
        "\\quad $\\alpha = 0$ (No Problem Scoring) & -- & -- & -- \\\\",
        "\\bottomrule",
        "\\end{tabular}",
        "\\vspace{1mm}",
        "\\footnotesize{Values marked with -- to be filled after running updated ablation.}",
        "\\end{table}",
    ]
    return "\n".join(lines)


def generate_statistical_significance_table(stats: Dict) -> str:
    """
    Table 3: Pairwise statistical significance
    """
    lines = [
        "\\begin{table}[t]",
        "\\centering",
        "\\caption{Pairwise Statistical Comparison (nDCG@5)}",
        "\\label{tab:significance}",
        "\\begin{tabular}{lcccc}",
        "\\toprule",
        "Comparison & $p$-value & Cohen's $d$ & Effect & Sig. \\\\",
        "\\midrule",
    ]

    ndcg_stats = stats.get('nDCG@5', {}).get('pairwise', {})
    for pair, data in ndcg_stats.items():
        pair_clean = pair.replace('_', '\\_')
        sig = "$\\checkmark$" if data.get('significant') else "--"
        lines.append(
            f"{pair_clean} & {data.get('p_value', 0):.4f} & "
            f"{data.get('cohens_d', 0):.3f} & "
            f"{data.get('effect_interpretation', 'N/A')} & {sig} \\\\"
        )

    if not ndcg_stats:
        lines.append("\\multicolumn{5}{c}{\\textit{Run evaluation to populate}} \\\\")

    lines.extend([
        "\\bottomrule",
        "\\end{tabular}",
        "\\end{table}",
    ])
    return "\n".join(lines)


def generate_human_eval_table() -> str:
    """
    Table 4: Human evaluation results template
    """
    lines = [
        "\\begin{table}[t]",
        "\\centering",
        "\\caption{Human Evaluation by Domain Experts ($n$ evaluators)}",
        "\\label{tab:human_eval}",
        "\\begin{tabular}{lccc}",
        "\\toprule",
        "System & Relevance & Completeness & Usefulness \\\\",
        "\\midrule",
        "Baseline (Hybrid) & -- & -- & -- \\\\",
        "H2L-Hybrid & -- & -- & -- \\\\",
        "H2L-Adaptive & -- & -- & -- \\\\",
        "\\midrule",
        "\\multicolumn{4}{l}{Krippendorff's $\\alpha$: --} \\\\",
        "\\bottomrule",
        "\\end{tabular}",
        "\\vspace{1mm}",
        "\\footnotesize{Scores on 1--5 Likert scale. Values to be filled after expert evaluation.}",
        "\\end{table}",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description='Generate LaTeX tables')
    parser.add_argument('results_file', nargs='?', default=None,
                       help='Path to evaluation results JSON')
    parser.add_argument('--combined', nargs='+', default=None,
                       help='Multiple result files to combine')
    parser.add_argument('--output', default='paper_tables.tex',
                       help='Output .tex file')

    args = parser.parse_args()

    aggregates = {}
    stats = {}

    if args.combined:
        for f in args.combined:
            with open(f, 'r') as fh:
                data = json.load(fh)
                agg = data.get('aggregates', {})
                aggregates.update(agg)
                if 'statistical_tests' in data:
                    stats.update(data['statistical_tests'])
    elif args.results_file:
        with open(args.results_file, 'r') as f:
            data = json.load(f)
            aggregates = data.get('aggregates', {})
            stats = data.get('statistical_tests', {})

    tables = []

    # Table 1: Main comparison
    if aggregates:
        tables.append("% Table 1: Main Strategy Comparison")
        tables.append(generate_main_comparison_table(aggregates))
    else:
        tables.append("% Table 1: Template (run evaluation first)")
        tables.append(generate_main_comparison_table({
            'basic': {'nDCG@5': {'mean': 0, 'std': 0}},
            'h2l-hybrid': {'nDCG@5': {'mean': 0, 'std': 0}},
        }))

    tables.append("")

    # Table 2: Ablation
    tables.append("% Table 2: Ablation Study")
    tables.append(generate_ablation_table())
    tables.append("")

    # Table 3: Statistical significance
    tables.append("% Table 3: Statistical Significance")
    tables.append(generate_statistical_significance_table(stats))
    tables.append("")

    # Table 4: Human evaluation
    tables.append("% Table 4: Human Evaluation")
    tables.append(generate_human_eval_table())

    output = "\n\n".join(tables)

    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(output)

    print(f"✅ LaTeX tables saved to: {args.output}")
    print(f"   Tables generated: 4")
    if not aggregates:
        print(f"   ⚠️ No results data provided — template tables generated")
        print(f"   Run evaluation first, then: python paper_tables.py <results.json>")


if __name__ == "__main__":
    main()
