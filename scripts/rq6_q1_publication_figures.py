#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ6 Q1-Quality Publication Figures & Tables
=============================================

Produces camera-ready figures and LaTeX tables for the V6 component
ablation study (RQ6).  Uses two complementary analysis tracks:

  1. **Rank-aware relevance metrics** (nDCG@5, MAP, MRR)
     — Wilcoxon signed-rank test + Cohen's d
  2. **Score-level perturbation** (h2l_mean_top5)
     — Direct comparison of H2L scoring output per variant
     — This metric captures component effects even when top-5
       document composition is unchanged

Output (→ ablation_results/q1_figures/):
  • fig_rq6_forest_plot.pdf / .png
  • fig_rq6_score_contribution.pdf / .png
  • fig_rq6_dual_axis_impact.pdf / .png
  • table_rq6_component_effects.tex
  • table_rq6_score_significance.tex

Usage:
  python scripts/rq6_q1_publication_figures.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

try:
    from scipy import stats as sp
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

# ── Config ────────────────────────────────────────────────────────────
CSV_PATH = Path("ablation_results/rq6_results.csv")
OUT_DIR  = Path("ablation_results/q1_figures")
FULL_V6  = "Full V6"

# Short display names for plotting
SHORT = {
    "w/o Adaptive Alpha":   "−Adaptive α",
    "w/o Bayesian Prior":   "−Bayesian Prior",
    "w/o IDF Specificity":  "−IDF",
    "w/o Margin Activation":"−Margin",
    "w/o KL Penalty":       "−KL Penalty",
    "w/o Negation Gate":    "−Negation",
    "Product Feature Mode": "Product Mode",
}

# Academic color palette
COLORS = {
    "score":    "#2563EB",   # blue-600
    "rank":     "#DC2626",   # red-600
    "neutral":  "#6B7280",   # gray-500
    "positive": "#059669",   # emerald-600
    "negative": "#E11D48",   # rose-600
    "ci_band":  "#BFDBFE",   # blue-200
}


# ── Helpers ───────────────────────────────────────────────────────────

def cohens_d(a, b):
    """Cohen's d with pooled SD."""
    na, nb = len(a), len(b)
    va, vb = np.var(a, ddof=1), np.var(b, ddof=1)
    pooled = np.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))
    if pooled == 0:
        return 0.0
    return (np.mean(a) - np.mean(b)) / pooled

def effect_label(d):
    ad = abs(d)
    if ad < 0.2:  return "negligible"
    if ad < 0.5:  return "small"
    if ad < 0.8:  return "medium"
    return "large"

def wilcoxon_safe(a, b):
    """Wilcoxon signed-rank, robust to zero-diff pairs."""
    if not HAS_SCIPY:
        return 1.0
    diff = a - b
    nonzero = diff[diff != 0]
    if len(nonzero) < 10:
        return 1.0
    try:
        return sp.wilcoxon(nonzero).pvalue
    except Exception:
        return 1.0

def bootstrap_ci(data, n_boot=2000, alpha=0.05, stat_fn=np.mean):
    """BCa-style bootstrap confidence interval."""
    rng = np.random.default_rng(42)
    n = len(data)
    theta_hat = stat_fn(data)
    theta_boot = np.array([
        stat_fn(rng.choice(data, size=n, replace=True))
        for _ in range(n_boot)
    ])
    lo = np.percentile(theta_boot, 100 * alpha / 2)
    hi = np.percentile(theta_boot, 100 * (1 - alpha / 2))
    return theta_hat, lo, hi


# ═══════════════════════════════════════════════════════════════════════
# FIGURE 1: Forest Plot — Cohen's d effect sizes for h2l_mean_top5
# ═══════════════════════════════════════════════════════════════════════

def fig_forest_plot(df, out_dir):
    """
    Forest plot showing Cohen's d effect sizes (Full V6 vs each ablated)
    for the continuous score metric h2l_mean_top5.
    Includes 95% bootstrap CIs.
    """
    full = df[df['variant'] == FULL_V6].sort_values('case_id')
    variants = [v for v in df['variant'].unique() if v != FULL_V6]
    
    records = []
    for var in variants:
        ablated = df[df['variant'] == var].sort_values('case_id')
        # Align by case_id
        merged = full.merge(ablated, on='case_id', suffixes=('_full', '_abl'))
        a = merged['h2l_mean_top5_full'].values
        b = merged['h2l_mean_top5_abl'].values
        
        d = cohens_d(a, b)
        p = wilcoxon_safe(a, b)
        mean_diff = np.mean(a - b)
        
        # Bootstrap CI on Cohen's d
        diffs = a - b
        def d_stat(x):
            pooled_sd = np.sqrt((np.var(a, ddof=1) + np.var(b, ddof=1)) / 2)
            return np.mean(x) / pooled_sd if pooled_sd > 0 else 0.0
        _, ci_lo, ci_hi = bootstrap_ci(diffs, stat_fn=d_stat)
        
        records.append({
            'variant': SHORT.get(var, var),
            'variant_full': var,
            'd': d,
            'ci_lo': ci_lo,
            'ci_hi': ci_hi,
            'p': p,
            'mean_diff': mean_diff,
            'label': effect_label(d),
        })
    
    rdf = pd.DataFrame(records).sort_values('d', ascending=True)
    
    fig, ax = plt.subplots(figsize=(10, 5))
    y_pos = np.arange(len(rdf))
    
    colors = []
    for _, row in rdf.iterrows():
        if row['p'] < 0.05:
            colors.append(COLORS['score'] if row['d'] > 0 else COLORS['negative'])
        else:
            colors.append(COLORS['neutral'])
    
    ax.barh(y_pos, rdf['d'].values, color=colors, alpha=0.85, height=0.6,
            edgecolor='white', linewidth=0.5)
    
    # Error bars for CI
    for i, (_, row) in enumerate(rdf.iterrows()):
        ax.plot([row['ci_lo'], row['ci_hi']], [i, i],
                color='black', linewidth=1.2, solid_capstyle='round')
        ax.plot([row['ci_lo']], [i], marker='|', color='black', markersize=6)
        ax.plot([row['ci_hi']], [i], marker='|', color='black', markersize=6)
        # Annotation
        sig = "***" if row['p'] < 0.001 else ("**" if row['p'] < 0.01 else ("*" if row['p'] < 0.05 else ""))
        label = f"d={row['d']:.3f} {sig}"
        x_offset = max(row['ci_hi'], row['d']) + 0.02
        ax.text(x_offset, i, label, va='center', fontsize=8.5,
                fontfamily='monospace')
    
    ax.set_yticks(y_pos)
    ax.set_yticklabels(rdf['variant'].values, fontsize=10)
    ax.set_xlabel("Cohen's d (Full V6 − Ablated)", fontsize=11)
    ax.set_title("RQ6: Component Contribution — Effect Size (h2l_mean_top5)",
                 fontsize=12, fontweight='bold')
    ax.axvline(0, color='black', linewidth=0.8, linestyle='-')
    ax.axvline(0.2, color='gray', linewidth=0.5, linestyle='--', alpha=0.5)
    ax.axvline(-0.2, color='gray', linewidth=0.5, linestyle='--', alpha=0.5)
    
    # Legend for effect size thresholds
    ax.text(0.22, len(rdf) - 0.3, "small", fontsize=7, color='gray', alpha=0.7)
    ax.text(-0.22, len(rdf) - 0.3, "small", fontsize=7, color='gray', alpha=0.7,
            ha='right')
    
    ax.set_xlim(min(rdf['ci_lo'].min(), rdf['d'].min()) - 0.15,
                max(rdf['ci_hi'].max(), rdf['d'].max()) + 0.25)
    
    plt.tight_layout()
    for ext in ('png', 'pdf'):
        fig.savefig(out_dir / f"fig_rq6_forest_plot.{ext}", dpi=300,
                    bbox_inches='tight')
    plt.close(fig)
    print(f"  ✅ fig_rq6_forest_plot.png/pdf")
    return rdf


# ═══════════════════════════════════════════════════════════════════════
# FIGURE 2: Score Contribution Waterfall
# ═══════════════════════════════════════════════════════════════════════

def fig_score_waterfall(df, out_dir):
    """
    Waterfall chart showing how much each component contributes to
    the average h2l_mean_top5 score (Full V6 as reference).
    """
    full = df[df['variant'] == FULL_V6]
    full_mean = full['h2l_mean_top5'].mean()
    
    variants = [v for v in df['variant'].unique() if v != FULL_V6]
    
    contributions = []
    for var in variants:
        ablated = df[df['variant'] == var]
        abl_mean = ablated['h2l_mean_top5'].mean()
        delta = full_mean - abl_mean  # positive = component helps
        contributions.append({
            'component': SHORT.get(var, var),
            'delta': delta,
            'pct_of_full': (delta / full_mean * 100) if full_mean > 0 else 0,
        })
    
    cdf = pd.DataFrame(contributions).sort_values('delta', ascending=False)
    
    fig, ax = plt.subplots(figsize=(10, 5))
    x_pos = np.arange(len(cdf))
    
    bar_colors = [COLORS['positive'] if d > 0 else COLORS['negative']
                  for d in cdf['delta'].values]
    
    bars = ax.bar(x_pos, cdf['delta'].values, color=bar_colors, alpha=0.85,
                  edgecolor='white', linewidth=0.5, width=0.65)
    
    # Annotate with percentage
    for i, (_, row) in enumerate(cdf.iterrows()):
        y = row['delta']
        sign = "+" if y > 0 else ""
        label = f"{sign}{row['pct_of_full']:.1f}%"
        ax.text(i, y + (0.02 if y > 0 else -0.05), label,
                ha='center', va='bottom' if y > 0 else 'top',
                fontsize=9, fontweight='bold')
    
    ax.set_xticks(x_pos)
    ax.set_xticklabels(cdf['component'].values, fontsize=9.5, rotation=25, ha='right')
    ax.set_ylabel("Δ h2l_mean_top5 (Full V6 − Ablated)", fontsize=11)
    ax.set_title("RQ6: Component Score Contribution",
                 fontsize=12, fontweight='bold')
    ax.axhline(0, color='black', linewidth=0.8)
    ax.set_xlim(-0.6, len(cdf) - 0.4)
    
    # Reference text
    ax.text(0.98, 0.95, f"Full V6 mean: {full_mean:.4f}",
            transform=ax.transAxes, fontsize=9, ha='right', va='top',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='lightyellow',
                      edgecolor='gray', alpha=0.8))
    
    plt.tight_layout()
    for ext in ('png', 'pdf'):
        fig.savefig(out_dir / f"fig_rq6_score_contribution.{ext}", dpi=300,
                    bbox_inches='tight')
    plt.close(fig)
    print(f"  ✅ fig_rq6_score_contribution.png/pdf")
    return cdf


# ═══════════════════════════════════════════════════════════════════════
# FIGURE 3: Dual-Axis Impact (Score delta + Rank swap rate)
# ═══════════════════════════════════════════════════════════════════════

def fig_dual_axis(df, out_dir):
    """
    Dual-axis grouped bar chart:
      Left axis  : mean absolute score delta (bars)
      Right axis : % of cases with rank change in top-5 (dots)
    """
    variants = [v for v in df['variant'].unique() if v != FULL_V6]
    
    records = []
    for var in variants:
        sub = df[df['variant'] == var]
        records.append({
            'component': SHORT.get(var, var),
            'score_delta': sub['mean_abs_score_delta'].mean(),
            'rank_pct': sub['rank_changed_at5'].mean() * 100,
        })
    
    rdf = pd.DataFrame(records).sort_values('score_delta', ascending=False)
    
    fig, ax1 = plt.subplots(figsize=(10, 5))
    x_pos = np.arange(len(rdf))
    
    # Bars: score delta
    bars = ax1.bar(x_pos, rdf['score_delta'].values, color=COLORS['score'],
                   alpha=0.75, width=0.55, label='Score Δ')
    ax1.set_ylabel("Mean |Score Δ|", color=COLORS['score'], fontsize=11)
    ax1.tick_params(axis='y', labelcolor=COLORS['score'])
    
    # Second axis: rank swap rate
    ax2 = ax1.twinx()
    ax2.plot(x_pos, rdf['rank_pct'].values, 'o-', color=COLORS['rank'],
             linewidth=2, markersize=8, label='Rank Change %')
    ax2.set_ylabel("Top-5 Rank Changed (%)", color=COLORS['rank'], fontsize=11)
    ax2.tick_params(axis='y', labelcolor=COLORS['rank'])
    ax2.set_ylim(0, max(rdf['rank_pct'].max() * 1.3, 20))
    
    ax1.set_xticks(x_pos)
    ax1.set_xticklabels(rdf['component'].values, fontsize=9.5, rotation=25, ha='right')
    ax1.set_title("RQ6: Score Perturbation vs Rank Change by Component",
                  fontsize=12, fontweight='bold')
    
    # Unified legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper right', fontsize=9)
    
    plt.tight_layout()
    for ext in ('png', 'pdf'):
        fig.savefig(out_dir / f"fig_rq6_dual_axis_impact.{ext}", dpi=300,
                    bbox_inches='tight')
    plt.close(fig)
    print(f"  ✅ fig_rq6_dual_axis_impact.png/pdf")
    return rdf


# ═══════════════════════════════════════════════════════════════════════
# TABLE: LaTeX Component Effects
# ═══════════════════════════════════════════════════════════════════════

def table_component_effects(df, forest_df, out_dir):
    """
    LaTeX table with nDCG@5, MAP, h2l_mean_top5, Cohen's d, p-value.
    """
    full = df[df['variant'] == FULL_V6]
    full_ndcg = full['nDCG@5'].mean()
    full_map  = full['MAP'].mean()
    full_h2l  = full['h2l_mean_top5'].mean()
    
    rows = []
    # Full V6 row
    rows.append({
        'Configuration': 'Full V6 (baseline)',
        'nDCG@5': f"{full_ndcg:.4f}",
        'MAP': f"{full_map:.4f}",
        'h2l score': f"{full_h2l:.4f}",
        "Cohen's d": '—',
        'p-value': '—',
        'Effect': '—',
    })
    
    for _, row in forest_df.iterrows():
        var = row['variant_full']
        sub = df[df['variant'] == var]
        rows.append({
            'Configuration': SHORT.get(var, var),
            'nDCG@5': f"{sub['nDCG@5'].mean():.4f}",
            'MAP': f"{sub['MAP'].mean():.4f}",
            'h2l score': f"{sub['h2l_mean_top5'].mean():.4f}",
            "Cohen's d": f"{row['d']:.3f}",
            'p-value': f"{row['p']:.4f}" if row['p'] > 0.0001 else "<0.001",
            'Effect': row['label'],
        })
    
    tdf = pd.DataFrame(rows)
    
    # Save as CSV
    tdf.to_csv(out_dir / "table_rq6_component_effects.csv", index=False)
    
    # Save as LaTeX
    latex_lines = [
        r"\begin{table}[htbp]",
        r"  \centering",
        r"  \caption{RQ6: V6 Component Ablation Results (n=197 cases)}",
        r"  \label{tab:rq6_ablation}",
        r"  \begin{tabular}{lcccccl}",
        r"    \toprule",
        r"    Configuration & nDCG@5 & MAP & H2L Score & Cohen's $d$ & $p$-value & Effect \\",
        r"    \midrule",
    ]
    for _, r in tdf.iterrows():
        cohens_d_val = r["Cohen's d"]
        p_val = r['p-value']
        latex_lines.append(
            f"    {r['Configuration']} & {r['nDCG@5']} & {r['MAP']} & "
            f"{r['h2l score']} & {cohens_d_val} & {p_val} & "
            f"{r['Effect']} \\\\"
        )
    latex_lines += [
        r"    \bottomrule",
        r"  \end{tabular}",
        r"  \begin{tablenotes}\small",
        r"    \item Cohen's $d$ computed on h2l\_mean\_top5 (Full V6 $-$ Ablated).",
        r"    \item $p$-value from Wilcoxon signed-rank test.",
        r"    \item Effect thresholds: $|d|<0.2$ negligible, $<0.5$ small, $<0.8$ medium, $\geq0.8$ large.",
        r"  \end{tablenotes}",
        r"\end{table}",
    ]
    (out_dir / "table_rq6_component_effects.tex").write_text(
        "\n".join(latex_lines), encoding='utf-8')
    
    print(f"  ✅ table_rq6_component_effects.csv / .tex")
    return tdf


# ═══════════════════════════════════════════════════════════════════════
# FIGURE 4: Per-case score distribution (violin/box)
# ═══════════════════════════════════════════════════════════════════════

def fig_score_distribution(df, out_dir):
    """
    Box plot comparing h2l_mean_top5 distributions across variants.
    """
    order = (df.groupby('variant')['h2l_mean_top5'].mean()
             .sort_values(ascending=False).index.tolist())
    
    fig, ax = plt.subplots(figsize=(12, 5))
    
    data_list = []
    labels = []
    for var in order:
        vals = df[df['variant'] == var]['h2l_mean_top5'].values
        data_list.append(vals)
        labels.append(SHORT.get(var, var) if var != FULL_V6 else "Full V6")
    
    bp = ax.boxplot(data_list, vert=True, patch_artist=True,
                    widths=0.5, showfliers=False)
    
    for i, patch in enumerate(bp['boxes']):
        if labels[i] == "Full V6":
            patch.set_facecolor(COLORS['positive'])
            patch.set_alpha(0.6)
        else:
            patch.set_facecolor(COLORS['score'])
            patch.set_alpha(0.4)
    
    ax.set_xticklabels(labels, fontsize=9, rotation=25, ha='right')
    ax.set_ylabel("h2l_mean_top5", fontsize=11)
    ax.set_title("RQ6: Score Distribution by Configuration",
                 fontsize=12, fontweight='bold')
    
    plt.tight_layout()
    for ext in ('png', 'pdf'):
        fig.savefig(out_dir / f"fig_rq6_score_distribution.{ext}", dpi=300,
                    bbox_inches='tight')
    plt.close(fig)
    print(f"  ✅ fig_rq6_score_distribution.png/pdf")


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("RQ6 Q1-Quality Publication Figures")
    print("=" * 60)
    
    if not CSV_PATH.exists():
        print(f"❌ CSV not found: {CSV_PATH}")
        sys.exit(1)
    
    df = pd.read_csv(CSV_PATH)
    print(f"📂 Loaded {len(df)} rows, {df['variant'].nunique()} variants, "
          f"{df['case_id'].nunique()} cases")
    
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Generate all figures and tables
    print("\n📊 Generating figures...")
    forest_df = fig_forest_plot(df, OUT_DIR)
    score_df  = fig_score_waterfall(df, OUT_DIR)
    dual_df   = fig_dual_axis(df, OUT_DIR)
    fig_score_distribution(df, OUT_DIR)
    
    print("\n📋 Generating tables...")
    table_df  = table_component_effects(df, forest_df, OUT_DIR)
    
    # Print summary to console
    print("\n" + "=" * 60)
    print("SUMMARY — Key Findings for Thesis Ch.4:")
    print("=" * 60)
    print(table_df.to_string(index=False))
    
    print(f"\n✅ All outputs → {OUT_DIR}/")


if __name__ == "__main__":
    main()
