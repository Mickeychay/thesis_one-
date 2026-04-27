#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Blind Expert Evaluation — Inter-Rater Agreement Analysis
=========================================================

Analyzes completed evaluation_form.csv from blind expert panel.

Metrics:
  - Cohen's κ  (pairwise, linear-weighted for ordinal scores)
  - Fleiss' κ  (multi-rater overall)
  - ICC(2,1)   (two-way mixed, single measures — continuous scores)
  - System A vs B: Wilcoxon signed-rank per metric
  - Slice analysis: negation cases, high-severity cases

Usage:
  python scripts/analyze_expert_agreement.py
  python scripts/analyze_expert_agreement.py --form human_evaluation/blind_packet_latest/evaluation_form.csv
  python scripts/analyze_expert_agreement.py --dry-run   # test with mock data

Output:
  human_evaluation/analysis/
    agreement_report.md
    cohen_kappa_pairwise.csv
    fleiss_kappa_overall.csv
    icc_results.csv
    system_comparison.csv
    plots/
      inter_rater_heatmap.png
      system_a_vs_b_boxplot.png
"""

import argparse
import sys
import warnings
from pathlib import Path
from itertools import combinations

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# ── Optional heavy deps ───────────────────────────────────────────────────────
try:
    from scipy import stats
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    print("⚠️  scipy not found — Wilcoxon tests will be skipped. pip install scipy")

try:
    import pingouin as pg
    HAS_PINGOUIN = True
except ImportError:
    HAS_PINGOUIN = False
    print("⚠️  pingouin not found — ICC will be skipped. pip install pingouin")

try:
    from sklearn.metrics import cohen_kappa_score
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False
    print("⚠️  sklearn not found — Cohen's κ will be skipped. pip install scikit-learn")

warnings.filterwarnings('ignore')


def _df_to_md(df: pd.DataFrame) -> str:
    """Convert DataFrame to markdown table without tabulate dependency."""
    if df.empty:
        return "_empty_"
    cols = list(df.columns)
    header = "| " + " | ".join(str(c) for c in cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    rows = []
    for _, row in df.iterrows():
        rows.append("| " + " | ".join(str(row[c]) for c in cols) + " |")
    return "\n".join([header, sep] + rows)

# ── Constants ─────────────────────────────────────────────────────────────────
SCORE_COLS = ['relevance_score', 'completeness_score', 'clinical_usefulness_score']
ORDINAL_COLS = ['relevance_score']          # 1-5 Likert → weighted κ
CONTINUOUS_COLS = ['completeness_score', 'clinical_usefulness_score']  # ICC

# Negation case IDs (from evaluation form)
NEGATION_CASE_IDS = {
    'NEG_MM_NEG', 'NEG_MM_POS', 'NEG_MM_POS_V2',
    'NEG_ML_NEG_V2', 'NEG_LL_NEG_V2',
}
HIGH_SEVERITY_PREFIXES = ('SUBSTANCE', 'MENTAL', 'HOMELESS')

OUTPUT_DIR = Path("human_evaluation/analysis")
PLOTS_DIR = OUTPUT_DIR / "plots"


# ═════════════════════════════════════════════════════════════════════════════
# MOCK DATA — for dry-run validation
# ═════════════════════════════════════════════════════════════════════════════

def make_mock_data() -> pd.DataFrame:
    """Generate synthetic 3-evaluator data for dry-run testing."""
    rng = np.random.default_rng(42)
    case_ids = ['ELDER_001', 'MENTAL_003', 'NEG_MM_POS', 'HOMELESS_001',
                'SUBSTANCE_002', 'NEG_ML_NEG_V2', 'NCD_008', 'BEDRIDDEN_002']
    systems = ['System_A', 'System_B']
    evaluators = ['E01', 'E02', 'E03']

    rows = []
    for case_id in case_ids:
        for sys in systems:
            base_rel = rng.integers(2, 5)
            base_comp = rng.uniform(2, 5)
            base_use = rng.uniform(2, 5)
            for ev in evaluators:
                rows.append({
                    'evaluator_id': ev,
                    'case_id': case_id,
                    'system_label': sys,
                    'relevance_score': int(np.clip(base_rel + rng.integers(-1, 2), 1, 5)),
                    'completeness_score': float(np.clip(base_comp + rng.uniform(-0.5, 0.5), 1, 5)),
                    'clinical_usefulness_score': float(np.clip(base_use + rng.uniform(-0.5, 0.5), 1, 5)),
                    'comments': '',
                })
    return pd.DataFrame(rows)


# ═════════════════════════════════════════════════════════════════════════════
# LOADING
# ═════════════════════════════════════════════════════════════════════════════

def load_form(form_path: Path) -> pd.DataFrame:
    df = pd.read_csv(form_path, encoding='utf-8-sig')
    df.columns = [c.strip() for c in df.columns]

    # Drop rows where evaluator_id is empty (not yet filled by expert)
    df = df[df['evaluator_id'].notna() & (df['evaluator_id'].astype(str).str.strip() != '')]

    for col in SCORE_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    n_filled = df['evaluator_id'].nunique()
    n_cases = df['case_id'].nunique()
    print(f"✅ Loaded: {len(df)} rows | {n_filled} evaluators | {n_cases} cases")

    if n_filled < 2:
        print("⚠️  Need ≥2 evaluators for agreement analysis. Run --dry-run to test.")
    return df


# ═════════════════════════════════════════════════════════════════════════════
# COHEN'S κ  (pairwise, linear-weighted for ordinal)
# ═════════════════════════════════════════════════════════════════════════════

def compute_cohen_kappa(df: pd.DataFrame) -> pd.DataFrame:
    if not HAS_SKLEARN:
        return pd.DataFrame()

    evaluators = sorted(df['evaluator_id'].unique())
    rows = []

    for col in ORDINAL_COLS:
        for ev1, ev2 in combinations(evaluators, 2):
            d1 = df[df['evaluator_id'] == ev1].set_index(['case_id', 'system_label'])[col]
            d2 = df[df['evaluator_id'] == ev2].set_index(['case_id', 'system_label'])[col]
            common = d1.index.intersection(d2.index)
            if len(common) < 5:
                continue
            v1 = d1.loc[common].values.astype(int)
            v2 = d2.loc[common].values.astype(int)
            mask = ~(np.isnan(v1) | np.isnan(v2))
            if mask.sum() < 5:
                continue
            kappa = cohen_kappa_score(v1[mask], v2[mask], weights='linear')
            rows.append({
                'evaluator_1': ev1, 'evaluator_2': ev2,
                'metric': col, 'n_cases': int(mask.sum()),
                'cohen_kappa_linear': round(kappa, 4),
                'interpretation': _kappa_label(kappa),
            })

    return pd.DataFrame(rows)


def _kappa_label(k: float) -> str:
    if k < 0.20: return 'slight'
    if k < 0.40: return 'fair'
    if k < 0.60: return 'moderate'
    if k < 0.80: return 'substantial'
    return 'almost perfect'


# ═════════════════════════════════════════════════════════════════════════════
# FLEISS' κ  (multi-rater)
# ═════════════════════════════════════════════════════════════════════════════

def fleiss_kappa(ratings_matrix: np.ndarray, n_categories: int) -> float:
    """
    ratings_matrix: shape (n_subjects, n_raters), values in 1..n_categories
    Returns Fleiss' κ.
    """
    n_subjects, n_raters = ratings_matrix.shape
    # Build category frequency table
    cat_counts = np.zeros((n_subjects, n_categories))
    for j in range(n_raters):
        for i in range(n_subjects):
            cat = int(ratings_matrix[i, j]) - 1  # 0-indexed
            if 0 <= cat < n_categories:
                cat_counts[i, cat] += 1

    p_j = cat_counts.sum(axis=0) / (n_subjects * n_raters)
    P_bar = (cat_counts ** 2).sum(axis=1)
    P_bar = (P_bar - n_raters) / (n_raters * (n_raters - 1))
    P_bar_mean = P_bar.mean()
    P_e = (p_j ** 2).sum()
    if P_e == 1.0:
        return 1.0
    kappa = (P_bar_mean - P_e) / (1 - P_e)
    return float(kappa)


def compute_fleiss_kappa(df: pd.DataFrame) -> pd.DataFrame:
    evaluators = sorted(df['evaluator_id'].unique())
    if len(evaluators) < 2:
        return pd.DataFrame()

    rows = []
    for col in ORDINAL_COLS:
        pivot = df.pivot_table(
            index=['case_id', 'system_label'],
            columns='evaluator_id',
            values=col,
            aggfunc='first'
        )
        pivot = pivot.dropna()
        if pivot.empty or len(pivot) < 5:
            continue
        mat = pivot.values.astype(int)
        k = fleiss_kappa(mat, n_categories=5)
        rows.append({
            'metric': col,
            'n_subjects': len(pivot),
            'n_raters': len(evaluators),
            'fleiss_kappa': round(k, 4),
            'interpretation': _kappa_label(k),
        })
    return pd.DataFrame(rows)


# ═════════════════════════════════════════════════════════════════════════════
# ICC(2,1)  (two-way mixed, single measures)
# ═════════════════════════════════════════════════════════════════════════════

def compute_icc(df: pd.DataFrame) -> pd.DataFrame:
    if not HAS_PINGOUIN:
        return pd.DataFrame()

    rows = []
    for col in CONTINUOUS_COLS + ORDINAL_COLS:
        if col not in df.columns:
            continue
        icc_df = df[['case_id', 'system_label', 'evaluator_id', col]].copy()
        icc_df['subject'] = icc_df['case_id'] + '_' + icc_df['system_label']
        icc_df = icc_df.dropna(subset=[col])
        if icc_df['evaluator_id'].nunique() < 2 or len(icc_df) < 10:
            continue
        try:
            result = pg.intraclass_corr(
                data=icc_df, targets='subject', raters='evaluator_id', ratings=col
            )
            icc21 = result[result['Type'] == 'ICC2'].iloc[0]
            rows.append({
                'metric': col,
                'ICC_type': 'ICC(2,1)',
                'icc': round(float(icc21['ICC']), 4),
                'CI95_lower': round(float(icc21['CI95%'][0]), 4),
                'CI95_upper': round(float(icc21['CI95%'][1]), 4),
                'F': round(float(icc21['F']), 3),
                'p_value': round(float(icc21['pval']), 4),
                'interpretation': _icc_label(float(icc21['ICC'])),
            })
        except Exception as e:
            print(f"  ⚠️  ICC failed for {col}: {e}")
    return pd.DataFrame(rows)


def _icc_label(icc: float) -> str:
    if icc < 0.50: return 'poor'
    if icc < 0.75: return 'moderate'
    if icc < 0.90: return 'good'
    return 'excellent'


# ═════════════════════════════════════════════════════════════════════════════
# SYSTEM A vs B COMPARISON
# ═════════════════════════════════════════════════════════════════════════════

def compute_system_comparison(df: pd.DataFrame) -> pd.DataFrame:
    if not HAS_SCIPY:
        return pd.DataFrame()

    sys_a = df[df['system_label'] == 'System_A']
    sys_b = df[df['system_label'] == 'System_B']

    rows = []
    for col in SCORE_COLS:
        if col not in df.columns:
            continue
        # Average over evaluators per (case_id, system)
        avg_a = sys_a.groupby('case_id')[col].mean()
        avg_b = sys_b.groupby('case_id')[col].mean()
        common = avg_a.index.intersection(avg_b.index)
        if len(common) < 5:
            continue
        a_vals = avg_a.loc[common].values
        b_vals = avg_b.loc[common].values

        stat, p = stats.wilcoxon(a_vals, b_vals, zero_method='wilcox', alternative='two-sided')
        effect_r = stat / (len(common) * (len(common) + 1) / 2) ** 0.5

        rows.append({
            'metric': col,
            'System_A_mean': round(float(a_vals.mean()), 4),
            'System_B_mean': round(float(b_vals.mean()), 4),
            'delta_A_minus_B': round(float((a_vals - b_vals).mean()), 4),
            'wilcoxon_stat': round(float(stat), 2),
            'p_value': round(float(p), 4),
            'effect_r': round(float(effect_r), 4),
            'n_cases': len(common),
            'significant_p05': p < 0.05,
        })
    return pd.DataFrame(rows)


# ═════════════════════════════════════════════════════════════════════════════
# SLICE ANALYSIS
# ═════════════════════════════════════════════════════════════════════════════

def compute_slice_analysis(df: pd.DataFrame, sys_compare: pd.DataFrame) -> pd.DataFrame:
    """System A vs B delta broken down by case type."""
    rows = []

    def _slice_delta(mask_label: str, mask: pd.Series):
        sub = df[mask]
        for col in SCORE_COLS:
            if col not in sub.columns:
                continue
            avg_a = sub[sub['system_label'] == 'System_A'].groupby('case_id')[col].mean()
            avg_b = sub[sub['system_label'] == 'System_B'].groupby('case_id')[col].mean()
            common = avg_a.index.intersection(avg_b.index)
            if len(common) < 3:
                continue
            delta = (avg_a.loc[common] - avg_b.loc[common]).mean()
            rows.append({
                'slice': mask_label,
                'metric': col,
                'n_cases': len(common),
                'delta_A_minus_B_mean': round(float(delta), 4),
            })

    # Negation cases
    neg_mask = df['case_id'].isin(NEGATION_CASE_IDS)
    _slice_delta('negation_cases', neg_mask)
    _slice_delta('non_negation_cases', ~neg_mask)

    # High-severity (by prefix)
    hi_mask = df['case_id'].str.startswith(tuple(HIGH_SEVERITY_PREFIXES), na=False)
    _slice_delta('high_severity_cases', hi_mask)
    _slice_delta('other_cases', ~hi_mask)

    return pd.DataFrame(rows)


# ═════════════════════════════════════════════════════════════════════════════
# PLOTS
# ═════════════════════════════════════════════════════════════════════════════

def plot_inter_rater_heatmap(cohen_df: pd.DataFrame, out_dir: Path):
    if cohen_df.empty:
        return
    out_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(8, 5))
    pivot = cohen_df.pivot_table(
        index='evaluator_1', columns='evaluator_2',
        values='cohen_kappa_linear', aggfunc='mean'
    )
    im = ax.imshow(pivot.values, vmin=-1, vmax=1, cmap='RdYlGn', aspect='auto')
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns, rotation=45, ha='right')
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            val = pivot.values[i, j]
            if not np.isnan(val):
                ax.text(j, i, f'{val:.2f}', ha='center', va='center',
                        fontsize=10, fontweight='bold',
                        color='black' if abs(val) < 0.6 else 'white')
    plt.colorbar(im, ax=ax, label="Cohen's κ (linear-weighted)")
    ax.set_title("Inter-Rater Agreement — Cohen's κ Heatmap", fontsize=13, fontweight='bold')
    ax.set_xlabel('Evaluator')
    ax.set_ylabel('Evaluator')
    plt.tight_layout()
    plt.savefig(out_dir / 'inter_rater_heatmap.png', dpi=300, bbox_inches='tight')
    plt.close()
    print("✅ Saved: inter_rater_heatmap.png")


def plot_system_comparison(df: pd.DataFrame, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    cols_available = [c for c in SCORE_COLS if c in df.columns]
    if not cols_available:
        return

    fig, axes = plt.subplots(1, len(cols_available), figsize=(5 * len(cols_available), 5))
    if len(cols_available) == 1:
        axes = [axes]

    palette = {'System_A': '#3498DB', 'System_B': '#E74C3C'}
    for ax, col in zip(axes, cols_available):
        avg = df.groupby(['case_id', 'system_label'])[col].mean().reset_index()
        for sys, color in palette.items():
            vals = avg[avg['system_label'] == sys][col].dropna()
            ax.boxplot(vals, positions=[list(palette.keys()).index(sys)],
                       widths=0.4, patch_artist=True,
                       boxprops=dict(facecolor=color, alpha=0.7),
                       medianprops=dict(color='black', linewidth=2))
        ax.set_xticks([0, 1])
        ax.set_xticklabels(list(palette.keys()))
        ax.set_title(col.replace('_', ' ').title(), fontsize=11, fontweight='bold')
        ax.set_ylabel('Score (1–5)')
        ax.set_ylim([0.5, 5.5])
        ax.grid(axis='y', alpha=0.3)

    fig.suptitle('System A vs System B — Expert Scores', fontsize=13, fontweight='bold')
    plt.tight_layout()
    plt.savefig(out_dir / 'system_a_vs_b_boxplot.png', dpi=300, bbox_inches='tight')
    plt.close()
    print("✅ Saved: system_a_vs_b_boxplot.png")


# ═════════════════════════════════════════════════════════════════════════════
# REPORT
# ═════════════════════════════════════════════════════════════════════════════

def write_report(df, cohen_df, fleiss_df, icc_df, sys_df, slice_df, out_path: Path):
    evaluators = sorted(df['evaluator_id'].unique())
    n_cases = df['case_id'].nunique()

    lines = [
        "# Expert Evaluation — Agreement Analysis Report",
        "",
        f"**Generated:** {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}  ",
        f"**Evaluators:** {len(evaluators)} ({', '.join(evaluators)})  ",
        f"**Unique cases:** {n_cases}  ",
        "",
        "---",
        "",
        "## 1. Cohen's κ (Pairwise, Linear-Weighted)",
        "",
    ]

    if not cohen_df.empty:
        lines.append(_df_to_md(cohen_df))
        avg_k = cohen_df['cohen_kappa_linear'].mean()
        lines += ["", f"**Average κ across pairs:** {avg_k:.4f} ({_kappa_label(avg_k)})"]
    else:
        lines.append("_Not computed (need sklearn or ≥2 evaluators)_")

    lines += ["", "---", "", "## 2. Fleiss' κ (Multi-Rater Overall)", ""]
    if not fleiss_df.empty:
        lines.append(_df_to_md(fleiss_df))
    else:
        lines.append("_Not computed (need ≥2 evaluators)_")

    lines += ["", "---", "", "## 3. ICC(2,1) — Two-Way Mixed, Single Measures", ""]
    if not icc_df.empty:
        lines.append(_df_to_md(icc_df))
    else:
        lines.append("_Not computed (need pingouin)_")

    lines += ["", "---", "", "## 4. System A vs System B", ""]
    if not sys_df.empty:
        lines.append(_df_to_md(sys_df))
        sig = sys_df[sys_df['significant_p05']]
        if not sig.empty:
            lines += ["", f"**Significant differences (p<.05):** {', '.join(sig['metric'].tolist())}"]
        else:
            lines += ["", "**No significant differences at p<.05**"]
    else:
        lines.append("_Not computed (need scipy or ≥5 cases per system)_")

    lines += ["", "---", "", "## 5. Slice Analysis — Delta (System A − System B)", ""]
    if not slice_df.empty:
        lines.append(_df_to_md(slice_df))
    else:
        lines.append("_Not computed_")

    lines += [
        "", "---", "",
        "## Interpretation Notes",
        "",
        "- **κ ≥ 0.61** (substantial) is the minimum acceptable threshold for clinical annotation tasks (Landis & Koch, 1977)",
        "- **ICC ≥ 0.75** (good) is recommended for clinical measurement tools",
        "- Wilcoxon signed-rank (two-sided, α=0.05) used for System A vs B comparison",
        "- Slice analysis is exploratory; interpret with caution for n_cases < 10",
    ]

    out_path.write_text('\n'.join(lines), encoding='utf-8')
    print(f"✅ Report saved: {out_path}")


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Blind Expert Evaluation Agreement Analysis")
    parser.add_argument('--form', default='human_evaluation/blind_packet_latest/evaluation_form.csv')
    parser.add_argument('--out', default=str(OUTPUT_DIR))
    parser.add_argument('--dry-run', action='store_true', help='Use mock data for testing')
    args = parser.parse_args()

    out_dir = Path(args.out)
    plots_dir = out_dir / 'plots'
    out_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)

    # Load data
    if args.dry_run:
        print("🔧 DRY-RUN mode — using synthetic mock data")
        df = make_mock_data()
    else:
        form_path = Path(args.form)
        if not form_path.exists():
            print(f"❌ Form not found: {form_path}")
            sys.exit(1)
        df = load_form(form_path)

    if df.empty:
        print("❌ No filled rows found. Ensure evaluator_id column is populated.")
        sys.exit(1)

    print(f"\n📊 Running agreement analysis...")

    # Compute
    print("  → Cohen's κ (pairwise)...")
    cohen_df = compute_cohen_kappa(df)

    print("  → Fleiss' κ (multi-rater)...")
    fleiss_df = compute_fleiss_kappa(df)

    print("  → ICC(2,1)...")
    icc_df = compute_icc(df)

    print("  → System A vs B comparison...")
    sys_df = compute_system_comparison(df)

    print("  → Slice analysis...")
    slice_df = compute_slice_analysis(df, sys_df)

    # Save CSVs
    if not cohen_df.empty:
        cohen_df.to_csv(out_dir / 'cohen_kappa_pairwise.csv', index=False)
        print(f"  ✅ cohen_kappa_pairwise.csv")

    if not fleiss_df.empty:
        fleiss_df.to_csv(out_dir / 'fleiss_kappa_overall.csv', index=False)
        print(f"  ✅ fleiss_kappa_overall.csv")

    if not icc_df.empty:
        icc_df.to_csv(out_dir / 'icc_results.csv', index=False)
        print(f"  ✅ icc_results.csv")

    if not sys_df.empty:
        sys_df.to_csv(out_dir / 'system_comparison.csv', index=False)
        print(f"  ✅ system_comparison.csv")

    if not slice_df.empty:
        slice_df.to_csv(out_dir / 'slice_analysis.csv', index=False)
        print(f"  ✅ slice_analysis.csv")

    # Plots
    print("  → Generating plots...")
    plot_inter_rater_heatmap(cohen_df, plots_dir)
    plot_system_comparison(df, plots_dir)

    # Report
    print("  → Writing report...")
    write_report(df, cohen_df, fleiss_df, icc_df, sys_df, slice_df,
                 out_dir / 'agreement_report.md')

    print(f"\n✅ All done → {out_dir}/")


if __name__ == '__main__':
    main()
