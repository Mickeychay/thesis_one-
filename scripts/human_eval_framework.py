#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Human Evaluation Framework for H2L
====================================
Generates evaluation packets for domain experts (social workers) to assess
retrieval quality in a blinded comparison.

Features:
1. Stratified sampling of evaluation cases
2. Blind comparison format (strategy labels hidden)
3. Rating rubric: Relevance, Completeness, Clinical Usefulness (1-5)
4. CSV export for evaluator input
5. Inter-rater reliability calculation (Krippendorff's Alpha)

Usage:
    python human_eval_framework.py generate             # Generate evaluation packets
    python human_eval_framework.py analyze results.csv  # Analyze completed evaluations
"""

import json
import csv
import random
import argparse
import math
from pathlib import Path
from typing import List, Dict, Tuple
from datetime import datetime
from collections import defaultdict

random.seed(42)


# ============================================================================
# EVALUATION PACKET GENERATION
# ============================================================================

RATING_RUBRIC = {
    "relevance": {
        "name_th": "ความเกี่ยวข้อง",
        "name_en": "Relevance",
        "description_th": "เอกสารที่ค้นพบมีความเกี่ยวข้องกับปัญหาที่ระบุในเคสมากน้อยเพียงใด",
        "scale": {
            1: "ไม่เกี่ยวข้องเลย — เอกสารไม่ตรงกับปัญหาใดใดในเคส",
            2: "เกี่ยวข้องน้อย — เอกสารเกี่ยวข้องกับหัวข้อกว้าง แต่ไม่ตรงกับปัญหาเฉพาะ",
            3: "เกี่ยวข้องปานกลาง — เอกสารตรงกับปัญหาบางส่วน",
            4: "เกี่ยวข้องมาก — เอกสารตรงกับปัญหาหลักในเคส",
            5: "เกี่ยวข้องมากที่สุด — เอกสารตรงกับปัญหาทุกด้านในเคส",
        }
    },
    "completeness": {
        "name_th": "ความครบถ้วน",
        "name_en": "Completeness",
        "description_th": "เอกสารที่ค้นพบครอบคลุมมิติต่างๆ ของปัญหาครบถ้วนเพียงใด",
        "scale": {
            1: "ไม่ครบถ้วนเลย — ขาดข้อมูลสำคัญส่วนใหญ่",
            2: "ครบถ้วนน้อย — ครอบคลุมเพียง 1 มิติของปัญหา",
            3: "ครบถ้วนปานกลาง — ครอบคลุม 2-3 มิติ",
            4: "ครบถ้วนมาก — ครอบคลุมเกือบทุกมิติ",
            5: "ครบถ้วนสมบูรณ์ — ครอบคลุมทุกมิติของปัญหา",
        }
    },
    "clinical_usefulness": {
        "name_th": "ประโยชน์ทางคลินิก",
        "name_en": "Clinical Usefulness",
        "description_th": "เอกสารที่ค้นพบมีประโยชน์สำหรับการวางแผนช่วยเหลือผู้รับบริการมากน้อยเพียงใด",
        "scale": {
            1: "ไม่มีประโยชน์ — ไม่สามารถนำไปใช้วางแผนได้",
            2: "มีประโยชน์น้อย — ให้ข้อมูลพื้นฐานบางส่วน",
            3: "มีประโยชน์ปานกลาง — ช่วยในการวางแผนบางด้าน",
            4: "มีประโยชน์มาก — ช่วยในการวางแผนส่วนใหญ่",
            5: "มีประโยชน์มากที่สุด — ช่วยในการวางแผนอย่างครอบคลุมและมั่นใจ",
        }
    }
}


def sample_evaluation_cases(
    ground_truth_path: str = "expanded_ground_truth.json",
    n_per_complexity: int = 10,
) -> List[Dict]:
    """Stratified sampling: n cases per complexity level"""
    with open(ground_truth_path, 'r', encoding='utf-8') as f:
        gt = json.load(f)

    cases = gt.get('cases', [])
    by_complexity = defaultdict(list)
    for c in cases:
        by_complexity[c.get('complexity', 'unknown')].append(c)

    sampled = []
    for complexity in ['simple', 'moderate', 'complex']:
        pool = by_complexity.get(complexity, [])
        n = min(n_per_complexity, len(pool))
        sampled.extend(random.sample(pool, n))

    random.shuffle(sampled)
    return sampled


def generate_evaluation_csv(
    cases: List[Dict],
    strategy_results: Dict[str, List] = None,
    output_path: str = "human_evaluation_form.csv",
    strategies_to_compare: List[str] = None,
):
    """
    Generate a CSV evaluation form.

    If strategy_results is None, creates a template with doc placeholders.
    """
    if strategies_to_compare is None:
        strategies_to_compare = ["System_A", "System_B"]

    fieldnames = [
        "evaluator_id",
        "case_id",
        "case_description",
        "expected_problems",
        "system_label",  # Blinded: "System_A", "System_B", etc.
        "retrieved_doc_1",
        "retrieved_doc_2",
        "retrieved_doc_3",
        "retrieved_doc_4",
        "retrieved_doc_5",
        "relevance_score",
        "completeness_score",
        "clinical_usefulness_score",
        "comments",
    ]

    with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for case in cases:
            problems_str = "; ".join(
                f"{p.get('code', '?')}: {p.get('category', '?')} (sev={p.get('severity', '?')})"
                for p in case.get('expected_diagnosis', {}).get('problem_list', [])
            )

            for sys_label in strategies_to_compare:
                row = {
                    "evaluator_id": "",
                    "case_id": case.get('case_id', ''),
                    "case_description": case.get('case_description', '')[:300],
                    "expected_problems": problems_str,
                    "system_label": sys_label,
                    "retrieved_doc_1": "[ใส่ข้อความจากเอกสารที่ 1]",
                    "retrieved_doc_2": "[ใส่ข้อความจากเอกสารที่ 2]",
                    "retrieved_doc_3": "[ใส่ข้อความจากเอกสารที่ 3]",
                    "retrieved_doc_4": "[ใส่ข้อความจากเอกสารที่ 4]",
                    "retrieved_doc_5": "[ใส่ข้อความจากเอกสารที่ 5]",
                    "relevance_score": "",
                    "completeness_score": "",
                    "clinical_usefulness_score": "",
                    "comments": "",
                }

                # Fill in actual retrieved docs if available
                if strategy_results and sys_label in strategy_results:
                    case_results = [
                        r for r in strategy_results[sys_label]
                        if r.get('case_id') == case.get('case_id')
                    ]
                    if case_results:
                        docs = case_results[0].get('doc_details', [])
                        for di, doc in enumerate(docs[:5]):
                            row[f"retrieved_doc_{di+1}"] = doc.get('text_preview', '')

                writer.writerow(row)

    return output_path


def generate_rubric_sheet(output_path: str = "evaluation_rubric.md"):
    """Generate a rubric reference sheet for evaluators"""
    lines = [
        "# แบบประเมินคุณภาพการค้นหาเอกสาร (Retrieval Quality Evaluation Rubric)",
        "",
        "## คำชี้แจง",
        "กรุณาให้คะแนนเอกสารที่ระบบค้นหามาให้ตามเกณฑ์ 3 ด้าน (คะแนน 1-5)",
        "โดยเปรียบเทียบกับเคสที่กำหนดและปัญหาที่คาดหวัง",
        "",
    ]

    for dim_key, dim in RATING_RUBRIC.items():
        lines.append(f"## {dim['name_th']} ({dim['name_en']})")
        lines.append(f"*{dim['description_th']}*")
        lines.append("")
        lines.append("| คะแนน | ความหมาย |")
        lines.append("|:-----:|----------|")
        for score, desc in dim['scale'].items():
            lines.append(f"| {score} | {desc} |")
        lines.append("")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))

    return output_path


# ============================================================================
# INTER-RATER RELIABILITY
# ============================================================================

def krippendorff_alpha(data: List[List], level: str = "ordinal") -> float:
    """
    Calculate Krippendorff's Alpha for inter-rater reliability.

    Args:
        data: List of lists, where each inner list contains ratings by one evaluator.
              Use None for missing values.
        level: "nominal", "ordinal", or "interval"

    Returns:
        Alpha value (-1 to 1, where 1 = perfect agreement)
    """
    # Flatten to units × observers matrix
    n_units = len(data[0]) if data else 0
    n_observers = len(data)

    if n_units == 0 or n_observers < 2:
        return 0.0

    # Collect all unique values
    all_values = set()
    for observer_data in data:
        for v in observer_data:
            if v is not None:
                all_values.add(v)
    values = sorted(all_values)

    if len(values) < 2:
        return 1.0  # Perfect agreement if everyone gives the same rating

    # Distance function
    def distance(v1, v2):
        if level == "nominal":
            return 0.0 if v1 == v2 else 1.0
        elif level == "ordinal":
            i1 = values.index(v1)
            i2 = values.index(v2)
            return (i1 - i2) ** 2
        else:  # interval
            return (v1 - v2) ** 2

    # Compute observed disagreement (D_o)
    n_total = 0
    d_observed = 0.0
    value_counts = defaultdict(int)

    for u in range(n_units):
        # Get all ratings for this unit
        ratings = [data[o][u] for o in range(n_observers) if data[o][u] is not None]
        m = len(ratings)
        if m < 2:
            continue

        n_total += m

        for v in ratings:
            value_counts[v] += 1

        for i in range(len(ratings)):
            for j in range(i + 1, len(ratings)):
                d_observed += distance(ratings[i], ratings[j])

        d_observed_normalized = d_observed / (m - 1) if m > 1 else 0

    if n_total == 0:
        return 0.0

    # Compute expected disagreement (D_e)
    d_expected = 0.0
    total_pairs = n_total * (n_total - 1)

    for v1 in values:
        for v2 in values:
            if v1 != v2:
                d_expected += value_counts[v1] * value_counts[v2] * distance(v1, v2)

    if total_pairs > 0:
        d_expected /= total_pairs

    if d_expected == 0:
        return 1.0

    alpha = 1.0 - (d_observed / d_expected) if d_expected > 0 else 0.0
    return alpha


def analyze_human_evaluation(csv_path: str) -> Dict:
    """
    Analyze completed human evaluation CSV.

    Returns:
        Dict with per-system scores, inter-rater reliability, and comparison
    """
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("❌ No data in CSV")
        return {}

    # Group by system and evaluator
    systems = defaultdict(lambda: defaultdict(list))
    evaluators = set()
    dimensions = ['relevance_score', 'completeness_score', 'clinical_usefulness_score']

    for row in rows:
        sys_label = row.get('system_label', '')
        evaluator = row.get('evaluator_id', '')
        evaluators.add(evaluator)

        for dim in dimensions:
            try:
                score = int(row.get(dim, 0))
                systems[sys_label][dim].append(score)
            except (ValueError, TypeError):
                pass

    # Per-system statistics
    system_stats = {}
    for sys_label, dim_scores in systems.items():
        stats = {}
        for dim in dimensions:
            scores = dim_scores.get(dim, [])
            if scores:
                mean = sum(scores) / len(scores)
                std = (sum((s - mean)**2 for s in scores) / len(scores)) ** 0.5
                stats[dim] = {'mean': round(mean, 3), 'std': round(std, 3), 'n': len(scores)}
        system_stats[sys_label] = stats

    # Inter-rater reliability (per dimension)
    irr = {}
    evaluator_list = sorted(evaluators)
    if len(evaluator_list) >= 2:
        for dim in dimensions:
            # Build per-evaluator rating arrays
            by_evaluator = defaultdict(dict)
            for row in rows:
                ev = row.get('evaluator_id', '')
                case_sys = f"{row.get('case_id', '')}_{row.get('system_label', '')}"
                try:
                    by_evaluator[ev][case_sys] = int(row.get(dim, 0))
                except (ValueError, TypeError):
                    by_evaluator[ev][case_sys] = None

            # Align to same unit order
            all_units = sorted(set().union(*[set(d.keys()) for d in by_evaluator.values()]))
            data_matrix = []
            for ev in evaluator_list:
                ratings = [by_evaluator.get(ev, {}).get(u) for u in all_units]
                data_matrix.append(ratings)

            try:
                alpha = krippendorff_alpha(data_matrix, level="ordinal")
                irr[dim] = round(alpha, 4)
            except Exception:
                irr[dim] = None

    # Print results
    print("\n" + "=" * 70)
    print("📊 Human Evaluation Results")
    print("=" * 70)

    for sys_label, stats in system_stats.items():
        print(f"\n  {sys_label}:")
        for dim, s in stats.items():
            dim_name = dim.replace('_score', '').replace('_', ' ').title()
            print(f"    {dim_name}: {s['mean']:.2f} ± {s['std']:.2f} (n={s['n']})")

    if irr:
        print(f"\n  Inter-rater Reliability (Krippendorff's α):")
        for dim, alpha in irr.items():
            dim_name = dim.replace('_score', '').replace('_', ' ').title()
            quality = (
                "excellent" if alpha and alpha >= 0.8 else
                "good" if alpha and alpha >= 0.67 else
                "tentative" if alpha and alpha >= 0.33 else
                "poor"
            )
            print(f"    {dim_name}: α={alpha} ({quality})")

    return {
        'system_stats': system_stats,
        'inter_rater_reliability': irr,
        'n_evaluators': len(evaluator_list),
        'n_cases': len(set(row.get('case_id') for row in rows)),
    }


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='Human Evaluation Framework')
    subparsers = parser.add_subparsers(dest='command')

    gen_parser = subparsers.add_parser('generate', help='Generate evaluation packets')
    gen_parser.add_argument('--ground-truth', default='expanded_ground_truth.json')
    gen_parser.add_argument('--n-per-complexity', type=int, default=10)
    gen_parser.add_argument('--output-dir', default='human_evaluation')

    analyze_parser = subparsers.add_parser('analyze', help='Analyze completed evaluations')
    analyze_parser.add_argument('csv_path', help='Path to completed evaluation CSV')

    args = parser.parse_args()

    if args.command == 'generate':
        output_dir = Path(args.output_dir)
        output_dir.mkdir(exist_ok=True)

        # Sample cases
        cases = sample_evaluation_cases(args.ground_truth, args.n_per_complexity)
        print(f"📋 Sampled {len(cases)} cases for evaluation")

        # Generate CSV form
        csv_path = generate_evaluation_csv(
            cases,
            output_path=str(output_dir / "evaluation_form.csv"),
            strategies_to_compare=["System_A", "System_B"]
        )
        print(f"✅ Evaluation form: {csv_path}")

        # Generate rubric
        rubric_path = generate_rubric_sheet(str(output_dir / "evaluation_rubric.md"))
        print(f"✅ Rubric: {rubric_path}")

        # Save case list
        with open(output_dir / "evaluation_cases.json", 'w', encoding='utf-8') as f:
            json.dump({'cases': cases}, f, ensure_ascii=False, indent=2)
        print(f"✅ Case list: {output_dir / 'evaluation_cases.json'}")

        print(f"\n📌 Next steps:")
        print(f"   1. Run evaluation for both strategies to fill in retrieved docs")
        print(f"   2. Distribute forms to 3-5 evaluators (social workers)")
        print(f"   3. Collect and merge results into one CSV")
        print(f"   4. Run: python human_eval_framework.py analyze <merged.csv>")

    elif args.command == 'analyze':
        analyze_human_evaluation(args.csv_path)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
