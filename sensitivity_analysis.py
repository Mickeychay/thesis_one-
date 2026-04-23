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
import copy
import logging
import argparse
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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
        self.ground_truth_path = ground_truth_path
        self.max_cases = max_cases
        self.cases = self._load_cases()

    def _load_cases(self) -> List[Dict]:
        """Load ground truth cases with problem definitions"""
        with open(self.ground_truth_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        cases = [c for c in data.get('cases', []) if c.get('split', 'train') == 'train']
        if self.max_cases:
            cases = cases[:self.max_cases]
        logger.info(f"📊 Loaded {len(cases)} ground truth cases (Real-world queries mapped to expert problem lists)")
        return cases

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
                'confidence': 0.8,  # Simulated detection confidence
                'keywords': keywords_map.get(code, []),
            })
        return problems

    def run_single_config(self, config) -> Dict[str, float]:
        """
        Run scoring on all cases with a given config.
        Returns mean metrics across all cases.
        """
        from H2L_core import calculate_final_score_probabilistic

        boosts = []
        phis = []
        alphas = []
        scores = []

        for case in self.cases:
            query = case.get('case_description', '')
            problems = self._build_problems_from_case(case)
            if not problems or not query:
                continue

            # Simulate a rerank_score (base retrieval score)
            rerank_score = 0.5

            try:
                final_score, breakdown = calculate_final_score_probabilistic(
                    rerank_score=rerank_score,
                    problems=problems,
                    doc_text=query,  # Use case text as "retrieved doc"
                    config=config,
                )

                boosts.append(breakdown.get('boost', 1.0))
                alphas.append(breakdown.get('α_eff', 1.0))
                scores.append(final_score)

                # Mean Φ_i across factors
                factors = breakdown.get('factors', [])
                if factors:
                    mean_phi = np.mean([f.get('Φ_i', 0) for f in factors])
                    phis.append(mean_phi)

            except Exception as e:
                logger.warning(f"  ⚠️ Case {case.get('case_id', '?')}: {e}")
                continue

        return {
            'mean_boost': float(np.mean(boosts)) if boosts else 0,
            'mean_Φ_i': float(np.mean(phis)) if phis else 0,
            'mean_α_eff': float(np.mean(alphas)) if alphas else 0,
            'mean_score': float(np.mean(scores)) if scores else 0,
            'std_score': float(np.std(scores)) if scores else 0,
        }

    def run_sensitivity(self) -> Tuple[Dict, Dict]:
        """
        Run full OAT sensitivity analysis.
        
        Returns:
            results: {param_name: {value: metrics_dict}}
            baseline: default metrics
        """
        from H2L_core import H2LConfigV3

        # 1. Run baseline (all defaults)
        logger.info("\n📐 Running baseline (default parameters)...")
        default_config = H2LConfigV3()
        baseline = self.run_single_config(default_config)
        logger.info(f"   Baseline: boost={baseline['mean_boost']:.4f}, "
                    f"score={baseline['mean_score']:.4f}")

        # 2. Sweep each parameter
        results = {}
        for sweep in PARAMETER_SWEEPS:
            logger.info(f"\n🔧 Sweeping {sweep.label} ({sweep.name})")
            param_results = {}

            for val in sweep.values:
                # Create config with this one parameter changed
                config = H2LConfigV3()
                setattr(config, sweep.name, val)
                # Re-run __post_init__ to fix weights if needed
                config.__post_init__()

                metrics = self.run_single_config(config)
                param_results[val] = metrics

                is_default = "← default" if val == sweep.default else ""
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
        ax.set_title('H2L V6 Parameter Sensitivity Analysis\n(Δ% change in mean score from default)',
                     fontsize=14, fontweight='bold')
        ax.set_xlabel('Parameter Values (★ = default)', fontsize=11)
        plt.tight_layout()
        plt.savefig(output_dir / 'sensitivity_heatmap.png', dpi=300, bbox_inches='tight')
        plt.close()
        logger.info(f"✅ Heatmap saved: {output_dir / 'sensitivity_heatmap.png'}")

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
        ax.set_title('Parameter Impact Tornado Plot\n(Max score change when parameter is varied)',
                     fontsize=14, fontweight='bold')
        ax.grid(axis='x', alpha=0.3)

        # Add robustness indicator
        max_impact = max(imp['max_abs'] for imp in impacts)
        if max_impact < 5:
            robustness = "✅ ROBUST (Stable: Score changes < 5%)"
            color = '#2ECC71'
        elif max_impact < 10:
            robustness = "⚠️ MODERATE (Score changes 5-10%)"
            color = '#F39C12'
        else:
            robustness = f"❌ SENSITIVE (Unstable: Score changes > 10%)"
            color = '#E74C3C'

        ax.text(0.02, 0.98, robustness, transform=ax.transAxes,
                fontsize=12, fontweight='bold', color=color,
                verticalalignment='top',
                bbox=dict(boxstyle='round,pad=0.5', facecolor='white',
                          edgecolor=color, alpha=0.9))

        plt.tight_layout()
        plt.savefig(output_dir / 'sensitivity_tornado.png', dpi=300, bbox_inches='tight')
        plt.close()
        logger.info(f"✅ Tornado plot saved: {output_dir / 'sensitivity_tornado.png'}")


def generate_csv(results: Dict, baseline: Dict, output_dir: Path):
    """Export raw data to CSV"""
    import csv

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / 'sensitivity_raw.csv'

    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'parameter', 'label', 'value', 'is_default',
            'mean_boost', 'mean_Φ_i', 'mean_α_eff',
            'mean_score', 'std_score',
            'Δ_score_%'
        ])

        for sweep in PARAMETER_SWEEPS:
            if sweep.name not in results:
                continue
            for val, metrics in results[sweep.name].items():
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
                ])

    logger.info(f"✅ CSV saved: {csv_path}")


def generate_report(results: Dict, baseline: Dict, num_cases: int, output_dir: Path):
    """Generate markdown summary report"""
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / 'sensitivity_report.md'

    lines = [
        "# H2L V6 Parameter Sensitivity Report",
        f"\n**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"\n**Baseline Score**: {baseline['mean_score']:.6f}",
        f"**Baseline Boost**: {baseline['mean_boost']:.4f}",
        f"**Cases Evaluated**: {num_cases}",
        "",
        "### 📌 แหล่งที่มาและประเภทของเคสทดสอบ (Test Cases Context)",
        "เคสจำนวนทั้งหมด **" + str(num_cases) + "** เคส ถูกดึงมาจากไฟล์ Ground Truth ซึ่งสร้างขึ้นจากฐานข้อมูลปัญหาผู้ใช้งานจริง (Real-world user queries) และได้รับการเฉลย (Label/Annotate) โดยอิงตามแนวทางการประเมินผู้รับบริการจริง",
        "**ประเภทเคสที่นำมาทดสอบครอบคลุม:**",
        "- **เคสแจ้งเหตุวิกฤต/ฉุกเฉิน (High Severity)**: ทดสอบว่าโมเดลทำคะแนนได้ไวและแม่นยำแค่ไหนเมื่อเจอเคสอันตราย",
        "- **เคสปัญหาสังคมทั่วไป (Standard Cases)**: ทดสอบมาตรฐานการให้คะแนนเคสทั่วไป",
        "- **เคสที่มีรูปประโยคปฏิเสธหรือมีความซับซ้อนทางภาษา (Polarity & Negation Cases)**: ทดสอบว่าโมเดลฉลาดพอที่จะไม่โดนหลอกจากคำหลอก",
        "เพื่อให้มั่นใจว่าเราได้ทดสอบความเสถียรของโมเดลครบทุกบริบทของการใช้งานจริง",
        "",
        "### 💡 คำแนะนำในการอ่านผล (Interpretation Guide)",
        "- **✅ Robust (เสถียร):** เมื่อปรับจูนค่าตัวแปรนี้ขึ้นหรือลงแล้ว คะแนนที่ระบบประเมินออกมาแทบจะไม่ผันผวน (เปลี่ยนไปจากเดิมน้อยกว่า 5%) แสดงว่าระบบของเราแข็งแกร่ง ไม่รวนง่ายแม้ตั้งค่าคลาดเคลื่อน",
        "- **⚠️ Moderate (เสถียรปานกลาง):** การปรับจูนค่าตัวแปรมีผลกระทบต่อคะแนนรวมในระดับหนึ่ง (ประมาณ 5-10%)",
        "- **❌ Sensitive (อ่อนไหว):** การเปลี่ยนแปลงค่าตัวแปรนี้แม้เพียงเล็กน้อย ทำให้คะแนนรวมระบบเปลี่ยนไปอย่างมาก (มากกว่า 10%) แสดงว่าเป็นตัวแปรควบคุมที่สำคัญมาก ต้องตั้งค่าอย่างระมัดระวังที่สุด",
        "",
        "## Parameter Impact Summary",
        "",
        "| Parameter | Default | Min Δ% | Max Δ% | Max |Δ| | Verdict |",
        "|-----------|---------|--------|--------|---------|---------|",
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
            verdict = "✅ Robust (เสถียร)" if max_abs < 5 else ("⚠️ Moderate (ปานกลาง)" if max_abs < 10 else "❌ Sensitive (อ่อนไหว)")
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
            "## สรุปภาพรวมความเสถียร (Overall Verdict)",
            "",
        ])
        if overall_max < 5:
            lines.append("> ✅ **มีความเสถียรสูง (ROBUST)**: ตัวแปรทุกตัวเมื่อถูกเปลี่ยนแปลง มีผลกระทบต่อคะแนนรวมของระบบน้อยกว่า 5%")
            lines.append("> แสดงให้เห็นว่าการออกแบบสมการนี้ ซึ่งใช้ค่า Parameter อ้างอิงจากหลักเกณฑ์ผู้เชี่ยวชาญ (Domain Knowledge) เป็นค่าที่ไว้ใจได้ ระบบมีความแข็งแกร่ง ไม่ให้คะแนนมั่วแม้เจอความเบี่ยงเบนเล็กน้อย")
        elif overall_max < 10:
            lines.append(f"> ⚠️ **มีความเสถียรปานกลาง (MODERATE)**: มีบางตัวแปรส่งผลกระทบชัดเจนต่อคะแนน (สูงสุด {overall_max:.1f}%)")
        else:
            lines.append(f"> ❌ **มีความอ่อนไหวสูง (SENSITIVE)**: โมเดลผันผวนสูงมากเมื่อเปลี่ยนค่าตัวแปรหลัก (คะแนนเหวี่ยงสูงสุด {overall_max:.1f}%) ควรมีการตรวจสอบการตั้งค่าตัวแปรนี้เพิ่มเติม")

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    logger.info(f"✅ Report saved: {report_path}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='H2L V6 Parameter Sensitivity Analysis')
    parser.add_argument('--max-cases', type=int, default=None,
                        help='Limit number of ground truth cases')
    parser.add_argument('--output-dir', type=str, default='sensitivity_results',
                        help='Output directory')
    parser.add_argument('--gt-path', type=str, default='expanded_ground_truth.json',
                        help='Ground truth file path')
    args = parser.parse_args()

    print("=" * 60)
    print("H2L V6 Parameter Sensitivity Analysis")
    print("=" * 60)

    analyzer = SensitivityAnalyzer(
        ground_truth_path=args.gt_path,
        max_cases=args.max_cases,
    )

    results, baseline = analyzer.run_sensitivity()
    output_dir = Path(args.output_dir)

    generate_csv(results, baseline, output_dir)
    generate_visualizations(results, baseline, output_dir)
    generate_report(results, baseline, len(analyzer.cases), output_dir)

    print(f"\n{'=' * 60}")
    print(f"✅ Sensitivity analysis complete!")
    print(f"   Results in: {output_dir.absolute()}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
