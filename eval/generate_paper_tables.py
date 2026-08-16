#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate LaTeX Tables for Paper from Evaluation Results
========================================================
Reads proper_eval_latest_summary.json and generates publication-ready LaTeX tables.
"""

import json
from pathlib import Path


def load_latest_results(results_dir='evaluation_results'):
    """Load latest evaluation summary"""
    summary_path = Path(results_dir) / 'proper_eval_latest_summary.json'
    with open(summary_path) as f:
        return json.load(f)


def format_metric(mean, std, bold=False):
    """Format metric as mean ± std"""
    formatted = f"{mean:.4f} ± {std:.4f}"
    if bold:
        formatted = f"\\textbf{{{formatted}}}"
    return formatted


def generate_main_comparison_table(data):
    """Generate Table 1: Main Strategy Comparison"""
    aggregates = data['aggregates']

    # Strategy order
    strategies = [
        ('bm25_only', 'bm25\\_only'),
        ('naive_rag', 'naive\\_rag'),
        ('hyde', 'hyde'),
        ('basic', 'basic'),
        ('h2l-bm25', 'h2l-bm25'),
        ('h2l-naive_rag', 'h2l-naive\\_rag'),
        ('h2l-hyde', 'h2l-hyde'),
        ('h2l-hybrid', 'h2l-hybrid'),
    ]

    metrics = ['nDCG@5', 'P@5', 'MAP', 'MRR', 'F1@5', 'retrieval_time']
    metric_labels = ['nDCG@5', 'P@5', 'MAP', 'MRR', 'F1@5', 'Time (s)']

    # Find best values for each metric (excluding time)
    best_values = {}
    for metric in metrics[:-1]:  # exclude time
        best_values[metric] = max(
            aggregates[strat][metric]['mean']
            for strat, _ in strategies if strat in aggregates and metric in aggregates[strat]
        )

    # Find best time (minimum)
    best_values['retrieval_time'] = min(
        aggregates[strat]['retrieval_time']['mean']
        for strat, _ in strategies if strat in aggregates and 'retrieval_time' in aggregates[strat]
    )

    lines = [
        "% Table 1: Main Strategy Comparison",
        "",
        "\\begin{table*}[t]",
        "\\centering",
        "\\caption{Retrieval Quality Comparison Across Strategies (Corpus-Level Metrics)}",
        "\\label{tab:main_comparison}",
        "\\begin{tabular}{lcccccc}",
        "\\toprule",
        "Strategy & " + " & ".join(metric_labels) + " \\\\",
        "\\midrule",
    ]

    for i, (strat, display_name) in enumerate(strategies):
        if strat not in aggregates:
            continue

        agg = aggregates[strat]
        values = []

        for metric in metrics:
            if metric not in agg:
                values.append("--")
                continue

            mean = agg[metric]['mean']
            std = agg[metric]['std']

            # Bold if best (or closest for time)
            is_best = abs(mean - best_values[metric]) < 1e-6
            values.append(format_metric(mean, std, bold=is_best))

        line = display_name + " & " + " & ".join(values) + " \\\\"
        lines.append(line)

        # Add midrule after baseline strategies
        if i == 3:  # after 'basic'
            lines.append("\\midrule")

    lines.extend([
        "\\bottomrule",
        "\\end{tabular}",
        "\\end{table*}",
        "",
    ])

    return "\n".join(lines)


def generate_statistical_significance_table(data):
    """Generate Table 3: Statistical Significance (nDCG@5 with Holm correction)"""
    stats = data.get('statistical_tests', {})
    if 'nDCG@5' not in stats:
        return "% Statistical tests not available\n"

    ndcg_stats = stats['nDCG@5']
    pairwise = ndcg_stats.get('pairwise', {})
    correction = ndcg_stats.get('multiple_comparison_correction', 'none')

    lines = [
        "% Table 3: Statistical Significance",
        "",
        "\\begin{table*}[t]",
        "\\centering",
        f"\\caption{{Pairwise Statistical Comparison (nDCG@5, Wilcoxon two-sided + {correction.replace('_', ' ').title()})}}",
        "\\label{tab:significance}",
        "\\begin{tabular}{lcccl}",
        "\\toprule",
        "Comparison & $p$-value (Holm) & Cohen's $d$ & $\\Delta$ & Effect \\\\",
        "\\midrule",
    ]

    # Sort by comparison name for consistency
    sorted_pairs = sorted(pairwise.items())

    for pair_name, stats_data in sorted_pairs:
        # Format comparison name
        comp_display = pair_name.replace('_', '\\_')

        p_holm = stats_data.get('p_value_holm', stats_data.get('p_value_raw', 1.0))
        cohens_d = stats_data.get('cohens_d', 0.0)
        mean_diff = stats_data.get('mean_diff', 0.0)
        effect = stats_data.get('effect_interpretation', 'unknown')
        sig = stats_data.get('significant_holm', False)

        # Format p-value with significance marker
        if p_holm < 0.0001:
            p_str = "$<$0.0001"
        else:
            p_str = f"{p_holm:.4f}"

        # Add significance marker only if actually significant
        if sig:
            # Append to comparison name instead of p-value for clarity
            comp_display += "$^*$"

        line = f"{comp_display} & {p_str} & {cohens_d:+.3f} & {mean_diff:+.4f} & {effect} \\\\"
        lines.append(line)

    lines.extend([
        "\\bottomrule",
        "\\end{tabular}",
        "\\vspace{2mm}",
        "\\footnotesize{$^*$ indicates $p < 0.05$ after Holm–Bonferroni correction. " +
        f"Total comparisons: {ndcg_stats.get('n_comparisons', 0)}.}}",
        "\\end{table*}",
        "",
    ])

    return "\n".join(lines)


def generate_all_tables(results_dir='evaluation_results', output_path=None):
    """Generate all LaTeX tables"""
    data = load_latest_results(results_dir)

    tables = []
    tables.append(generate_main_comparison_table(data))
    tables.append("\n\n")
    tables.append(generate_statistical_significance_table(data))

    latex_content = "\n".join(tables)

    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(latex_content)
        print(f"✅ Tables written to {output_path}")

    return latex_content


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Generate LaTeX tables from evaluation results')
    parser.add_argument('--results-dir', default='evaluation_results',
                       help='Directory containing proper_eval_latest_summary.json')
    parser.add_argument('--output', default='evaluation_results/paper_tables_generated.tex',
                       help='Output LaTeX file')

    args = parser.parse_args()

    latex = generate_all_tables(args.results_dir, args.output)
    print("\n" + "="*70)
    print("Preview:")
    print("="*70)
    print(latex[:1000] + "\n...\n")
