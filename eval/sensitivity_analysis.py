#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
H2L V6 Parameter Sensitivity Analysis
=======================================

Systematically varies each key parameter ±30-50% from its default value
and measures impact on scoring metrics using ground truth cases.

Purpose:
    Demonstrate that H2L scoring is ROBUST to parameter changes —
    i.e., expert-elicited parameters produce stable results even
    when perturbed. This is required for thesis validity when
    parameters are set from domain knowledge rather than data fitting.

Methodology:
    - One-at-a-Time (OAT) sensitivity analysis
    - Each parameter varied independently while others held at default
    - Metrics: mean boost, mean Φ_i, mean α_eff per ground truth case
    - Visualizations: Heatmap + Tornado plot

Output:
    sensitivity_results/
    ├── sensitivity_heatmap.png       — Parameter × Metric Δ%
    ├── sensitivity_tornado.png       — Impact ranking
    ├── sensitivity_raw.csv           — Raw data
    └── sensitivity_report.md         — Summary

Usage:
    python sensitivity_analysis.py                   # Full (all cases)
    python sensitivity_analysis.py --max-cases 10    # Quick test
"""

import json
import hashlib
import logging
import argparse
import math
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

EXPECTED_TOTAL_CASES = 220
EXPECTED_TRAIN_CASES = 125
EXPECTED_TEST_CASES = 95
EXPECTED_EMPTY_TRAIN_CASES = 10
EXPECTED_SCORED_TRAIN_CASES = 115
ANALYSIS_SCOPE = "score_function_oat"
SIMULATED_RERANK_SCORE = 0.5
SIMULATED_DETECTION_CONFIDENCE = 0.8


def file_sha256(path: Path) -> str:
    """Return a content hash for a provenance-tracked input."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")

# ============================================================================
# PARAMETER DEFINITIONS
# ============================================================================

@dataclass
class ParameterSweep:
    """Defines one parameter to sweep"""
    name: str           # H2LConfigV3 attribute name
    label: str          # Human-readable label
    default: float      # Default value
    values: List[float] # Values to test
    description: str    # What this parameter controls


# 8 key parameters identified from H2LConfigV3
PARAMETER_SWEEPS = [
    ParameterSweep(
        name="CALIBRATION_T_BASE",
        label="T_base (Calibration)",
        default=0.5,
        values=[0.2, 0.35, 0.5, 0.65, 0.8, 1.0],
        description="Base temperature for severity-weighted confidence calibration"
    ),
    ParameterSweep(
        name="CALIBRATION_T_RANGE",
        label="T_range (Calibration)",
        default=1.5,
        values=[0.5, 1.0, 1.5, 2.0, 2.5],
        description="Temperature range for severity discrimination"
    ),
    ParameterSweep(
        name="NEG_LAMBDA",
        label="λ_neg (Polarity Gate)",
        default=0.6,
        values=[0.3, 0.45, 0.6, 0.8, 1.0],
        description="Negation dampening strength in sentence polarity gating"
    ),
    ParameterSweep(
        name="KL_KAPPA",
        label="κ (KL Penalty)",
        default=0.15,
        values=[0.0, 0.05, 0.10, 0.15, 0.25, 0.30],
        description="KL-divergence concentration penalty strength"
    ),
    ParameterSweep(
        name="MARGIN_M",
        label="m (Margin)",
        default=0.3,
        values=[0.1, 0.2, 0.3, 0.4, 0.5],
        description="Decision boundary margin for saturating activation"
    ),
    ParameterSweep(
        name="DIRICHLET_MU",
        label="μ (Dirichlet)",
        default=2.0,
        values=[0.5, 1.0, 2.0, 3.0, 4.0],
        description="Dirichlet smoothing strength for problem priors"
    ),
    ParameterSweep(
        name="ALPHA",
        label="α₀ (Base Weight)",
        default=1.0,
        values=[0.25, 0.5, 0.75, 1.0, 1.5, 2.0],
        description="Base problem influence weight"
    ),
    ParameterSweep(
        name="L1_WEIGHT_BETA",
        label="β (L1/L2 Balance)",
        default=0.3,
        values=[0.0, 0.1, 0.3, 0.5, 0.7, 1.0],
        description="L1 vs L2 detection weight balance"
    ),
]


# ============================================================================
# SENSITIVITY ANALYSIS ENGINE
# ============================================================================

class SensitivityAnalyzer:
    """
    Runs OAT sensitivity analysis on H2L scoring parameters.
    
    Uses calculate_final_score_probabilistic directly —
    no model loading or retrieval needed.
    """

    def __init__(self, ground_truth_path: str = "ground_truth_train.json",
                 max_cases: int = None):
        self.ground_truth_path = Path(ground_truth_path).resolve()
        self.max_cases = max_cases
        self.ground_truth_metadata: Dict[str, Any] = {}
        self.all_case_count = 0
        self.train_case_count = 0
        self.test_case_count = 0
        self.skipped_case_ids: List[str] = []
        self.scorable_cases: List[Dict] = []
        self.cases = self._load_cases()

    def _load_cases(self) -> List[Dict]:
        """Load and validate the signed unified ground-truth split."""
        with open(self.ground_truth_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if not isinstance(data, dict) or not isinstance(data.get('cases'), list):
            raise ValueError("Ground truth must be an object containing a cases list")

        all_cases = data['cases']
        self.ground_truth_metadata = data.get('metadata', {})
        self.all_case_count = len(all_cases)
        train_cases = [case for case in all_cases if case.get('split') == 'train']
        test_cases = [case for case in all_cases if case.get('split') == 'test']
        self.train_case_count = len(train_cases)
        self.test_case_count = len(test_cases)

        metadata_counts = {
            'total_cases': EXPECTED_TOTAL_CASES,
            'train_cases': EXPECTED_TRAIN_CASES,
            'test_cases': EXPECTED_TEST_CASES,
        }
        actual_counts = {
            'total_cases': self.all_case_count,
            'train_cases': self.train_case_count,
            'test_cases': self.test_case_count,
        }
        for key, expected in metadata_counts.items():
            declared = self.ground_truth_metadata.get(key)
            if declared != expected:
                raise ValueError(
                    f"Ground-truth metadata {key} mismatch: expected {expected}, got {declared!r}"
                )
            if actual_counts[key] != expected:
                raise ValueError(
                    f"Ground-truth {key} mismatch: expected {expected}, got {actual_counts[key]}"
                )

        train_ids = [case.get('case_id') for case in train_cases]
        if any(not isinstance(case_id, str) or not case_id.strip() for case_id in train_ids):
            raise ValueError("Every train case must have a non-empty string case_id")
        if len(train_ids) != len(set(train_ids)):
            duplicates = sorted({case_id for case_id in train_ids if train_ids.count(case_id) > 1})
            raise ValueError(f"Duplicate train case IDs: {duplicates}")

        if self.max_cases is not None:
            if self.max_cases <= 0:
                raise ValueError("max_cases must be a positive integer")
            train_cases = train_cases[:self.max_cases]

        self.skipped_case_ids = []
        self.scorable_cases = []
        for case in train_cases:
            case_id = case['case_id']
            query = case.get('case_description')
            if not isinstance(query, str) or not query.strip():
                raise ValueError(f"Train case {case_id} has an empty case_description")
            if not self._build_problems_from_case(case):
                self.skipped_case_ids.append(case_id)
            else:
                self.scorable_cases.append(case)

        if self.max_cases is None:
            if len(self.skipped_case_ids) != EXPECTED_EMPTY_TRAIN_CASES:
                raise ValueError(
                    "Empty train problem-list count mismatch: "
                    f"expected {EXPECTED_EMPTY_TRAIN_CASES}, got {len(self.skipped_case_ids)}"
                )
            if len(self.scorable_cases) != EXPECTED_SCORED_TRAIN_CASES:
                raise ValueError(
                    "Scorable train case count mismatch: "
                    f"expected {EXPECTED_SCORED_TRAIN_CASES}, got {len(self.scorable_cases)}"
                )

        logger.info(
            "Loaded %d train cases: %d scorable, %d empty problem lists",
            len(train_cases),
            len(self.scorable_cases),
            len(self.skipped_case_ids),
        )
        return train_cases

    def _build_problems_from_case(self, case: Dict) -> List[Dict]:
        """Extract problem list from a ground truth case"""
        expected = case.get('expected_diagnosis', {})
        problem_list = expected.get('problem_list', [])
        keywords_map = case.get('relevant_keywords', {})

        problems = []
        for p in problem_list:
            code = p.get('code', 'unknown')
            problems.append({
                'code': code,
                'name': p.get('category', ''),
                'severity': p.get('severity', 3),
                'confidence': SIMULATED_DETECTION_CONFIDENCE,
                'keywords': keywords_map.get(code, []),
            })
        return problems

    def run_single_config(self, config) -> Dict[str, Any]:
        """
        Run scoring on all cases with a given config.
        Returns mean metrics across all cases.
        """
        from h2l.core import calculate_final_score_probabilistic

        boosts = []
        phis = []
        alphas = []
        scores = []

        scored_case_ids = []
        for case in self.scorable_cases:
            case_id = case['case_id']
            query = case.get('case_description', '')
            problems = self._build_problems_from_case(case)

            try:
                final_score, breakdown = calculate_final_score_probabilistic(
                    rerank_score=SIMULATED_RERANK_SCORE,
                    problems=problems,
                    doc_text=query,  # Use case text as "retrieved doc"
                    query_text=query,
                    config=config,
                )
            except Exception as e:
                raise RuntimeError(f"Scoring failed for case {case_id}: {e}") from e

            if not isinstance(breakdown, dict):
                raise RuntimeError(f"Scoring returned a non-dict breakdown for case {case_id}")
            factors = breakdown.get('factors')
            if not isinstance(factors, list) or not factors:
                raise RuntimeError(f"Scoring returned no factors for case {case_id}")

            try:
                boost = float(breakdown['boost'])
                alpha_eff = float(breakdown['α_eff'])
                score = float(final_score)
                phi_values = [float(factor['Φ_i']) for factor in factors]
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(f"Scoring returned invalid metrics for case {case_id}: {exc}") from exc

            metric_values = [boost, alpha_eff, score, *phi_values]
            if not all(math.isfinite(value) for value in metric_values):
                raise RuntimeError(f"Scoring returned non-finite metrics for case {case_id}")

            boosts.append(boost)
            alphas.append(alpha_eff)
            scores.append(score)
            phis.append(float(np.mean(phi_values)))
            scored_case_ids.append(case_id)

        expected_case_ids = [case['case_id'] for case in self.scorable_cases]
        if scored_case_ids != expected_case_ids:
            raise RuntimeError("Scored case IDs differ from the validated scorable train case set")
        if not scores:
            raise RuntimeError("No train cases were scored")

        return {
            'mean_boost': float(np.mean(boosts)),
            'mean_Φ_i': float(np.mean(phis)),
            'mean_α_eff': float(np.mean(alphas)),
            'mean_score': float(np.mean(scores)),
            'std_score': float(np.std(scores)),
            'n_scored': len(scored_case_ids),
            'scored_case_ids': scored_case_ids,
        }

    def run_sensitivity(self) -> Tuple[Dict, Dict]:
        """
        Run full OAT sensitivity analysis.
        
        Returns:
            results: {param_name: {value: metrics_dict}}
            baseline: default metrics
        """
        from h2l.core import H2LConfigV3

        parameter_names = [sweep.name for sweep in PARAMETER_SWEEPS]
        if len(parameter_names) != 8 or len(set(parameter_names)) != 8:
            raise ValueError("Sensitivity analysis must define exactly eight unique parameters")
        for sweep in PARAMETER_SWEEPS:
            if sweep.values.count(sweep.default) != 1:
                raise ValueError(
                    f"Parameter {sweep.name} must include its default exactly once"
                )

        # 1. Run baseline (all defaults)
        logger.info("\nRunning baseline (default parameters)...")
        default_config = H2LConfigV3()
        baseline = self.run_single_config(default_config)
        expected_case_ids = baseline['scored_case_ids']
        logger.info(f"   Baseline: boost={baseline['mean_boost']:.4f}, "
                    f"score={baseline['mean_score']:.4f}")

        # 2. Sweep each parameter
        results = {}
        for sweep in PARAMETER_SWEEPS:
            logger.info(f"\nSweeping {sweep.label} ({sweep.name})")
            param_results = {}

            for val in sweep.values:
                # Create config with this one parameter changed
                config = H2LConfigV3()
                setattr(config, sweep.name, val)
                # Re-run __post_init__ to fix weights if needed
                config.__post_init__()

                metrics = self.run_single_config(config)
                if metrics['scored_case_ids'] != expected_case_ids:
                    raise RuntimeError(
                        f"Case-set invariant failed for {sweep.name}={val}"
                    )
                param_results[val] = metrics

                is_default = "(default)" if val == sweep.default else ""
                logger.info(f"   {sweep.name}={val:6.2f} → "
                            f"boost={metrics['mean_boost']:.4f}, "
                            f"score={metrics['mean_score']:.4f} {is_default}")

            results[sweep.name] = param_results

        return results, baseline


# ============================================================================
# VISUALIZATION
# ============================================================================

def generate_visualizations(results: Dict, baseline: Dict,
                            output_dir: Path):
    """Generate heatmap and tornado plot"""
    import matplotlib.pyplot as plt
    import matplotlib
    matplotlib.use('Agg')

    output_dir.mkdir(parents=True, exist_ok=True)
    metric_name = 'mean_score'

    # ── Build delta matrix for heatmap ──
    param_labels = []
    delta_rows = []

    for sweep in PARAMETER_SWEEPS:
        if sweep.name not in results:
            continue
        param_data = results[sweep.name]
        deltas = []
        for val in sweep.values:
            if val in param_data:
                base_val = baseline[metric_name]
                new_val = param_data[val][metric_name]
                if base_val > 0:
                    delta_pct = ((new_val - base_val) / base_val) * 100
                else:
                    delta_pct = 0
                deltas.append(delta_pct)
        if deltas:
            param_labels.append(sweep.label)
            delta_rows.append(deltas)

    # ── Heatmap ──
    if delta_rows:
        fig, ax = plt.subplots(figsize=(12, 7))

        # Pad rows to same length
        max_cols = max(len(row) for row in delta_rows)
        padded = []
        col_labels_list = []
        for i, sweep in enumerate(PARAMETER_SWEEPS):
            if sweep.name in results:
                vals = sweep.values
                col_labels_list.append([f"{v}" for v in vals])
                row = delta_rows[len(padded)]
                padded.append(row + [np.nan] * (max_cols - len(row)))

        matrix = np.array(padded, dtype=float)

        # Use diverging colormap (red = worse, green = better)
        vmax = max(abs(np.nanmin(matrix)), abs(np.nanmax(matrix)), 5)
        im = ax.imshow(matrix, cmap='RdYlGn', aspect='auto',
                       vmin=-vmax, vmax=vmax)

        ax.set_yticks(range(len(param_labels)))
        ax.set_yticklabels(param_labels, fontsize=11)

        # Use the longest col_labels for x-axis
        ax.set_xticks(range(max_cols))
        ax.set_xticklabels([f"val_{j+1}" for j in range(max_cols)], fontsize=9)

        # Annotate cells
        for i in range(matrix.shape[0]):
            for j in range(matrix.shape[1]):
                if not np.isnan(matrix[i, j]):
                    val = matrix[i, j]
                    # Show actual parameter value + delta
                    sweep_idx = i
                    if sweep_idx < len(PARAMETER_SWEEPS) and j < len(PARAMETER_SWEEPS[sweep_idx].values):
                        param_val = PARAMETER_SWEEPS[sweep_idx].values[j]
                        is_default = PARAMETER_SWEEPS[sweep_idx].default == param_val
                        text = f"{param_val}\n({val:+.1f}%)"
                        if is_default:
                            text += "\n★"
                    else:
                        text = f"{val:+.1f}%"

                    color = 'black' if abs(val) < vmax * 0.6 else 'white'
                    ax.text(j, i, text, ha='center', va='center',
                            fontsize=8, color=color, fontweight='bold' if is_default else 'normal')

        plt.colorbar(im, ax=ax, label='Δ% from default', shrink=0.8)
        ax.set_title('H2L V6 Score-Function Parameter Sensitivity\n(Δ% change in mean score from default)',
                     fontsize=14, fontweight='bold')
        ax.set_xlabel('Parameter Values (★ = default)', fontsize=11)
        plt.tight_layout()
        plt.savefig(output_dir / 'sensitivity_heatmap.png', dpi=300, bbox_inches='tight')
        plt.close()
        logger.info(f"Heatmap saved: {output_dir / 'sensitivity_heatmap.png'}")

    # ── Tornado Plot ──
    # Shows max absolute Δ% for each parameter
    impacts = []
    for sweep in PARAMETER_SWEEPS:
        if sweep.name not in results:
            continue
        param_data = results[sweep.name]
        base_val = baseline[metric_name]
        deltas = []
        for val, metrics in param_data.items():
            if base_val > 0:
                delta_pct = ((metrics[metric_name] - base_val) / base_val) * 100
                deltas.append(delta_pct)
        if deltas:
            max_delta = max(deltas, key=abs)
            min_delta = min(deltas)
            max_delta_pos = max(deltas)
            impacts.append({
                'label': sweep.label,
                'min_delta': min_delta,
                'max_delta': max_delta_pos,
                'max_abs': max(abs(min_delta), abs(max_delta_pos)),
            })

    if impacts:
        # Sort by max absolute impact
        impacts.sort(key=lambda x: x['max_abs'])

        fig, ax = plt.subplots(figsize=(10, 7))
        y_pos = range(len(impacts))
        labels = [imp['label'] for imp in impacts]
        min_vals = [imp['min_delta'] for imp in impacts]
        max_vals = [imp['max_delta'] for imp in impacts]

        # Draw bars from min to max delta
        for i, imp in enumerate(impacts):
            color_neg = '#E74C3C' if imp['min_delta'] < 0 else '#2ECC71'
            color_pos = '#2ECC71' if imp['max_delta'] > 0 else '#E74C3C'

            # Negative side
            if imp['min_delta'] < 0:
                ax.barh(i, imp['min_delta'], color=color_neg, alpha=0.8,
                        height=0.6, edgecolor='white')
            # Positive side
            if imp['max_delta'] > 0:
                ax.barh(i, imp['max_delta'], color=color_pos, alpha=0.8,
                        height=0.6, edgecolor='white')

            # Annotate
            ax.text(imp['min_delta'] - 0.5, i, f"{imp['min_delta']:+.1f}%",
                    va='center', ha='right', fontsize=9, color='#E74C3C')
            ax.text(imp['max_delta'] + 0.5, i, f"{imp['max_delta']:+.1f}%",
                    va='center', ha='left', fontsize=9, color='#2ECC71')

        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels, fontsize=11)
        ax.axvline(0, color='black', linewidth=0.8)
        ax.set_xlabel('Δ% from Default Score', fontsize=12)
        ax.set_title('Score-Function Parameter Impact\n(Maximum mean-score change in the OAT sweep)',
                     fontsize=14, fontweight='bold')
        ax.grid(axis='x', alpha=0.3)

        # Add robustness indicator
        max_impact = max(imp['max_abs'] for imp in impacts)
        if max_impact < 5:
            robustness = "LOW SCORE-FUNCTION SENSITIVITY (< 5%)"
            color = '#2ECC71'
        elif max_impact < 10:
            robustness = "MODERATE SCORE-FUNCTION SENSITIVITY (5-10%)"
            color = '#F39C12'
        else:
            robustness = "HIGH SCORE-FUNCTION SENSITIVITY (> 10%)"
            color = '#E74C3C'

        ax.text(0.02, 0.98, robustness, transform=ax.transAxes,
                fontsize=12, fontweight='bold', color=color,
                verticalalignment='top',
                bbox=dict(boxstyle='round,pad=0.5', facecolor='white',
                          edgecolor=color, alpha=0.9))

        plt.tight_layout()
        plt.savefig(output_dir / 'sensitivity_tornado.png', dpi=300, bbox_inches='tight')
        plt.close()
        logger.info(f"Tornado plot saved: {output_dir / 'sensitivity_tornado.png'}")


def generate_csv(results: Dict, baseline: Dict, output_dir: Path,
                 expected_n_scored: int):
    """Export raw data to CSV"""
    import csv

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / 'sensitivity_raw.csv'

    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'parameter', 'label', 'value', 'is_default',
            'mean_boost', 'mean_phi_i', 'mean_alpha_eff',
            'mean_score', 'std_score',
            'delta_score_pct', 'n_scored'
        ])

        for sweep in PARAMETER_SWEEPS:
            if sweep.name not in results:
                raise ValueError(f"Missing sensitivity results for {sweep.name}")
            default_rows = sum(value == sweep.default for value in results[sweep.name])
            if default_rows != 1:
                raise ValueError(f"Parameter {sweep.name} must have exactly one default row")
            for val, metrics in results[sweep.name].items():
                n_scored = int(metrics.get('n_scored', -1))
                if n_scored != expected_n_scored:
                    raise ValueError(
                        f"{sweep.name}={val} scored {n_scored} cases; "
                        f"expected {expected_n_scored}"
                    )
                base_score = baseline['mean_score']
                delta_pct = ((metrics['mean_score'] - base_score) / base_score * 100
                             if base_score > 0 else 0)
                writer.writerow([
                    sweep.name, sweep.label, val,
                    val == sweep.default,
                    f"{metrics['mean_boost']:.6f}",
                    f"{metrics['mean_Φ_i']:.6f}",
                    f"{metrics['mean_α_eff']:.6f}",
                    f"{metrics['mean_score']:.6f}",
                    f"{metrics['std_score']:.6f}",
                    f"{delta_pct:.2f}",
                    n_scored,
                ])

    logger.info(f"CSV saved: {csv_path}")


def generate_report(results: Dict, baseline: Dict, selected_cases: int,
                    scored_cases: int, skipped_cases: int, output_dir: Path):
    """Generate markdown summary report"""
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / 'sensitivity_report.md'

    lines = [
        "# H2L V6 Score-Function Parameter Sensitivity Report",
        f"\n**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"\n**Analysis scope**: `{ANALYSIS_SCOPE}`",
        "**Retrieval executed**: `false`",
        f"\n**Baseline Score**: {baseline['mean_score']:.6f}",
        f"**Baseline Boost**: {baseline['mean_boost']:.4f}",
        f"**Train cases selected**: {selected_cases}",
        f"**Cases scored**: {scored_cases}",
        f"**Empty problem lists skipped by design**: {skipped_cases}",
        "",
        "### ขอบเขตและชุดข้อมูล (Analysis Scope and Dataset)",
        "เลือกเคสชุดฝึก **" + str(selected_cases) + "** เคสจาก unified ground truth; "
        "คำนวณได้จริง **" + str(scored_cases) + "** เคส และข้าม **" + str(skipped_cases) + "** เคสที่ expected problem list ว่างตามนิยามของชุดข้อมูล",
        "การวิเคราะห์นี้ปรับพารามิเตอร์ครั้งละหนึ่งค่า โดยคงค่าอื่นไว้ที่ค่าปริยาย และเรียกเฉพาะ `calculate_final_score_probabilistic`",
        "ไม่มีการรัน retrieval, L1/L2 detection, reranker หรือ embedding model ในการวิเคราะห์นี้ ดังนั้นผลลัพธ์จึงอธิบายความไวของฟังก์ชันคะแนนภายใต้สมมติฐานนี้ ไม่ใช่ประสิทธิภาพหรือความเสถียรของโมเดล retrieval ทั้งระบบ",
        "",
        "### เกณฑ์การตีความ (Interpretation Guide)",
        "- **Low sensitivity:** ค่าเฉลี่ยของฟังก์ชันคะแนนเปลี่ยนแปลงน้อยกว่า 5% จากค่าปริยายภายในช่วงที่ทดสอบ",
        "- **Moderate sensitivity:** ค่าเฉลี่ยของฟังก์ชันคะแนนเปลี่ยนแปลงตั้งแต่ 5% แต่ไม่ถึง 10%",
        "- **High sensitivity:** ค่าเฉลี่ยของฟังก์ชันคะแนนเปลี่ยนแปลงตั้งแต่ 10% ขึ้นไป",
        "- **Not exercised:** พารามิเตอร์อยู่ในสาขาการคำนวณที่ไม่ถูกเรียกใช้ภายใต้สมมติฐานนี้ จึงไม่สามารถสรุปความไวจาก delta เท่ากับศูนย์",
        "",
        "## Parameter Impact Summary",
        "",
        "| Parameter | Default | Min delta | Max delta | Max absolute delta | Interpretation |",
        "|-----------|---------|-----------|-----------|--------------------|----------------|",
    ]

    for sweep in PARAMETER_SWEEPS:
        if sweep.name not in results:
            continue
        param_data = results[sweep.name]
        base_score = baseline['mean_score']
        deltas = []
        for val, metrics in param_data.items():
            if base_score > 0:
                delta = ((metrics['mean_score'] - base_score) / base_score) * 100
                deltas.append(delta)

        if deltas:
            min_d = min(deltas)
            max_d = max(deltas)
            max_abs = max(abs(min_d), abs(max_d))
            if sweep.name in {'MARGIN_M', 'L1_WEIGHT_BETA'}:
                verdict = "Not exercised in this score-function setup"
            elif max_abs < 5:
                verdict = "Low sensitivity"
            elif max_abs < 10:
                verdict = "Moderate sensitivity"
            else:
                verdict = "High sensitivity"
            lines.append(
                f"| {sweep.label} | {sweep.default} | {min_d:+.2f}% | {max_d:+.2f}% | {max_abs:.2f}% | {verdict} |"
            )

    # Overall verdict
    all_max = []
    for sweep in PARAMETER_SWEEPS:
        if sweep.name not in results:
            continue
        base_score = baseline['mean_score']
        for val, metrics in results[sweep.name].items():
            if base_score > 0:
                delta = abs((metrics['mean_score'] - base_score) / base_score * 100)
                all_max.append(delta)

    if all_max:
        overall_max = max(all_max)
        lines.extend([
            "",
            "## สรุปความไวของฟังก์ชันคะแนน (Overall Score-Function Sensitivity)",
            "",
        ])
        if overall_max < 5:
            lines.append("> ภายในช่วงที่ทดสอบ พารามิเตอร์ที่ถูกกระตุ้นทุกตัวทำให้ค่าเฉลี่ยของฟังก์ชันคะแนนเปลี่ยนแปลงน้อยกว่า 5%")
        elif overall_max < 10:
            lines.append(f"> ฟังก์ชันคะแนนมีความไวปานกลางต่อบางพารามิเตอร์ (สูงสุด {overall_max:.1f}%)")
        else:
            lines.append(f"> ฟังก์ชันคะแนนมีความไวสูงต่อบางพารามิเตอร์ (ค่าเปลี่ยนแปลงสูงสุด {overall_max:.1f}%) ภายใต้ช่วงค่าที่ทดสอบ")

        lines.extend([
            "",
            "### ข้อจำกัดในการตีความ",
            "",
            "`MARGIN_M` ไม่ถูกกระตุ้นเนื่องจากไม่ได้ส่ง document/problem embeddings เข้าสู่ฟังก์ชันคะแนน และ `L1_WEIGHT_BETA` ไม่ถูกกระตุ้นเนื่องจากใช้ detected problem list กับ confidence คงที่ ค่า delta เท่ากับศูนย์ของสองพารามิเตอร์นี้จึงไม่ใช่หลักฐานว่ามีความไวต่ำ",
        ])

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    logger.info(f"Report saved: {report_path}")


def build_run_metadata(analyzer: SensitivityAnalyzer, baseline: Dict[str, Any],
                       started_at: str, status: str = 'complete',
                       error: str = None) -> Dict[str, Any]:
    """Build an auditable manifest for this exact OAT run."""
    root = Path(__file__).resolve().parent.parent
    h2l_core_path = root / 'h2l' / 'core.py'
    scored_ids = list(baseline.get('scored_case_ids', []))
    expected_ids = [case['case_id'] for case in analyzer.scorable_cases]
    case_set_verified = scored_ids == expected_ids

    if status == 'complete' and not case_set_verified:
        raise ValueError("Cannot mark sensitivity metadata complete: case set is not verified")

    public_baseline = {
        key: value for key, value in baseline.items()
        if key != 'scored_case_ids'
    }
    metadata = {
        'status': status,
        'analysis_scope': ANALYSIS_SCOPE,
        'split': 'train',
        'started_at': started_at,
        'completed_at': _now_iso() if status == 'complete' else None,
        'selected_cases': len(analyzer.cases),
        'scored_cases': len(scored_ids),
        'skipped_empty_problem_lists': len(analyzer.skipped_case_ids),
        'skipped_case_ids': analyzer.skipped_case_ids,
        'scored_case_ids': scored_ids,
        'case_set_invariant_verified': case_set_verified,
        'ground_truth_path': str(analyzer.ground_truth_path),
        'ground_truth_sha256': file_sha256(analyzer.ground_truth_path),
        'ground_truth_last_updated': analyzer.ground_truth_metadata.get('last_updated'),
        'ground_truth_counts': {
            'total': analyzer.all_case_count,
            'train': analyzer.train_case_count,
            'test': analyzer.test_case_count,
        },
        'h2l_core_path': str(h2l_core_path),
        'h2l_core_sha256': file_sha256(h2l_core_path),
        'analysis_code_path': str(Path(__file__).resolve()),
        'analysis_code_sha256': file_sha256(Path(__file__).resolve()),
        'parameter_count': len(PARAMETER_SWEEPS),
        'configuration_rows': sum(len(sweep.values) for sweep in PARAMETER_SWEEPS),
        'parameters': [
            {
                'name': sweep.name,
                'label': sweep.label,
                'default': sweep.default,
                'values': sweep.values,
                'description': sweep.description,
            }
            for sweep in PARAMETER_SWEEPS
        ],
        'scoring_assumptions': {
            'method': 'one-at-a-time score-function sensitivity',
            'retrieval_executed': False,
            'rerank_score_fixed': SIMULATED_RERANK_SCORE,
            'detection_confidence_fixed': SIMULATED_DETECTION_CONFIDENCE,
            'doc_text_source': 'ground-truth case_description',
            'query_text_source': 'ground-truth case_description',
            'empty_problem_lists': 'excluded and disclosed; never scored as zero',
            'not_exercised_parameters': {
                'MARGIN_M': 'no document/problem embeddings were supplied',
                'L1_WEIGHT_BETA': 'detected problems and confidence were held fixed',
            },
        },
        'baseline': public_baseline,
    }
    if error:
        metadata['error'] = error
    return metadata


def write_run_metadata(metadata: Dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / 'run_metadata.json'
    with path.open('w', encoding='utf-8') as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    logger.info("Run metadata saved: %s", path)
    return path


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='H2L V6 Parameter Sensitivity Analysis')
    parser.add_argument('--max-cases', type=int, default=None,
                        help='Limit number of ground truth cases')
    parser.add_argument('--output-dir', type=str, default='sensitivity_results',
                        help='Output directory')
    parser.add_argument('--gt-path', type=str, default='data/expanded_ground_truth.json',
                        help='Ground truth file path')
    args = parser.parse_args()

    print("=" * 60)
    print("H2L V6 Parameter Sensitivity Analysis")
    print("=" * 60)

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    ground_truth_path = Path(args.gt_path).resolve()
    h2l_core_path = Path(__file__).resolve().parent.parent / 'h2l' / 'core.py'
    started_at = _now_iso()
    initial_metadata = {
        'status': 'running',
        'analysis_scope': ANALYSIS_SCOPE,
        'split': 'train',
        'started_at': started_at,
        'ground_truth_path': str(ground_truth_path),
        'ground_truth_sha256': file_sha256(ground_truth_path),
        'h2l_core_path': str(h2l_core_path),
        'h2l_core_sha256': file_sha256(h2l_core_path),
    }
    write_run_metadata(initial_metadata, output_dir)

    analyzer = None
    baseline: Dict[str, Any] = {}
    try:
        analyzer = SensitivityAnalyzer(
            ground_truth_path=str(ground_truth_path),
            max_cases=args.max_cases,
        )
        results, baseline = analyzer.run_sensitivity()
        n_scored = int(baseline['n_scored'])

        generate_csv(results, baseline, output_dir, n_scored)
        generate_visualizations(results, baseline, output_dir)
        generate_report(
            results,
            baseline,
            len(analyzer.cases),
            n_scored,
            len(analyzer.skipped_case_ids),
            output_dir,
        )
        complete_metadata = build_run_metadata(
            analyzer,
            baseline,
            started_at,
            status='complete',
        )
        write_run_metadata(complete_metadata, output_dir)
    except Exception as exc:
        failed_metadata = dict(initial_metadata)
        failed_metadata.update({
            'status': 'failed',
            'failed_at': _now_iso(),
            'error': f"{type(exc).__name__}: {exc}",
        })
        if analyzer is not None:
            failed_metadata.update({
                'selected_cases': len(analyzer.cases),
                'scored_cases': int(baseline.get('n_scored', 0)),
                'skipped_empty_problem_lists': len(analyzer.skipped_case_ids),
                'skipped_case_ids': analyzer.skipped_case_ids,
            })
        write_run_metadata(failed_metadata, output_dir)
        raise

    print(f"\n{'=' * 60}")
    print("Sensitivity analysis complete")
    print(f"   Results in: {output_dir.absolute()}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
