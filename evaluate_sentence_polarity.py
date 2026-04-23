#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sentence Polarity Evaluator for H2L System
==========================================
Dedicated evaluation module for measuring G_neg effectiveness
on sentence pattern recognition (affirmative vs negated).

Metrics measured:
1. Negation Detection Rate (NDR) — % of negation cases where G_neg < 1.0
2. False Positive Rate (FPR) — % of positive cases where G_neg < 1.0 (should be 0)
3. Mean G_neg on negated queries (should be low)
4. Mean G_neg on positive queries (should be 1.0)
5. Per-length breakdown (short/medium/long)
6. Per-severity breakdown (high/medium/low)

Usage:
    python evaluate_sentence_polarity.py
    python evaluate_sentence_polarity.py --ground-truth expanded_ground_truth.json
"""

import json
import sys
import logging
from pathlib import Path
from collections import defaultdict
from datetime import datetime

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from H2L_core import calculate_sentence_polarity, H2LConfigV3

log_dir = Path(__file__).parent / "logs"
log_dir.mkdir(exist_ok=True)
log_file = log_dir / f"evaluate_sentence_polarity_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(str(log_file), encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

LATEST_POLARITY_ARTIFACT = Path("evaluation_results/sentence_polarity_latest.json")
POLARITY_PROGRESS_ARTIFACT = Path("evaluation_results/sentence_polarity_progress.json")


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)


def _write_progress(payload):
    _write_json(POLARITY_PROGRESS_ARTIFACT, {
        "updated_at": datetime.now().isoformat(),
        **payload,
    })


def _prune_polarity_history(keep_history: int = 2):
    files = sorted(Path("evaluation_results").glob("sentence_polarity_eval_*.json"))
    if keep_history < 0:
        keep_history = 0
    removable = files[:-keep_history] if keep_history else files
    removed = 0
    for path in removable:
        try:
            if path.exists():
                path.unlink()
                removed += 1
        except Exception as exc:
            logger.warning("Failed to prune old polarity artifact %s: %s", path, exc)
    return {
        "kept_history": keep_history,
        "removed_files": removed,
        "remaining_files": len(sorted(Path("evaluation_results").glob("sentence_polarity_eval_*.json"))),
    }


def load_polarity_cases(gt_path="expanded_ground_truth.json"):
    """Load only the polarity test cases from ground truth."""
    with open(gt_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    cases = data.get("cases", [])
    missing_split = [case.get("case_id", "unknown") for case in cases if "split" not in case]
    if missing_split:
        preview = ", ".join(missing_split[:10])
        raise ValueError(
            f"Ground truth contains {len(missing_split)} case(s) without 'split'. "
            f"Examples: {preview}"
        )

    test_cases = [c for c in cases if c.get("split") == "test"]
    metadata_test = data.get("metadata", {}).get("test_cases")
    if metadata_test is not None and int(metadata_test) != len(test_cases):
        logger.warning(
            "Ground truth metadata test_cases=%s does not match actual test split count=%s",
            metadata_test,
            len(test_cases),
        )
    return test_cases


def load_problems_from_taxonomy(taxonomy_path="problem_codes.json"):
    """Load problem taxonomy for G_neg evaluation."""
    with open(taxonomy_path, 'r', encoding='utf-8') as f:
        taxonomy = json.load(f)

    problems = {}
    for cat in taxonomy.get("categories", []):
        for prob in cat.get("problems", []):
            code = prob.get("code", "")
            problems[code] = {
                "code": code,
                "name": prob.get("name", ""),
                "severity": prob.get("severity", 1),
                "keywords": prob.get("keywords", []),
                "category_id": cat.get("id", ""),
                "category_name": cat.get("name", "Unknown Category")
            }
    return problems


def evaluate_sentence_polarity(gt_path="expanded_ground_truth.json",
                            taxonomy_path="problem_codes.json",
                            model_type="H2L (G_neg enabled)"):
    """
    Run full sentence polarity evaluation.

    Returns dict with metrics organized by:
    - overall
    - per_length (short/medium/long)
    - per_severity (high/medium/low)
    - per_case details
    """
    config = H2LConfigV3()
    if "Baseline" in model_type:
        config.NEG_ENABLE = False
        config.NEG_LAMBDA = 0.0

    polarity_cases = load_polarity_cases(gt_path)

    if not polarity_cases:
        return {"error": "No polarity test cases found in ground truth"}

    problems_db = load_problems_from_taxonomy(taxonomy_path)

    results = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "gt_file": gt_path,
            "total_polarity_cases": len(polarity_cases),
            "polarity_markers": config.NEGATION_MARKERS,
            "window_size": 30
        },
        "overall": {},
        "per_length": defaultdict(lambda: {"positive": [], "negated": []}),
        "per_severity": defaultdict(lambda: {"positive": [], "negated": []}),
        "per_case": []
    }

    logger = logging.getLogger('sentence_polarity')
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter('%(levelname)s:%(name)s: %(message)s'))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    logger.info(f"🚀 เริ่มต้นการประเมิน Sentence Polarity จำนวน {len(polarity_cases)} เคส (Model: {model_type})...")
    _write_progress({
        "status": "running",
        "phase": "evaluating",
        "ground_truth_path": gt_path,
        "taxonomy_path": taxonomy_path,
        "model_type": model_type,
        "completed_case_count": 0,
        "total_case_count": len(polarity_cases),
        "current_case_id": None,
        "current_case_index": 0,
    })

    for index, case in enumerate(polarity_cases, start=1):
        case_id = case["case_id"]
        query = case["case_description"]
        is_negated = case.get("is_negated", case.get("has_negation", False))
        length_cat = case.get("length_category", "unknown")
        severity_level = case.get("severity_level", "unknown")

        # Get expected problem codes from the case
        expected_problems = case.get("expected_diagnosis", {}).get("problem_list", [])
        expected_codes = [p["code"] for p in expected_problems]

        logger.info(f"  🔬 Evaluating [{case_id}] (Negated={is_negated}) - Expected Codes: {expected_codes}")
        _write_progress({
            "status": "running",
            "phase": "evaluating",
            "ground_truth_path": gt_path,
            "taxonomy_path": taxonomy_path,
            "model_type": model_type,
            "completed_case_count": index - 1,
            "total_case_count": len(polarity_cases),
            "current_case_id": case_id,
            "current_case_index": index,
        })

        # Build problem dicts from CASE-LEVEL relevant_keywords
        # This ensures we test with keywords that are actually relevant
        # to this specific case, not just generic taxonomy keywords
        case_keywords = case.get("relevant_keywords", {})

        # Strategy: Use BOTH case-level keywords AND taxonomy keywords
        # Case-level keywords take priority (more specific)
        g_neg_values = {}
        g_full_details = {}

        # 1) Test against case-level relevant_keywords (most accurate)
        for code, keywords in case_keywords.items():
            if keywords:
                prob_dict = {
                    "code": code,
                    "name": code,
                    "severity": next((p.get("severity", 3) for p in expected_problems if p["code"] == code), 3),
                    "keywords": keywords
                }
                g_res = calculate_sentence_polarity(prob_dict, query, config)
                g_neg_values[code] = g_res.get('gate_neg', 1.0) if isinstance(g_res, dict) else float(g_res)
                if isinstance(g_res, dict): g_full_details[code] = g_res

        # 2) Also test against taxonomy keywords for codes mentioned in case
        for code in expected_codes:
            if code not in g_neg_values and code in problems_db:
                prob = problems_db[code]
                if prob.get("keywords"):
                    g_res = calculate_sentence_polarity(prob, query, config)
                    g_neg_values[code] = g_res.get('gate_neg', 1.0) if isinstance(g_res, dict) else float(g_res)
                    if isinstance(g_res, dict): g_full_details[code] = g_res

        # 3) For negation cases with no expected problems, test against
        #    the PAIRED positive case's codes via taxonomy
        if is_negated and not expected_codes and not case_keywords:
            # Infer the paired positive case's code prefix
            base_id = case_id.replace("_NEG", "_POS")
            paired = next((c for c in polarity_cases if c["case_id"] == base_id), None)
            if paired:
                paired_keywords = paired.get("relevant_keywords", {})
                for code, keywords in paired_keywords.items():
                    if keywords:
                        prob_dict = {
                            "code": code,
                            "name": code,
                            "severity": 3,
                            "keywords": keywords
                        }
                        g_res = calculate_sentence_polarity(prob_dict, query, config)
                        g_neg_values[code] = g_res.get('gate_neg', 1.0) if isinstance(g_res, dict) else float(g_res)
                        if isinstance(g_res, dict): g_full_details[code] = g_res

        # Calculate case-level metrics
        negated_codes = {k: v for k, v in g_neg_values.items() if v < 1.0}
        any_negation_detected = len(negated_codes) > 0
        all_g = list(g_neg_values.values()) if g_neg_values else [1.0]
        min_g_neg = min(all_g)
        mean_g_neg = sum(all_g) / len(all_g)
        n_codes_negated = len(negated_codes)

        case_result = {
            "case_id": case_id,
            "is_negated": is_negated,
            "length_category": length_cat,
            "severity_level": severity_level,
            "query": query,
            "query_length_chars": len(query),
            "expected_problems": expected_codes,
            "negation_detected": any_negation_detected,
            "min_g_neg": min_g_neg,
            "mean_g_neg": mean_g_neg,
            "n_codes_negated": n_codes_negated,
            "g_neg_details": g_neg_values,
            "g_full_details": g_full_details,
            "correct": (is_negated == any_negation_detected)
        }
        results["per_case"].append(case_result)
        
        icon_res = "✅ Passed" if case_result["correct"] else "❌ Failed"
        logger.info(f"     -> G_neg: {min_g_neg:.2f} | Detected: {any_negation_detected} | {icon_res}")

        # Categorize
        group_key = "negated" if is_negated else "positive"
        results["per_length"][length_cat][group_key].append(case_result)
        results["per_severity"][severity_level][group_key].append(case_result)

    # Calculate overall metrics
    positive_cases = [c for c in results["per_case"] if not c["is_negated"]]
    negated_cases = [c for c in results["per_case"] if c["is_negated"]]

    # Negation Detection Rate (NDR)
    ndr = sum(1 for c in negated_cases if c["negation_detected"]) / len(negated_cases) if negated_cases else 0

    # False Positive Rate (FPR) — positive cases wrongly detected as negated
    fpr = sum(1 for c in positive_cases if c["negation_detected"]) / len(positive_cases) if positive_cases else 0

    # True Positive Rate
    tpr = ndr

    # F1 Score for negation detection
    precision = (sum(1 for c in negated_cases if c["negation_detected"]) /
                 (sum(1 for c in negated_cases if c["negation_detected"]) +
                  sum(1 for c in positive_cases if c["negation_detected"]))) if (ndr > 0 or fpr > 0) else 0

    f1 = 2 * precision * tpr / (precision + tpr) if (precision + tpr) > 0 else 0

    # Accuracy
    accuracy = sum(1 for c in results["per_case"] if c["correct"]) / len(results["per_case"])

    # Mean G_neg values
    mean_g_pos = sum(c["min_g_neg"] for c in positive_cases) / len(positive_cases) if positive_cases else 1.0
    mean_g_neg = sum(c["min_g_neg"] for c in negated_cases) / len(negated_cases) if negated_cases else 0.0

    results["overall"] = {
        "accuracy": accuracy,
        "negation_detection_rate": ndr,
        "false_positive_rate": fpr,
        "precision": precision,
        "f1_score": f1,
        "mean_g_neg_positive": mean_g_pos,
        "mean_g_neg_negated": mean_g_neg,
        "n_positive": len(positive_cases),
        "n_negated": len(negated_cases),
        "total_cases": len(results["per_case"])
    }
    
    logger.info(f"✅ ประเมินเสร็จสิ้น! ความแม่นยำ (Acc)={accuracy:.1%} | ตรวจจับคำปฏิเสธ (NDR)={ndr:.1%} | ผิดพลาด (FPR)={fpr:.1%}")

    # Per-length summary
    length_summary = {}
    for length, groups in results["per_length"].items():
        pos = groups["positive"]
        neg = groups["negated"]
        length_summary[length] = {
            "n_positive": len(pos),
            "n_negated": len(neg),
            "ndr": sum(1 for c in neg if c["negation_detected"]) / len(neg) if neg else 0,
            "fpr": sum(1 for c in pos if c["negation_detected"]) / len(pos) if pos else 0,
            "mean_g_pos": sum(c["min_g_neg"] for c in pos) / len(pos) if pos else 1.0,
            "mean_g_neg": sum(c["min_g_neg"] for c in neg) / len(neg) if neg else 0.0,
        }
    results["per_length_summary"] = length_summary

    # Per-severity summary
    severity_summary = {}
    for sev, groups in results["per_severity"].items():
        pos = groups["positive"]
        neg = groups["negated"]
        severity_summary[sev] = {
            "n_positive": len(pos),
            "n_negated": len(neg),
            "ndr": sum(1 for c in neg if c["negation_detected"]) / len(neg) if neg else 0,
            "fpr": sum(1 for c in pos if c["negation_detected"]) / len(pos) if pos else 0,
            "mean_g_pos": sum(c["min_g_neg"] for c in pos) / len(pos) if pos else 1.0,
            "mean_g_neg": sum(c["min_g_neg"] for c in neg) / len(neg) if neg else 0.0,
        }
    results["per_severity_summary"] = severity_summary

    # Problem Distribution Summary
    category_summary = {}
    for c in results["per_case"]:
        # If no expected problems, count as control case
        if not c.get("expected_problems"):
            cat_id = "CTRL"
            if cat_id not in category_summary:
                category_summary[cat_id] = {"name": "กลุ่มควบคุม (Control / General)", "total": 0, "problems": {}}
            category_summary[cat_id]["total"] += 1
            continue
            
        for expected_code in c.get("expected_problems", []):
            if expected_code in problems_db:
                prob = problems_db[expected_code]
                cat_id = prob.get("category_id", "Unknown")
                cat_name = prob.get("category_name", "Unknown Category")
                prob_name = prob.get("name", "Unknown Problem")
                sev = prob.get("severity", 3)
                
                if cat_id not in category_summary:
                    category_summary[cat_id] = {
                        "name": cat_name,
                        "total": 0,
                        "problems": {}
                    }
                
                category_summary[cat_id]["total"] += 1
                
                if expected_code not in category_summary[cat_id]["problems"]:
                    category_summary[cat_id]["problems"][expected_code] = {
                        "name": prob_name,
                        "severity": sev,
                        "count": 0
                    }
                
                category_summary[cat_id]["problems"][expected_code]["count"] += 1
                
    results["category_summary"] = category_summary

    # Clean up defaultdict for JSON serialization
    results["per_length"] = dict(results["per_length"])
    results["per_severity"] = dict(results["per_severity"])

    _write_progress({
        "status": "running",
        "phase": "aggregating",
        "ground_truth_path": gt_path,
        "taxonomy_path": taxonomy_path,
        "model_type": model_type,
        "completed_case_count": len(polarity_cases),
        "total_case_count": len(polarity_cases),
        "current_case_id": None,
        "current_case_index": len(polarity_cases),
    })

    return results


def format_results_text(results):
    """Format results for terminal output."""
    if "error" in results:
        return f"❌ {results['error']}"

    o = results["overall"]
    lines = [
        "=" * 60,
        "📊 Sentence Polarity (G_neg) Evaluation Results",
        "=" * 60,
        f"Total cases: {o['total_cases']} ({o['n_positive']} positive + {o['n_negated']} negated)",
        "",
        "🎯 Overall Metrics:",
        f"  Accuracy:                 {o['accuracy']:.1%}",
        f"  Negation Detection Rate:  {o['negation_detection_rate']:.1%}",
        f"  False Positive Rate:      {o['false_positive_rate']:.1%}",
        f"  Precision:                {o['precision']:.1%}",
        f"  F1 Score:                 {o['f1_score']:.3f}",
        f"  Mean G_neg (positive):    {o['mean_g_neg_positive']:.3f} (should be ~1.0)",
        f"  Mean G_neg (negated):     {o['mean_g_neg_negated']:.3f} (should be <1.0)",
        "",
        "📏 Per-Length Breakdown:",
    ]

    for length in ["short", "medium", "long"]:
        if length in results.get("per_length_summary", {}):
            s = results["per_length_summary"][length]
            lines.append(f"  {length:8s}: NDR={s['ndr']:.1%}, FPR={s['fpr']:.1%}, "
                         f"G_pos={s['mean_g_pos']:.3f}, G_neg={s['mean_g_neg']:.3f}")

    lines.append("")
    lines.append("⚡ Per-Severity Breakdown:")

    for sev in ["high", "medium", "low"]:
        if sev in results.get("per_severity_summary", {}):
            s = results["per_severity_summary"][sev]
            lines.append(f"  {sev:8s}: NDR={s['ndr']:.1%}, FPR={s['fpr']:.1%}, "
                         f"G_pos={s['mean_g_pos']:.3f}, G_neg={s['mean_g_neg']:.3f}")

    lines.extend(["", "📋 Per-Case Details:"])
    for c in results["per_case"]:
        icon = "✅" if c["correct"] else "❌"
        neg_icon = "🔴" if c["is_negated"] else "🟢"
        lines.append(f"  {icon} {c['case_id']:12s} | {neg_icon} {c['length_category']:6s}/{c['severity_level']:6s} | "
                     f"G_min={c['min_g_neg']:.2f} | detected={c['negation_detected']}")

    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


def format_results_html(results):
    """Format results as HTML for Gradio UI."""
    if "error" in results:
        return f"<div style='color:red;'>❌ {results['error']}</div>"

    o = results["overall"]

    # Accuracy color
    acc_color = "#27AE60" if o["accuracy"] >= 0.8 else "#ffc107" if o["accuracy"] >= 0.6 else "#dc3545"

    # Overall metrics cards
    cards_html = f"""
    <div style='display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; margin-bottom: 16px;'>
        <div style='background: linear-gradient(135deg, {acc_color}, {acc_color}dd); padding: 14px; border-radius: 10px; text-align: center; color: white;'>
            <div style='font-size: 1.8em; font-weight: 700;'>{o['accuracy']:.0%}</div>
            <div style='font-size: 0.8em; opacity: 0.9;'>Accuracy</div>
        </div>
        <div style='background: linear-gradient(135deg, #667eea, #764ba2); padding: 14px; border-radius: 10px; text-align: center; color: white;'>
            <div style='font-size: 1.8em; font-weight: 700;'>{o['negation_detection_rate']:.0%}</div>
            <div style='font-size: 0.8em; opacity: 0.9;'>Detection Rate</div>
        </div>
        <div style='background: linear-gradient(135deg, #28a745, #218838); padding: 14px; border-radius: 10px; text-align: center; color: white;'>
            <div style='font-size: 1.8em; font-weight: 700;'>{o['false_positive_rate']:.0%}</div>
            <div style='font-size: 0.8em; opacity: 0.9;'>False Positive</div>
        </div>
        <div style='background: linear-gradient(135deg, #17a2b8, #138496); padding: 14px; border-radius: 10px; text-align: center; color: white;'>
            <div style='font-size: 1.8em; font-weight: 700;'>{o['f1_score']:.3f}</div>
            <div style='font-size: 0.8em; opacity: 0.9;'>F1 Score</div>
        </div>
    </div>
    """

    # G_neg distribution
    g_pos = o["mean_g_neg_positive"]
    g_neg = o["mean_g_neg_negated"]
    cards_html += f"""
    <div style='display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 16px;'>
        <div style='background:#f0fdf4; padding:12px; border-radius:8px; border-left:4px solid #27AE60;'>
            <div style='font-weight:600; color:#166534; margin-bottom:4px;'>🟢 Mean G_neg (Positive)</div>
            <div style='font-size:1.5em; font-weight:700; color:#27AE60;'>{g_pos:.3f}</div>
            <div style='font-size:0.8em; color:#666;'>Should be ~1.0</div>
        </div>
        <div style='background:#fef2f2; padding:12px; border-radius:8px; border-left:4px solid #dc3545;'>
            <div style='font-weight:600; color:#991b1b; margin-bottom:4px;'>🔴 Mean G_neg (Negated)</div>
            <div style='font-size:1.5em; font-weight:700; color:#dc3545;'>{g_neg:.3f}</div>
            <div style='font-size:0.8em; color:#666;'>Should be &lt;1.0</div>
        </div>
    </div>
    """

    # Per-length table
    length_rows = ""
    for length in ["short", "medium", "long"]:
        s = results.get("per_length_summary", {}).get(length, {})
        if s:
            ndr_color = "#27AE60" if s["ndr"] >= 0.8 else "#ffc107" if s["ndr"] >= 0.5 else "#dc3545"
            fpr_color = "#27AE60" if s["fpr"] <= 0.1 else "#ffc107" if s["fpr"] <= 0.3 else "#dc3545"
            length_label = {"short": "📏 สั้น", "medium": "📐 ปานกลาง", "long": "📏 ยาว"}
            length_rows += f"""
            <tr>
                <td style='padding:8px; font-weight:600;'>{length_label.get(length, length)}</td>
                <td style='text-align:center;'>{s['n_positive']}</td>
                <td style='text-align:center;'>{s['n_negated']}</td>
                <td style='text-align:center; color:{ndr_color}; font-weight:600;'>{s['ndr']:.0%}</td>
                <td style='text-align:center; color:{fpr_color}; font-weight:600;'>{s['fpr']:.0%}</td>
                <td style='text-align:center;'>{s['mean_g_pos']:.3f}</td>
                <td style='text-align:center;'>{s['mean_g_neg']:.3f}</td>
            </tr>
            """

    # Per-severity table
    severity_rows = ""
    for sev in ["high", "medium", "low"]:
        s = results.get("per_severity_summary", {}).get(sev, {})
        if s:
            ndr_color = "#27AE60" if s["ndr"] >= 0.8 else "#ffc107" if s["ndr"] >= 0.5 else "#dc3545"
            fpr_color = "#27AE60" if s["fpr"] <= 0.1 else "#ffc107" if s["fpr"] <= 0.3 else "#dc3545"
            sev_label = {"high": "🔴 รุนแรง", "medium": "🟡 ปานกลาง", "low": "🟢 น้อย"}
            severity_rows += f"""
            <tr>
                <td style='padding:8px; font-weight:600;'>{sev_label.get(sev, sev)}</td>
                <td style='text-align:center;'>{s['n_positive']}</td>
                <td style='text-align:center;'>{s['n_negated']}</td>
                <td style='text-align:center; color:{ndr_color}; font-weight:600;'>{s['ndr']:.0%}</td>
                <td style='text-align:center; color:{fpr_color}; font-weight:600;'>{s['fpr']:.0%}</td>
                <td style='text-align:center;'>{s['mean_g_pos']:.3f}</td>
                <td style='text-align:center;'>{s['mean_g_neg']:.3f}</td>
            </tr>
            """

    table_header = """
    <tr style='background:#667eea; color:white;'>
        <th style='padding:8px;'>Category</th>
        <th style='padding:8px;'>Positive</th>
        <th style='padding:8px;'>Negated</th>
        <th style='padding:8px;'>NDR ↑</th>
        <th style='padding:8px;'>FPR ↓</th>
        <th style='padding:8px;'>G̅_pos</th>
        <th style='padding:8px;'>G̅_neg</th>
    </tr>
    """

    cards_html += f"""
    <div style='margin-bottom: 16px;'>
        <h4 style='color:#333; margin:0 0 8px 0;'>📏 ตามความยาวประโยค</h4>
        <table style='width:100%; border-collapse:collapse; font-size:0.9em; border-radius:8px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.1);'>
            {table_header}
            {length_rows}
        </table>
    </div>

    <div style='margin-bottom: 16px;'>
        <h4 style='color:#333; margin:0 0 8px 0;'>⚡ ตามระดับความรุนแรง</h4>
        <table style='width:100%; border-collapse:collapse; font-size:0.9em; border-radius:8px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.1);'>
            {table_header}
            {severity_rows}
        </table>
    </div>
    """

    # Per-case detail list with dataset transparency
    case_items = ""
    for c in results["per_case"]:
        icon = "✅" if c["correct"] else "❌"
        polarity_badge = "<span style='background:#dc3545; color:white; padding:2px 8px; border-radius:12px; font-size:0.75em; font-weight:bold;'>NEG</span>" if c["is_negated"] else "<span style='background:#27AE60; color:white; padding:2px 8px; border-radius:12px; font-size:0.75em; font-weight:bold;'>AFF</span>"
        len_badge = {"short": "📏", "medium": "📐", "long": "📏📏"}.get(c["length_category"], "")
        g_color = "#dc3545" if c["min_g_neg"] < 0.5 else "#f39c12" if c["min_g_neg"] < 1.0 else "#27AE60"
        
        query_text = c.get("query", "<i>N/A</i>")
        expected = ", ".join(c.get("expected_problems", []))
        if not expected: expected = "None (Control Case)"

        # Get full polarity details for the worst negated code (if any)
        details = {}
        for code, probs in c.get('g_full_details', {}).items():
            if probs.get('gate_neg', 1.0) == c['min_g_neg']:
                details = probs
                break
        if not details and c.get('g_full_details'):
            details = list(c['g_full_details'].values())[0]
            
        g_pol = details.get('gate_total', c['min_g_neg']) if details else c['min_g_neg']
        g_len = details.get('gate_len', 1.0) if details else 1.0
        g_sub = details.get('gate_sub', 1.0) if details else 1.0
        g_n = c['min_g_neg']

        case_items += f"""
        <div style='display:flex; flex-direction:column; padding:12px; background:white; border-radius:8px; margin-bottom:10px; border-left:4px solid {g_color}; box-shadow:0 2px 4px rgba(0,0,0,0.05);'>
            <div style='display:flex; align-items:center; gap:8px; margin-bottom:8px;'>
                <span>{icon}</span>
                <span style='font-weight:700; font-size:0.85em; color:#2c3e50;'>{c['case_id']}</span>
                {polarity_badge}
                <span style='font-size:0.75em; color:#555; background:#ecf0f1; padding:2px 8px; border-radius:6px;'>⚠️ Sev {c['severity_level']}</span>
                <span style='font-size:0.75em; color:#555; background:#ecf0f1; padding:2px 8px; border-radius:6px;'>📐 {c['length_category']}</span>
                <span style='margin-left:auto; font-weight:800; color:{g_color}; font-size:0.95em;'>G_polarity = {g_pol:.3f}</span>
            </div>
            <div style='font-size:0.95em; color:#34495e; margin-bottom:6px; line-height:1.5; font-family:"Athiti", sans-serif;'><b>💬 ข้อความ:</b> "{query_text}"</div>
            <div style='display:flex; justify-content:space-between; align-items:center;'>
                <div style='font-size:0.85em; color:#7f8c8d; font-family:"Courier New", monospace;'><b>🎯 โค้ดปัญหา:</b> {expected}</div>
                <div style='font-size:0.8em; color:#555; background:#f8f9fa; padding:4px 8px; border-radius:6px; border:1px solid #ddd;'>
                    <b>G_neg:</b> {g_n:.2f} &nbsp;|&nbsp; <b>G_len:</b> {g_len:.2f} &nbsp;|&nbsp; <b>G_sub:</b> {g_sub:.2f}
                </div>
            </div>
        </div>
        """

    # Build Problem Distribution Report
    cat_items = ""
    for cat_id, cat_info in sorted(results.get("category_summary", {}).items(), key=lambda x: x[1]['total'], reverse=True):
        sub_items = ""
        for p_code, p_info in cat_info.get("problems", {}).items():
            sub_items += f"""
            <div style='display:flex; justify-content:space-between; margin-left:12px; margin-top:2px; font-size:0.85em; color:#555;'>
                <span>└ {p_code} : {p_info['name']} <span style='font-size:0.8em;'>(Sev {p_info['severity']})</span></span>
                <span style='font-weight:600;'>{p_info['count']}</span>
            </div>
            """
        cat_items += f"""
        <div style='margin-bottom:10px; padding-bottom:10px; border-bottom:1px solid #e0e0e0;'>
            <div style='display:flex; justify-content:space-between; font-weight:600; color:#2c3e50; font-size:0.95em; margin-bottom:4px;'>
                <span>📁 {cat_info['name']}</span>
                <span style='background:#3498db; color:white; padding:2px 6px; border-radius:12px; font-size:0.8em;'>รวม {cat_info['total']} ราย</span>
            </div>
            {sub_items}
        </div>
        """

    cards_html += f"""
    <div style='margin-top: 24px; border-top: 2px dashed #ccc; padding-top: 16px;'>
        <h4 style='color:#2c3e50; margin:0 0 12px 0; font-size:1.1em;'>📋 รายงานความโปร่งใสของชุดข้อมูล (Dataset Transparency)</h4>
        
        <div style='display:flex; gap:16px; flex-wrap:wrap;'>
            <!-- Left Column: Problem Distribution -->
            <div style='flex:1; min-width:300px;'>
                <h5 style='margin:0 0 8px 0; color:#555;'>📊 การกระจายตัวของกลุ่มปัญหา</h5>
                <div style='max-height:500px; overflow-y:auto; background:#ffffff; border-radius:8px; padding:16px; border: 1px solid #dfe6e9; box-shadow:0 1px 3px rgba(0,0,0,0.05);'>
                    {cat_items}
                </div>
            </div>
            
            <!-- Right Column: Case Logs -->
            <div style='flex:2; min-width:400px;'>
                <h5 style='margin:0 0 8px 0; color:#555;'>📄 รายการเคสทดสอบ</h5>
                <div style='max-height:500px; overflow-y:auto; background:#f0f2f5; border-radius:8px; padding:12px; border: 1px solid #dfe6e9;'>
                    {case_items}
                </div>
            </div>
        </div>
    </div>
    """

    return cards_html


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Evaluate G_neg mechanism")
    parser.add_argument("--ground-truth", default="expanded_ground_truth.json")
    parser.add_argument("--taxonomy", default="problem_codes.json")
    parser.add_argument("--output", default=None)
    parser.add_argument("--no-history", action="store_true",
                        help="Do not create a timestamped artifact; only refresh the stable latest file")
    parser.add_argument("--history-limit", type=int, default=2,
                        help="Number of timestamped polarity artifacts to keep after refreshing the stable latest file")
    args = parser.parse_args()

    try:
        results = evaluate_sentence_polarity(args.ground_truth, args.taxonomy)
        print(format_results_text(results))

        # Save JSON results
        serializable = json.loads(json.dumps(results, default=str))
        if args.output:
            output_path = Path(args.output)
        elif args.no_history:
            output_path = None
        else:
            output_path = Path(f"evaluation_results/sentence_polarity_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

        if output_path:
            _write_json(output_path, serializable)
            print(f"\n💾 Results saved to {output_path}")

        _write_json(LATEST_POLARITY_ARTIFACT, serializable)
        print(f"💾 Latest results updated at {LATEST_POLARITY_ARTIFACT}")

        retention = _prune_polarity_history(args.history_limit) if not args.no_history else {
            "kept_history": args.history_limit,
            "removed_files": 0,
            "remaining_files": len(sorted(Path("evaluation_results").glob("sentence_polarity_eval_*.json"))),
        }
        print(
            f"🧹 Polarity artifact retention: kept newest {retention['kept_history']} file(s), "
            f"remaining history={retention['remaining_files']}, removed files={retention['removed_files']}"
        )
        _write_progress({
            "status": "complete",
            "phase": "complete",
            "ground_truth_path": args.ground_truth,
            "taxonomy_path": args.taxonomy,
            "completed_case_count": int(serializable.get("overall", {}).get("total_cases") or 0),
            "total_case_count": int(serializable.get("overall", {}).get("total_cases") or 0),
            "latest_artifact": str(LATEST_POLARITY_ARTIFACT),
            "history_artifact": str(output_path) if output_path else None,
            "history_limit": args.history_limit,
        })
    except Exception as exc:
        _write_progress({
            "status": "error",
            "phase": "failed",
            "ground_truth_path": args.ground_truth,
            "taxonomy_path": args.taxonomy,
            "error": str(exc),
        })
        raise
