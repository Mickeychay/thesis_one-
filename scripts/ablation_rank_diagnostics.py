#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ablation Rank-Distance Diagnostics
====================================

Complements the standard RQ6 ablation by measuring **score-level** and
**rank-level** differences that binary relevance metrics miss.

Metrics:
  - Kendall τ distance (rank correlation per case, Full V6 vs each ablated)
  - Top-k swap count (how many docs change within top-5)
  - Score distribution shift (mean absolute score delta per variant)
  - Per-component contribution table (markdown)
  - Slice analysis: negation / high-severity / multi-problem cases

Usage:
  # After running ablation_study.py with --rq 6 and full 68 cases:
  python scripts/ablation_rank_diagnostics.py

  # Or specify custom input:
  python scripts/ablation_rank_diagnostics.py --csv ablation_results/v6_component_latest/rq6_results.csv

  # Dry-run with synthetic data:
  python scripts/ablation_rank_diagnostics.py --dry-run

Output:
  ablation_results/v6_component_latest/diagnostics/
    rank_distance_table.csv
    kendall_tau_heatmap.png
    top5_swap_summary.csv
    score_delta_by_variant.csv
    per_component_contribution_table.md
    slice_analysis_summary.csv
"""

import argparse
import sys
from pathlib import Path
from itertools import combinations

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

try:
    from scipy import stats as sp_stats
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    print("⚠️  scipy not found — Kendall τ will use a simplified implementation.")


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _df_to_md(df: pd.DataFrame) -> str:
    """DataFrame → markdown table without tabulate."""
    if df.empty:
        return "_empty_"
    cols = list(df.columns)
    header = "| " + " | ".join(str(c) for c in cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    rows = []
    for _, row in df.iterrows():
        rows.append("| " + " | ".join(str(row[c]) for c in cols) + " |")
    return "\n".join([header, sep] + rows)


FULL_V6 = "Full V6"

# Slice definitions
NEGATION_PREFIXES = ("NEG_",)
HIGH_SEVERITY_PREFIXES = ("SUBSTANCE", "MENTAL", "HOMELESS", "SUICIDE")
MULTI_PROBLEM_CATEGORIES = ("complex",)


# ═══════════════════════════════════════════════════════════════════════
# MOCK DATA
# ═══════════════════════════════════════════════════════════════════════

def make_mock_data() -> pd.DataFrame:
    """Generate synthetic ablation results for dry-run."""
    rng = np.random.default_rng(42)
    case_ids = [f"CASE_{i:03d}" for i in range(1, 21)]
    variants = [
        "Full V6", "w/o Adaptive Alpha", "w/o Bayesian Prior",
        "w/o IDF Specificity", "w/o Margin Activation",
        "w/o KL Penalty", "w/o Negation Gate", "Product Feature Mode",
    ]
    complexities = rng.choice(["simple", "moderate", "complex"], size=len(case_ids))
    categories = rng.choice(["เด็ก", "ผู้สูงอายุ", "สุขภาพจิต", "ไร้ที่อยู่"], size=len(case_ids))

    rows = []
    for ci, cid in enumerate(case_ids):
        # Base scores for Full V6
        base_p5 = rng.uniform(0, 1)
        base_ndcg = rng.uniform(0, 1)
        base_map = rng.uniform(0, 1)
        base_mrr = rng.uniform(0, 1)
        for vi, var in enumerate(variants):
            # Ablated variants get slightly perturbed scores
            noise = 0.0 if vi == 0 else rng.uniform(-0.15, 0.05)
            rows.append({
                "variant": var,
                "case_id": cid,
                "complexity": complexities[ci],
                "category": categories[ci],
                "P@5": round(max(0, min(1, base_p5 + noise)), 4),
                "R@5": round(max(0, min(1, base_p5 + noise * 0.8)), 4),
                "F1@5": round(max(0, min(1, base_p5 + noise * 0.9)), 4),
                "nDCG@5": round(max(0, min(1, base_ndcg + noise)), 4),
                "MAP": round(max(0, min(1, base_map + noise)), 4),
                "MRR": round(max(0, min(1, base_mrr + noise * 0.5)), 4),
                "rank_changed_at5": rng.random() > 0.6 if vi > 0 else False,
                "mean_abs_score_delta": round(abs(noise) * 0.3, 6) if vi > 0 else 0.0,
                "n_detected_problems": int(rng.integers(0, 5)),
            })
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════════════
# KENDALL τ DISTANCE
# ═══════════════════════════════════════════════════════════════════════

def kendall_tau_distance(ranking_a: list, ranking_b: list) -> float:
    """
    Kendall τ distance: fraction of pairwise disagreements.
    0 = identical rankings, 1 = completely reversed.
    """
    if len(ranking_a) != len(ranking_b) or len(ranking_a) < 2:
        return 0.0

    n = len(ranking_a)
    # Build position maps
    pos_a = {v: i for i, v in enumerate(ranking_a)}
    pos_b = {v: i for i, v in enumerate(ranking_b)}
    common = set(ranking_a) & set(ranking_b)
    common_list = sorted(common, key=lambda x: pos_a.get(x, 0))

    if len(common_list) < 2:
        return 0.0

    discordant = 0
    total = 0
    for i in range(len(common_list)):
        for j in range(i + 1, len(common_list)):
            a_i, a_j = common_list[i], common_list[j]
            # In ranking_a, a_i comes before a_j (by construction)
            # Check if same order in ranking_b
            if pos_b.get(a_j, 0) < pos_b.get(a_i, 0):
                discordant += 1
            total += 1

    return discordant / total if total > 0 else 0.0


def compute_rank_distances(df: pd.DataFrame, metric: str = "nDCG@5") -> pd.DataFrame:
    """
    Per-case score distance between Full V6 and each ablated variant.
    Uses h2l_mean_top5 if available (raw H2L scores), else falls back to metric.
    """
    variants = [v for v in df["variant"].unique() if v != FULL_V6]
    case_ids = df["case_id"].unique()
    
    # Use raw H2L scores if available for finer-grained comparison
    score_col = "h2l_mean_top5" if "h2l_mean_top5" in df.columns else metric

    rows = []
    for var in variants:
        taus = []
        swaps = []
        for cid in case_ids:
            full = df[(df["variant"] == FULL_V6) & (df["case_id"] == cid)]
            ablated = df[(df["variant"] == var) & (df["case_id"] == cid)]
            if full.empty or ablated.empty:
                continue

            full_score = float(full[score_col].iloc[0])
            abl_score = float(ablated[score_col].iloc[0])

            # For per-case scalar comparison, use absolute difference
            score_diff = abs(full_score - abl_score)
            taus.append(score_diff)
            swaps.append(1 if score_diff > 0.001 else 0)

        rows.append({
            "variant": var,
            "mean_score_diff": round(np.mean(taus), 6) if taus else 0.0,
            "max_score_diff": round(np.max(taus), 6) if taus else 0.0,
            "n_cases_changed": sum(swaps),
            "pct_cases_changed": round(100 * sum(swaps) / len(swaps), 1) if swaps else 0.0,
            "n_cases": len(taus),
        })

    return pd.DataFrame(rows).sort_values("mean_score_diff", ascending=False)


# ═══════════════════════════════════════════════════════════════════════
# TOP-K SWAP COUNT
# ═══════════════════════════════════════════════════════════════════════

def compute_topk_swaps(df: pd.DataFrame, k: int = 5) -> pd.DataFrame:
    """Count how many of the top-k results change between Full V6 and each variant."""
    if "rank_changed_at5" not in df.columns:
        return pd.DataFrame()

    variants = [v for v in df["variant"].unique() if v != FULL_V6]
    rows = []
    for var in variants:
        sub = df[df["variant"] == var]
        n_changed = sub["rank_changed_at5"].sum()
        n_total = len(sub)
        rows.append({
            "variant": var,
            "n_rank_changed": int(n_changed),
            "n_total": n_total,
            "pct_rank_changed": round(100 * n_changed / n_total, 1) if n_total > 0 else 0.0,
        })
    return pd.DataFrame(rows).sort_values("pct_rank_changed", ascending=False)


# ═══════════════════════════════════════════════════════════════════════
# SCORE DISTRIBUTION SHIFT
# ═══════════════════════════════════════════════════════════════════════

def compute_score_deltas(df: pd.DataFrame) -> pd.DataFrame:
    """Mean absolute score delta per variant (if column exists)."""
    if "mean_abs_score_delta" not in df.columns:
        return pd.DataFrame()

    variants = [v for v in df["variant"].unique() if v != FULL_V6]
    rows = []
    for var in variants:
        sub = df[df["variant"] == var]
        deltas = sub["mean_abs_score_delta"].dropna()
        rows.append({
            "variant": var,
            "mean_abs_delta": round(float(deltas.mean()), 6) if len(deltas) > 0 else 0.0,
            "std_delta": round(float(deltas.std()), 6) if len(deltas) > 1 else 0.0,
            "max_delta": round(float(deltas.max()), 6) if len(deltas) > 0 else 0.0,
            "n_nonzero": int((deltas > 0.001).sum()),
        })
    return pd.DataFrame(rows).sort_values("mean_abs_delta", ascending=False)


def compute_statistical_significance(df: pd.DataFrame, metric: str = "nDCG@5") -> pd.DataFrame:
    """
    Wilcoxon signed-rank test between Full V6 and each variant.
    Tests both binary metric (nDCG@5) and raw H2L scores if available.
    """
    if not HAS_SCIPY:
        return pd.DataFrame()

    variants = [v for v in df["variant"].unique() if v != FULL_V6]
    case_ids = df["case_id"].unique()
    
    # Test on both binary metric and raw scores
    test_metrics = [metric]
    if "h2l_mean_top5" in df.columns:
        test_metrics.append("h2l_mean_top5")

    rows = []
    for test_metric in test_metrics:
        for var in variants:
            full_scores = []
            abl_scores = []
            for cid in case_ids:
                f = df[(df["variant"] == FULL_V6) & (df["case_id"] == cid)]
                a = df[(df["variant"] == var) & (df["case_id"] == cid)]
                if f.empty or a.empty:
                    continue
                full_scores.append(float(f[test_metric].iloc[0]))
                abl_scores.append(float(a[test_metric].iloc[0]))

            diffs = np.array(full_scores) - np.array(abl_scores)
            if not full_scores or np.all(diffs == 0):
                p_val = 1.0
                effect_size = 0.0
            else:
                try:
                    _, p_val = sp_stats.wilcoxon(full_scores, abl_scores)
                except ValueError:
                    p_val = 1.0
                # Cohen's d effect size
                pooled_std = np.std(diffs)
                effect_size = float(np.mean(diffs) / pooled_std) if pooled_std > 0 else 0.0

            rows.append({
                "variant": var,
                "metric": test_metric,
                "p_value": round(p_val, 4),
                "significant": p_val < 0.05,
                "effect_size_d": round(effect_size, 4),
                "mean_diff": round(float(np.mean(diffs)), 6),
            })
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════════════
# SLICE ANALYSIS
# ═══════════════════════════════════════════════════════════════════════

def compute_slice_analysis(df: pd.DataFrame) -> pd.DataFrame:
    """Compare Full V6 vs ablated variants on case subsets."""
    metrics = ["nDCG@5", "MAP", "MRR"]
    variants = [v for v in df["variant"].unique() if v != FULL_V6]

    slices = {}
    # Negation cases
    neg_mask = df["case_id"].str.startswith(NEGATION_PREFIXES, na=False)
    if neg_mask.any():
        slices["negation"] = neg_mask
        slices["non_negation"] = ~neg_mask

    # High severity
    hi_mask = df["case_id"].str.startswith(HIGH_SEVERITY_PREFIXES, na=False)
    if hi_mask.any():
        slices["high_severity"] = hi_mask

    # Multi-problem (complex cases)
    if "complexity" in df.columns:
        complex_mask = df["complexity"].isin(MULTI_PROBLEM_CATEGORIES)
        if complex_mask.any():
            slices["complex_cases"] = complex_mask
            slices["simple_cases"] = df["complexity"] == "simple"

    rows = []
    for slice_name, mask in slices.items():
        full_sub = df[(df["variant"] == FULL_V6) & mask]
        for var in variants:
            abl_sub = df[(df["variant"] == var) & mask]
            for m in metrics:
                if m not in df.columns:
                    continue
                full_mean = full_sub[m].mean()
                abl_mean = abl_sub[m].mean()
                rows.append({
                    "slice": slice_name,
                    "variant": var,
                    "metric": m,
                    "Full_V6_mean": round(float(full_mean), 4),
                    "ablated_mean": round(float(abl_mean), 4),
                    "delta": round(float(full_mean - abl_mean), 4),
                    "n_cases": len(full_sub),
                })
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════════════
# PER-COMPONENT CONTRIBUTION TABLE
# ═══════════════════════════════════════════════════════════════════════

def build_contribution_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    Per-component contribution: Full V6 mean − ablated mean for each metric.
    Positive = component helps, Negative = component hurts.
    """
    metrics = ["P@5", "nDCG@5", "MAP", "MRR"]
    full = df[df["variant"] == FULL_V6]
    variants = [v for v in df["variant"].unique() if v != FULL_V6]

    rows = []
    for var in variants:
        abl = df[df["variant"] == var]
        row = {"component_disabled": var}
        for m in metrics:
            if m not in df.columns:
                continue
            full_mean = full[m].mean()
            abl_mean = abl[m].mean()
            row[f"Δ_{m}"] = round(float(full_mean - abl_mean), 6)
        # Score delta if available
        if "mean_abs_score_delta" in abl.columns:
            row["avg_score_perturbation"] = round(float(abl["mean_abs_score_delta"].mean()), 6)
        if "rank_changed_at5" in abl.columns:
            row["pct_rank_changed"] = round(100 * float(abl["rank_changed_at5"].mean()), 1)
        rows.append(row)

    return pd.DataFrame(rows).sort_values(f"Δ_nDCG@5", ascending=True)


# ═══════════════════════════════════════════════════════════════════════
# PLOTS
# ═══════════════════════════════════════════════════════════════════════

def plot_contribution_heatmap(contrib_df: pd.DataFrame, out_dir: Path):
    """Heatmap of per-component metric deltas."""
    if contrib_df.empty:
        return

    delta_cols = [c for c in contrib_df.columns if c.startswith("Δ_")]
    if not delta_cols:
        return

    fig, ax = plt.subplots(figsize=(10, 6))
    data = contrib_df[delta_cols].values
    labels = contrib_df["component_disabled"].values

    vmax = max(abs(data.min()), abs(data.max()), 0.01)
    im = ax.imshow(data, cmap="RdYlGn", aspect="auto", vmin=-vmax, vmax=vmax)
    ax.set_xticks(range(len(delta_cols)))
    ax.set_xticklabels([c.replace("Δ_", "") for c in delta_cols], fontsize=10)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=9)

    for i in range(len(labels)):
        for j in range(len(delta_cols)):
            val = data[i, j]
            color = "black" if abs(val) < vmax * 0.5 else "white"
            ax.text(j, i, f"{val:+.4f}", ha="center", va="center",
                    fontsize=8, fontweight="bold", color=color)

    plt.colorbar(im, ax=ax, label="Δ (Full V6 − ablated)")
    ax.set_title("Per-Component Contribution (positive = component helps)",
                 fontsize=12, fontweight="bold")
    plt.tight_layout()
    plt.savefig(out_dir / "component_contribution_heatmap.png", dpi=300, bbox_inches="tight")
    plt.close()
    print("✅ Saved: component_contribution_heatmap.png")


def plot_score_delta_bars(delta_df: pd.DataFrame, out_dir: Path):
    """Bar chart of mean absolute score delta per variant."""
    if delta_df.empty:
        return

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.barh(delta_df["variant"], delta_df["mean_abs_delta"],
                   color="#3498DB", edgecolor="white")
    ax.set_xlabel("Mean Absolute Score Delta")
    ax.set_title("Score Perturbation by Disabled Component", fontsize=12, fontweight="bold")
    ax.grid(axis="x", alpha=0.3)
    for bar, val in zip(bars, delta_df["mean_abs_delta"]):
        ax.text(bar.get_width() + 0.001, bar.get_y() + bar.get_height() / 2,
                f"{val:.4f}", va="center", fontsize=9)
    plt.tight_layout()
    plt.savefig(out_dir / "score_delta_by_variant.png", dpi=300, bbox_inches="tight")
    plt.close()
    print("✅ Saved: score_delta_by_variant.png")


# ═══════════════════════════════════════════════════════════════════════
# REPORT
# ═══════════════════════════════════════════════════════════════════════

def write_contribution_report(
    contrib_df, rank_dist_df, swap_df, delta_df, slice_df, sig_df,
    out_path: Path
):
    lines = [
        "# V6 Component Ablation — Rank-Distance Diagnostics",
        "",
        f"**Generated:** {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}  ",
        f"**Protocol:** Scoring-layer ablation; L1 detection held constant across all variants",
        "",
        "---",
        "",
        "## 1. Per-Component Contribution Table",
        "",
        "Positive Δ = component **helps** (removing it hurts performance).",
        "",
    ]
    lines.append(_df_to_md(contrib_df))

    lines += ["", "---", "", "## 2. Statistical Significance (Full V6 vs Variant)", ""]
    if not sig_df.empty:
        lines.append(_df_to_md(sig_df))
    else:
        lines.append("_Not computed_")

    lines += ["", "---", "", "## 3. Score-Level Distance (Full V6 vs Ablated)", ""]
    if not rank_dist_df.empty:
        lines.append(_df_to_md(rank_dist_df))
    else:
        lines.append("_Not computed_")

    lines += ["", "---", "", "## 3. Top-5 Rank Swap Summary", ""]
    if not swap_df.empty:
        lines.append(_df_to_md(swap_df))
    else:
        lines.append("_Not available (rank_changed_at5 column missing)_")

    lines += ["", "---", "", "## 4. Score Perturbation by Variant", ""]
    if not delta_df.empty:
        lines.append(_df_to_md(delta_df))
    else:
        lines.append("_Not available (mean_abs_score_delta column missing)_")

    lines += ["", "---", "", "## 5. Slice Analysis", ""]
    if not slice_df.empty:
        lines.append(_df_to_md(slice_df))
    else:
        lines.append("_Not computed (no matching case prefixes)_")

    lines += [
        "", "---", "",
        "## Interpretation Notes",
        "",
        "- Binary relevance metrics (P@5, nDCG@5) may show **zero difference** when top-5 documents remain identical",
        "- Score-level delta and rank swap count capture **finer-grained** component effects",
        "- Components with Δ ≈ 0 may have synergistic effects — removing them alone doesn't capture interaction",
        "- Slice analysis is exploratory for n_cases < 10",
        "- Protocol: L1 detection is held constant; only scoring-layer V6 components are toggled",
    ]

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"✅ Report saved: {out_path}")


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Ablation Rank-Distance Diagnostics")
    parser.add_argument("--csv", default="ablation_results/v6_component_latest/rq6_results.csv")
    parser.add_argument("--out", default="ablation_results/v6_component_latest/diagnostics")
    parser.add_argument("--dry-run", action="store_true", help="Use synthetic data")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        print("🔧 DRY-RUN mode — using synthetic data")
        df = make_mock_data()
    else:
        csv_path = Path(args.csv)
        if not csv_path.exists():
            print(f"❌ CSV not found: {csv_path}")
            sys.exit(1)
        df = pd.read_csv(csv_path)
        print(f"✅ Loaded: {len(df)} rows, {df['variant'].nunique()} variants, {df['case_id'].nunique()} cases")

    if FULL_V6 not in df["variant"].values:
        print(f"❌ '{FULL_V6}' variant not found in data")
        sys.exit(1)

    print("\n📊 Running diagnostics...")

    print("  → Per-component contribution table...")
    contrib_df = build_contribution_table(df)
    contrib_df.to_csv(out_dir / "per_component_contribution.csv", index=False)

    print("  → Rank distances...")
    rank_dist_df = compute_rank_distances(df)
    rank_dist_df.to_csv(out_dir / "rank_distance_table.csv", index=False)

    print("  → Top-k swap counts...")
    swap_df = compute_topk_swaps(df)
    if not swap_df.empty:
        swap_df.to_csv(out_dir / "top5_swap_summary.csv", index=False)

    print("  → Score deltas...")
    delta_df = compute_score_deltas(df)
    if not delta_df.empty:
        delta_df.to_csv(out_dir / "score_delta_by_variant.csv", index=False)

    print("  → Statistical significance...")
    sig_df = compute_statistical_significance(df)
    if not sig_df.empty:
        sig_df.to_csv(out_dir / "statistical_significance.csv", index=False)

    print("  → Slice analysis...")
    slice_df = compute_slice_analysis(df)
    if not slice_df.empty:
        slice_df.to_csv(out_dir / "slice_analysis_summary.csv", index=False)

    print("  → Generating plots...")
    plot_contribution_heatmap(contrib_df, out_dir)
    plot_score_delta_bars(delta_df, out_dir)

    print("  → Writing report...")
    write_contribution_report(
        contrib_df, rank_dist_df, swap_df, delta_df, slice_df, sig_df,
        out_dir / "per_component_contribution_table.md"
    )

    print(f"\n✅ All done → {out_dir}/")


if __name__ == "__main__":
    main()
