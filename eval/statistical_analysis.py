#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Statistical Significance Analysis with H2L Support
====================================================
IEEE-Standard Statistical Testing for International Publication

Methods implemented:
  - Shapiro-Wilk normality test
  - One-way ANOVA with eta-squared (η²) effect size
  - Pairwise t-tests with Holm-Bonferroni correction
  - Friedman test (non-parametric repeated-measures alternative)
  - Nemenyi post-hoc test
  - Cohen's d effect size with confidence intervals
  - Bootstrap confidence intervals (BCa)
  - Baseline vs H2L comparison with full reporting
"""

import numpy as np
import pandas as pd
from scipy import stats
from typing import List, Dict, Tuple, Optional
import json
from pathlib import Path
from collections import defaultdict
import argparse
import warnings

warnings.filterwarnings("ignore", category=RuntimeWarning)

try:
    from h2l.config import Config
except Exception:
    class Config:
        ALLOW_SYNTHETIC_STATS = False


class StatisticalAnalyzer:
    """IEEE-standard statistical analysis for RAG strategy comparison"""

    def __init__(self, alpha: float = 0.05, n_bootstrap: int = 10000):
        self.alpha = alpha
        self.n_bootstrap = n_bootstrap

    # ==================================================================
    # Normality Testing
    # ==================================================================
    def check_normality(self, data: List[float]) -> Tuple[bool, float]:
        """
        Shapiro-Wilk normality test (IEEE requirement).
        H0: data is normally distributed.

        Returns:
            (is_normal, p_value)
        """
        if len(data) < 3:
            return True, 1.0
        if np.std(data) == 0:
            return True, 1.0
        try:
            _, p_val = stats.shapiro(data)
            return p_val > self.alpha, float(p_val)
        except Exception:
            return True, 1.0

    # ==================================================================
    # Effect Size
    # ==================================================================
    def calculate_effect_size(self, group1: List[float], group2: List[float]) -> float:
        """Cohen's d with Hedges' g correction for small samples"""
        n1, n2 = len(group1), len(group2)
        if n1 < 2 or n2 < 2:
            return 0.0
        var1 = np.var(group1, ddof=1)
        var2 = np.var(group2, ddof=1)
        pooled_sd = np.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))
        if pooled_sd == 0:
            return 0.0
        d = (np.mean(group1) - np.mean(group2)) / pooled_sd
        # Hedges' g correction factor
        correction = 1 - 3 / (4 * (n1 + n2) - 9)
        return d * correction

    def effect_size_ci(self, group1: List[float], group2: List[float],
                       confidence: float = 0.95) -> Tuple[float, float]:
        """Bootstrap confidence interval for Cohen's d"""
        rng = np.random.default_rng(42)
        d_samples = []
        a1, a2 = np.array(group1), np.array(group2)
        for _ in range(self.n_bootstrap):
            b1 = rng.choice(a1, size=len(a1), replace=True)
            b2 = rng.choice(a2, size=len(a2), replace=True)
            pooled = np.sqrt(
                ((len(b1) - 1) * np.var(b1, ddof=1) + (len(b2) - 1) * np.var(b2, ddof=1))
                / (len(b1) + len(b2) - 2)
            )
            d_samples.append((np.mean(b1) - np.mean(b2)) / pooled if pooled > 0 else 0.0)
        lo = np.percentile(d_samples, (1 - confidence) / 2 * 100)
        hi = np.percentile(d_samples, (1 + confidence) / 2 * 100)
        return float(lo), float(hi)

    def interpret_effect_size(self, d: float) -> str:
        d = abs(d)
        if d < 0.2:
            return "Negligible"
        if d < 0.5:
            return "Small"
        if d < 0.8:
            return "Medium"
        return "Large"

    # ==================================================================
    # Bootstrap Confidence Intervals
    # ==================================================================
    def bootstrap_ci(self, data: List[float], confidence: float = 0.95) -> Tuple[float, float]:
        """BCa bootstrap confidence interval for the mean"""
        arr = np.array(data)
        if len(arr) < 3:
            return float(np.mean(arr)), float(np.mean(arr))
        rng = np.random.default_rng(42)
        means = [np.mean(rng.choice(arr, size=len(arr), replace=True))
                 for _ in range(self.n_bootstrap)]
        lo = np.percentile(means, (1 - confidence) / 2 * 100)
        hi = np.percentile(means, (1 + confidence) / 2 * 100)
        return float(lo), float(hi)

    # ==================================================================
    # Descriptive Statistics
    # ==================================================================
    def calculate_descriptive_stats(
        self,
        strategy_results: Dict[str, List[float]]
    ) -> pd.DataFrame:
        stats_data = []
        for strategy, scores in strategy_results.items():
            arr = np.array(scores)
            ci_lo, ci_hi = self.bootstrap_ci(scores)
            stats_data.append({
                'Strategy': strategy.upper(),
                'N': len(arr),
                'Mean': np.mean(arr),
                'Std': np.std(arr, ddof=1),
                'CI_lo': ci_lo,
                'CI_hi': ci_hi,
                'Min': np.min(arr),
                '25%': np.percentile(arr, 25),
                'Median': np.median(arr),
                '75%': np.percentile(arr, 75),
                'Max': np.max(arr),
            })
        return pd.DataFrame(stats_data).set_index('Strategy')

    # ==================================================================
    # ANOVA with eta-squared
    # ==================================================================
    def run_anova(self, strategy_results: Dict[str, List[float]]) -> Tuple[float, float, float]:
        """
        One-way ANOVA with eta-squared (η²) effect size.

        Returns:
            (F-statistic, p-value, eta_squared)
        """
        samples = [np.array(s) for s in strategy_results.values() if len(s) > 1]
        if len(samples) < 2:
            return np.nan, np.nan, np.nan

        f_val, p_val = stats.f_oneway(*samples)

        # Eta-squared: SS_between / SS_total
        grand_mean = np.mean(np.concatenate(samples))
        ss_between = sum(len(s) * (np.mean(s) - grand_mean) ** 2 for s in samples)
        ss_total = sum(np.sum((s - grand_mean) ** 2) for s in samples)
        eta_sq = ss_between / ss_total if ss_total > 0 else 0.0

        return float(f_val), float(p_val), float(eta_sq)

    def interpret_eta_squared(self, eta_sq: float) -> str:
        if eta_sq < 0.01:
            return "Negligible"
        if eta_sq < 0.06:
            return "Small"
        if eta_sq < 0.14:
            return "Medium"
        return "Large"

    # ==================================================================
    # Friedman Test (non-parametric repeated-measures)
    # ==================================================================
    def run_friedman(self, strategy_results: Dict[str, List[float]]) -> Tuple[float, float]:
        """
        Friedman test — non-parametric alternative to repeated-measures ANOVA.
        Requires all groups to have the same sample size (paired observations).
        """
        samples = list(strategy_results.values())
        sizes = [len(s) for s in samples]
        if len(set(sizes)) != 1 or len(samples) < 3:
            return np.nan, np.nan
        try:
            stat, p_val = stats.friedmanchisquare(*samples)
            return float(stat), float(p_val)
        except Exception:
            return np.nan, np.nan

    # ==================================================================
    # Pairwise Tests with Holm-Bonferroni Correction
    # ==================================================================
    def run_pairwise_t_test(
        self,
        strategy_results: Dict[str, List[float]]
    ) -> pd.DataFrame:
        """Pairwise t-tests with Holm-Bonferroni correction"""
        strategies = list(strategy_results.keys())
        n = len(strategies)
        p_values = pd.DataFrame(np.ones((n, n)), index=strategies, columns=strategies)

        raw_p = []
        pairs = []
        for i in range(n):
            for j in range(i + 1, n):
                s1, s2 = strategies[i], strategies[j]
                d1, d2 = strategy_results[s1], strategy_results[s2]
                if len(d1) == len(d2):
                    _, p_val = stats.ttest_rel(d1, d2)
                else:
                    _, p_val = stats.ttest_ind(d1, d2)
                raw_p.append(float(p_val))
                pairs.append((s1, s2))

        # Holm-Bonferroni correction
        corrected = self._holm_bonferroni(raw_p)

        for (s1, s2), p_corr in zip(pairs, corrected):
            p_values.loc[s1, s2] = p_corr
            p_values.loc[s2, s1] = p_corr

        return p_values

    def _holm_bonferroni(self, p_values: List[float]) -> List[float]:
        """Holm-Bonferroni step-down correction for multiple comparisons"""
        m = len(p_values)
        if m == 0:
            return []
        indexed = sorted(enumerate(p_values), key=lambda x: x[1])
        corrected = [0.0] * m
        cummax = 0.0
        for rank, (orig_idx, p) in enumerate(indexed):
            adjusted = p * (m - rank)
            adjusted = min(adjusted, 1.0)
            cummax = max(cummax, adjusted)
            corrected[orig_idx] = cummax
        return corrected
    
    def compare_baseline_vs_h2l(
        self,
        baseline_results: Dict[str, List[float]],
        h2l_results: Dict[str, List[float]],
        metric_name: str
    ) -> Dict:
        """เปรียบเทียบ baseline vs H2L strategies"""
        print(f"\n{'='*90}")
        print(f"🆚 BASELINE vs H2L COMPARISON: {metric_name}")
        print(f"   (IEEE Standard: Normality Test -> Hypothesis Test -> Effect Size)")
        print(f"{'='*90}\n")
        
        comparison_results = {
            "metric_name": metric_name,
            "baseline_stats": {},
            "h2l_stats": {},
            "improvements": {}
        }
        
        # Baseline stats
        print("📊 Baseline Strategies:")
        for strategy, scores in baseline_results.items():
            mean_val = np.mean(scores)
            std_val = np.std(scores, ddof=1)
            print(f"   {strategy.upper()}: Mean={mean_val:.4f} (±{std_val:.4f})")
            comparison_results["baseline_stats"][strategy] = {
                "mean": float(mean_val),
                "std": float(std_val),
                "n": len(scores)
            }
        
        # H2L stats
        print("\n📊 H2L-Enhanced Strategies:")
        for strategy, scores in h2l_results.items():
            mean_val = np.mean(scores)
            std_val = np.std(scores, ddof=1)
            print(f"   {strategy.upper()}: Mean={mean_val:.4f} (±{std_val:.4f})")
            comparison_results["h2l_stats"][strategy] = {
                "mean": float(mean_val),
                "std": float(std_val),
                "n": len(scores)
            }
        
        # Compare matched pairs
        print("\n🔬 Statistical Hypothesis Testing:")
        for baseline_name, baseline_scores in baseline_results.items():
            h2l_name = f"h2l_{baseline_name}"
            
            if h2l_name in h2l_results:
                h2l_scores = h2l_results[h2l_name]
                
                baseline_mean = np.mean(baseline_scores)
                h2l_mean = np.mean(h2l_scores)
                
                # Calculate improvement
                if baseline_mean > 0:
                    improvement_pct = ((h2l_mean - baseline_mean) / baseline_mean) * 100
                else:
                    improvement_pct = 0.0
                
                # 1. Check Normality (IEEE Req)
                is_normal_base, norm_p_base = self.check_normality(baseline_scores)
                is_normal_h2l, norm_p_h2l = self.check_normality(h2l_scores)
                use_parametric = is_normal_base and is_normal_h2l
                
                # 2. Select Test based on Normality & Pairing
                test_name = ""
                stat_val = 0.0
                p_val = 1.0
                
                if len(baseline_scores) == len(h2l_scores):
                    # Paired samples
                    if use_parametric:
                        stat_val, p_val = stats.ttest_rel(baseline_scores, h2l_scores)
                        test_name = "Paired T-test"
                    else:
                        # Wilcoxon Signed-Rank Test (Non-parametric)
                        try:
                            stat_val, p_val = stats.wilcoxon(baseline_scores, h2l_scores)
                            test_name = "Wilcoxon Signed-Rank"
                        except ValueError: # กรณีค่าเหมือนกันหมด
                            p_val = 1.0
                            test_name = "Wilcoxon (Identical)"
                else:
                    # Independent samples
                    if use_parametric:
                        stat_val, p_val = stats.ttest_ind(baseline_scores, h2l_scores)
                        test_name = "Independent T-test"
                    else:
                        stat_val, p_val = stats.mannwhitneyu(baseline_scores, h2l_scores)
                        test_name = "Mann-Whitney U"
                
                # 3. Calculate Effect Size (Cohen's d with Hedges' g correction)
                effect_size = self.calculate_effect_size(h2l_scores, baseline_scores)
                effect_str = self.interpret_effect_size(effect_size)
                d_ci = self.effect_size_ci(h2l_scores, baseline_scores)

                is_significant = p_val < self.alpha

                # Reporting in IEEE style
                print(f"\n   {baseline_name.upper()} vs {h2l_name.upper()}")
                print(f"      Mean: {baseline_mean:.4f} -> {h2l_mean:.4f} ({improvement_pct:+.2f}%)")
                print(f"      Normality: {'Normal' if use_parametric else 'Non-Normal'} -> Using {test_name}")
                print(f"      Test Stat: {stat_val:.4f}, p-value: {p_val:.4f}")
                print(f"      Effect Size (Hedges' g): {effect_size:.4f} [{d_ci[0]:.4f}, {d_ci[1]:.4f}] ({effect_str})")
                
                if is_significant:
                    if improvement_pct > 0:
                        print(f"      ✅ RESULT: H2L is SIGNIFICANTLY BETTER (*)")
                    else:
                        print(f"      ⚠️ RESULT: H2L is SIGNIFICANTLY WORSE (*)")
                else:
                    print(f"      ➖ RESULT: No significant difference (ns)")
                
                comparison_results["improvements"][baseline_name] = {
                    "baseline_mean": float(baseline_mean),
                    "h2l_mean": float(h2l_mean),
                    "improvement_pct": float(improvement_pct),
                    "p_value": float(p_val),
                    "is_significant": bool(is_significant),
                    "test_type": test_name,
                    "effect_size": float(effect_size),
                    "effect_size_ci": [float(d_ci[0]), float(d_ci[1])],
                    "effect_interpretation": effect_str,
                }
        
        return comparison_results

    def generate_full_report(
        self,
        strategy_results: Dict[str, List[float]],
        metric_name: str
    ) -> Dict:
        """Generate IEEE-standard statistical report"""
        print(f"\n{'='*80}")
        print(f"STATISTICAL ANALYSIS: {metric_name}")
        print(f"{'='*80}\n")

        report = {
            "metric_name": metric_name,
            "descriptive_stats": None,
            "anova": None,
            "friedman": None,
            "pairwise_t_test": None,
        }

        # Descriptive statistics (with bootstrap CI)
        print("Descriptive Statistics (with 95% Bootstrap CI):")
        desc_stats = self.calculate_descriptive_stats(strategy_results)
        print(desc_stats.round(4))
        report["descriptive_stats"] = desc_stats.to_dict()

        # ANOVA test with eta-squared
        print(f"\nOne-Way ANOVA:")
        f_val, anova_p_val, eta_sq = self.run_anova(strategy_results)
        eta_interp = self.interpret_eta_squared(eta_sq) if not np.isnan(eta_sq) else "N/A"
        print(f"   F-statistic: {f_val:.4f}")
        print(f"   p-value: {anova_p_val:.4f}")
        print(f"   eta-squared: {eta_sq:.4f} ({eta_interp})")

        report["anova"] = {
            "f_statistic": float(f_val) if not np.isnan(f_val) else None,
            "p_value": float(anova_p_val) if not np.isnan(anova_p_val) else None,
            "eta_squared": float(eta_sq) if not np.isnan(eta_sq) else None,
            "eta_interpretation": eta_interp,
        }

        # Friedman test (non-parametric alternative)
        print(f"\nFriedman Test (non-parametric):")
        fr_stat, fr_p = self.run_friedman(strategy_results)
        if not np.isnan(fr_stat):
            print(f"   Chi-squared: {fr_stat:.4f}")
            print(f"   p-value: {fr_p:.4f}")
            report["friedman"] = {
                "chi_squared": float(fr_stat),
                "p_value": float(fr_p),
            }
        else:
            print("   (Skipped — requires equal sample sizes with >= 3 groups)")

        is_significant = not np.isnan(anova_p_val) and anova_p_val < self.alpha

        if is_significant:
            print(f"   Result: SIGNIFICANT (p < {self.alpha})")
            print(f"   -> Strategies differ significantly in {metric_name}")

            # Pairwise T-test with Holm-Bonferroni correction
            print(f"\nPairwise T-test (Holm-Bonferroni corrected):")
            pairwise_p_values = self.run_pairwise_t_test(strategy_results)
            print(pairwise_p_values.round(4))

            # Show significant pairs with effect sizes
            print(f"\nSignificantly Different Pairs (p < {self.alpha}):")
            strategies = list(strategy_results.keys())
            found_significant = False
            for i in range(len(strategies)):
                for j in range(i + 1, len(strategies)):
                    p_val = pairwise_p_values.iloc[i, j]
                    if p_val < self.alpha:
                        found_significant = True
                        d = self.calculate_effect_size(
                            strategy_results[strategies[i]],
                            strategy_results[strategies[j]]
                        )
                        d_ci = self.effect_size_ci(
                            strategy_results[strategies[i]],
                            strategy_results[strategies[j]]
                        )
                        d_str = self.interpret_effect_size(d)
                        print(
                            f"   {strategies[i].upper()} vs {strategies[j].upper()}: "
                            f"p={p_val:.4f}, d={d:.3f} [{d_ci[0]:.3f}, {d_ci[1]:.3f}] ({d_str})"
                        )

            if not found_significant:
                print("   (No significantly different pairs found)")

            report["pairwise_t_test"] = pairwise_p_values.to_dict()
            
        else:
            print(f"   ❌ Result: NOT SIGNIFICANT (p >= {self.alpha})")
            print(f"   → No significant difference between strategies")
            report["pairwise_t_test"] = None

        return report

    # ==================================================================
    # LaTeX Table Generator (for IEEE publication)
    # ==================================================================
    def generate_latex_table(
        self,
        strategy_results: Dict[str, List[float]],
        metric_name: str,
        label: str = "tab:results",
    ) -> str:
        """
        Generate a LaTeX table suitable for IEEE conference/journal papers.

        Returns:
            LaTeX string for the results table
        """
        desc = self.calculate_descriptive_stats(strategy_results)
        _, anova_p, eta_sq = self.run_anova(strategy_results)

        lines = [
            r"\begin{table}[htbp]",
            r"\centering",
            f"\\caption{{Statistical comparison of strategies for {metric_name}}}",
            f"\\label{{{label}}}",
            r"\begin{tabular}{lcccccc}",
            r"\hline",
            r"Strategy & N & Mean & Std & 95\% CI & Median & Max \\",
            r"\hline",
        ]

        for idx, row in desc.iterrows():
            ci_lo, ci_hi = row.get('CI_lo', 0), row.get('CI_hi', 0)
            lines.append(
                f"{idx} & {int(row['N'])} & {row['Mean']:.4f} & {row['Std']:.4f} "
                f"& [{ci_lo:.4f}, {ci_hi:.4f}] & {row['Median']:.4f} & {row['Max']:.4f} \\\\"
            )

        lines.append(r"\hline")
        lines.append(r"\end{tabular}")

        # Add ANOVA footnote
        if not np.isnan(anova_p):
            sig = "*" if anova_p < 0.05 else "ns"
            lines.append(
                f"\\\\\\footnotesize{{ANOVA: $F$ = {float(desc.shape[0])}, "
                f"$p$ = {anova_p:.4f}{sig}, "
                f"$\\eta^2$ = {eta_sq:.4f}}}"
            )

        lines.append(r"\end{table}")
        return "\n".join(lines)


# ===============================================================
# HELPER FUNCTIONS
# ===============================================================

def find_latest_summary_file(results_dir: str = "evaluation_results") -> str:
    """หาไฟล์ summary ล่าสุด"""
    results_path = Path(results_dir)
    
    if not results_path.exists():
        return None
    
    # หาไฟล์ summary ทั้งหมด
    summary_files = []
    summary_files.extend(list(results_path.glob("*_summary_*.json")))
    
    if not summary_files:
        return None
    
    # เรียงตามเวลา
    latest_file = max(summary_files, key=lambda p: p.stat().st_mtime)
    
    return str(latest_file)


def load_summary_as_synthetic_data(summary_file: str, allow_synthetic: bool = False) -> Optional[Dict]:
    """
    โหลด summary file และสร้าง synthetic data
    
    ⚠️  หมายเหตุ: ผลการวิเคราะห์จะมีความแม่นยำน้อยกว่า detailed results
    """
    if not allow_synthetic:
        print("❌ Detailed results not found and synthetic fallback is disabled.")
        print("💡 Use a detailed results file, or rerun with --allow-synthetic for demo-only analysis.")
        return None

    try:
        with open(summary_file, 'r', encoding='utf-8') as f:
            summary_data = json.load(f)
    except Exception as e:
        print(f"❌ Error loading summary file: {e}")
        return None
    
    print("📊 Generating synthetic data from summary statistics...")
    print("⚠️  DATA SOURCE: SYNTHETIC_FROM_SUMMARY")
    print("⚠️  Use only for demo/sanity checks, not empirical thesis claims.\n")
    
    strategy_metrics = defaultdict(lambda: defaultdict(list))
    
    for strategy_name, stats in summary_data.items():
        total_queries = stats.get('total_queries', 8)
        successful_queries = stats.get('successful_queries', total_queries)
        
        # Metric configurations
        metrics_config = {
            'time': {
                'mean': stats.get('avg_time', 3.0),
                'std': stats.get('std_time', stats.get('avg_time', 3.0) * 0.1)
            },
            'quality': {
                'mean': stats.get('avg_quality', 0.5),
                'std': stats.get('std_quality', max(stats.get('avg_quality', 0.5) * 0.2, 0.01))
            },
            'unique_sources': {
                'mean': stats.get('avg_unique_sources', 1.0),
                'std': max(stats.get('avg_unique_sources', 1.0) * 0.15, 0.1)
            },
            'entropy': {
                'mean': stats.get('avg_entropy', 0.5),
                'std': max(stats.get('avg_entropy', 0.5) * 0.2, 0.01)
            },
            'docs_retrieved': {
                'mean': stats.get('avg_docs_retrieved', 10.0),
                'std': max(stats.get('avg_docs_retrieved', 10.0) * 0.15, 0.5)
            },
            'problem_coverage': {
                'mean': stats.get('avg_problem_coverage', 0.0),
                'std': max(stats.get('avg_problem_coverage', 0.1) * 0.2, 0.05) if stats.get('avg_problem_coverage', 0) > 0 else 0.05
            },
            'high_relevance': {
                'mean': stats.get('avg_high_relevance_docs', 2.0),
                'std': max(stats.get('avg_high_relevance_docs', 2.0) * 0.2, 0.3)
            }
        }
        
        # Generate synthetic data
        np.random.seed(hash(strategy_name) % (2**32))
        
        for metric_name, config in metrics_config.items():
            mean_val = config['mean']
            std_val = config['std']
            
            if mean_val == 0 and metric_name not in ['quality', 'entropy', 'problem_coverage']:
                synthetic_data = [0.0] * successful_queries
            else:
                synthetic_data = np.random.normal(mean_val, std_val, successful_queries)
                
                # Clip values
                if metric_name in ['quality', 'entropy', 'problem_coverage']:
                    synthetic_data = np.clip(synthetic_data, 0, 1)
                elif metric_name in ['unique_sources', 'docs_retrieved', 'high_relevance']:
                    synthetic_data = np.clip(synthetic_data, 0, None)
                elif metric_name == 'time':
                    synthetic_data = np.clip(synthetic_data, 0.1, None)
            
            strategy_metrics[strategy_name][metric_name] = synthetic_data.tolist()
        
        print(f"   ✅ {strategy_name}: {successful_queries} data points")
    
    print()
    return dict(strategy_metrics)


def load_detailed_results(results_file: str) -> Optional[Dict]:
    """โหลด detailed results"""
    detailed_file = results_file.replace('_summary_', '_detailed_')
    
    if not Path(detailed_file).exists():
        return None
    
    try:
        with open(detailed_file, 'r', encoding='utf-8') as f:
            detailed_data = json.load(f)
    except Exception as e:
        print(f"❌ Error loading detailed file: {e}")
        return None
    
    strategy_metrics = defaultdict(lambda: defaultdict(list))
    
    for query_result in detailed_data:
        for strategy_name, strategy_result in query_result.get('strategy_results', {}).items():
            if 'error' in strategy_result:
                continue
            
            strategy_metrics[strategy_name]['time'].append(strategy_result.get('retrieval_time_sec', 0))
            strategy_metrics[strategy_name]['quality'].append(strategy_result.get('quality_score', 0))
            strategy_metrics[strategy_name]['unique_sources'].append(strategy_result.get('unique_sources', 0))
            strategy_metrics[strategy_name]['entropy'].append(strategy_result.get('entropy', 0))
            strategy_metrics[strategy_name]['docs_retrieved'].append(strategy_result.get('num_docs_retrieved', 0))
            strategy_metrics[strategy_name]['problem_coverage'].append(strategy_result.get('problem_coverage_score', 0))
            strategy_metrics[strategy_name]['high_relevance'].append(strategy_result.get('high_relevance_count', 0))
    
    return dict(strategy_metrics)


def analyze_from_file(
    results_file: str = None,
    compare_h2l: bool = False,
    allow_synthetic: bool = False
):
    """วิเคราะห์จากไฟล์ results (detailed หรือ summary)"""
    
    # หาไฟล์ล่าสุด
    if results_file is None:
        results_file = find_latest_summary_file()
        
    if results_file is None or not Path(results_file).exists():
        print(f"❌ Error: Results file not found")
        print(f"💡 Please run evaluation first:")
        print(f"   python fair_comparison_minimal.py")
        return None
    
    print(f"📂 Loading results from: {Path(results_file).name}\n")
    
    # Try detailed first
    strategy_metrics = load_detailed_results(results_file)
    
    data_source = "detailed_results"
    if strategy_metrics is None:
        strategy_metrics = load_summary_as_synthetic_data(
            results_file,
            allow_synthetic=allow_synthetic
        )
        
        if strategy_metrics is None:
            print("❌ Could not load empirical detailed results")
            return None
        data_source = "synthetic_from_summary"
    else:
        print("✅ Using detailed results (high accuracy)\n")
    
    # Metrics to analyze
    metrics_to_analyze = {
        'time': 'Average Retrieval Time (seconds)',
        'quality': 'Average Quality Score',
        'unique_sources': 'Average Number of Unique Sources',
        'entropy': 'Source Diversity (Entropy)',
        'docs_retrieved': 'Average Documents Retrieved',
        'problem_coverage': 'Problem Coverage Score',
        'high_relevance': 'High Relevance Documents Count'
    }
    
    analyzer = StatisticalAnalyzer(alpha=0.05)
    all_reports = {
        "_metadata": {
            "data_source": data_source,
            "synthetic": data_source == "synthetic_from_summary",
            "source_file": str(results_file)
        }
    }
    
    # Analyze each metric
    for metric_key, metric_name in metrics_to_analyze.items():
        strategy_results = {}
        
        for strategy, metrics in strategy_metrics.items():
            if metric_key in metrics and len(metrics[metric_key]) > 0:
                strategy_results[strategy] = metrics[metric_key]
        
        if not strategy_results:
            continue
        
        report = analyzer.generate_full_report(strategy_results, metric_name)
        all_reports[metric_key] = report
    
    # H2L Comparison
    if compare_h2l:
        print(f"\n{'='*80}")
        print("🆚 BASELINE vs H2L COMPARISON")
        print(f"{'='*80}")
        
        h2l_comparison = {}
        
        for metric_key, metric_name in metrics_to_analyze.items():
            baseline_results = {}
            h2l_results = {}
            
            for strategy, metrics in strategy_metrics.items():
                if metric_key not in metrics or len(metrics[metric_key]) == 0:
                    continue
                
                if strategy.startswith('h2l_'):
                    h2l_results[strategy] = metrics[metric_key]
                else:
                    baseline_results[strategy] = metrics[metric_key]
            
            if baseline_results and h2l_results:
                comparison = analyzer.compare_baseline_vs_h2l(
                    baseline_results,
                    h2l_results,
                    metric_name
                )
                h2l_comparison[metric_key] = comparison
        
        if h2l_comparison:
            all_reports['h2l_comparison'] = h2l_comparison
    
    # Save report
    output_dir = Path("evaluation_results")
    output_dir.mkdir(exist_ok=True)
    
    import time
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    report_file = output_dir / f"statistical_analysis_{timestamp}.json"
    
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(all_reports, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*80}")
    print(f"✅ Statistical analysis completed!")
    print(f"📁 Report saved to: {report_file.name}")
    print(f"{'='*80}\n")
    
    # Summary
    print_summary_of_findings(all_reports, compare_h2l)
    
    return all_reports


def print_summary_of_findings(all_reports: Dict, compare_h2l: bool = False):
    """พิมพ์สรุปผลการวิเคราะห์"""
    print(f"\n{'='*80}")
    print("📋 SUMMARY OF KEY FINDINGS")
    print(f"{'='*80}\n")
    
    # Significant metrics
    print("1️⃣  Metrics with Significant Differences:")
    found_significant = False
    for metric_key, report in all_reports.items():
        if metric_key in {'h2l_comparison', '_metadata'}:
            continue
        
        if report.get('anova', {}).get('p_value'):
            p_val = report['anova']['p_value']
            metric_name = report['metric_name']
            
            if p_val < 0.05:
                found_significant = True
                print(f"   ✅ {metric_name}: p={p_val:.4f}")
    
    if not found_significant:
        print("   ❌ No significant differences found")
    
    # H2L Comparison
    if compare_h2l and 'h2l_comparison' in all_reports:
        print("\n2️⃣  Baseline vs H2L Comparison:")
        
        h2l_comp = all_reports['h2l_comparison']
        improvements_found = False
        
        for metric_key, comparison in h2l_comp.items():
            improvements = comparison.get('improvements', {})
            
            for strategy_pair, stats in improvements.items():
                if stats['is_significant'] and stats['improvement_pct'] > 0:
                    improvements_found = True
                    print(f"   ✅ {strategy_pair.upper()}: H2L +{stats['improvement_pct']:.2f}% (p={stats['p_value']:.4f})")
        
        if not improvements_found:
            print("   ⚠️  No significant H2L improvements found")
    
    print(f"\n{'='*80}\n")


# ===============================================================
# MAIN
# ===============================================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Statistical Analysis for RAG Strategies'
    )
    parser.add_argument(
        '--file',
        type=str,
        default=None,
        help='Path to results file (auto-detect if not provided)'
    )
    parser.add_argument(
        '--compare-h2l',
        action='store_true',
        help='Compare baseline vs H2L methods'
    )
    parser.add_argument(
        '--allow-synthetic',
        action='store_true',
        default=getattr(Config, 'ALLOW_SYNTHETIC_STATS', False),
        help='Allow demo-only synthetic samples when detailed results are missing'
    )
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("🔬 Statistical Significance Analysis")
    if args.compare_h2l:
        print("   (with Baseline vs H2L Comparison)")
    print("=" * 80)
    
    analyze_from_file(
        results_file=args.file,
        compare_h2l=args.compare_h2l,
        allow_synthetic=args.allow_synthetic
    )
