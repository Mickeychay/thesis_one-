#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Expert Validation Panel for H2L System
========================================

Standalone Gradio interface for domain experts to validate
H2L system outputs. Calculates Cohen's Kappa for inter-rater
agreement and exports structured results.

Purpose:
    Enable expert validation of H2L outputs to demonstrate
    that expert-elicited parameters produce clinically valid results.
    This is Level 3 validation for thesis methodology.

Workflow:
    1. Load ground truth cases
    2. Run H2L scoring on each case
    3. Present results to expert for validation
    4. Collect ratings (correct / partial / incorrect)
    5. Calculate Cohen's Kappa and agreement statistics

Output:
    expert_ratings.json — raw ratings with timestamps
    expert_report.md   — summary statistics

Usage:
    python expert_validation.py
    python expert_validation.py --max-cases 15
"""

import json
import random
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import gradio as gr

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

RATINGS_FILE = Path("expert_ratings.json")
REPORT_FILE = Path("expert_report.md")


# ============================================================================
# DATA LOADING
# ============================================================================

def load_cases(gt_path: str = "expanded_ground_truth.json",
               max_cases: int = 30, seed: int = 42) -> List[Dict]:
    """Load and randomly sample ground truth cases."""
    with open(gt_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    cases = data.get("cases", [])
    random.seed(seed)
    if len(cases) > max_cases:
        cases = random.sample(cases, max_cases)
    return cases


def load_existing_ratings() -> Dict:
    """Load previously saved ratings."""
    if RATINGS_FILE.exists():
        with open(RATINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"experts": {}, "ratings": []}


def save_ratings(data: Dict):
    """Save ratings to JSON."""
    with open(RATINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================================
# COHEN'S KAPPA CALCULATION
# ============================================================================

def cohens_kappa(ratings1: List[int], ratings2: List[int]) -> float:
    """
    Calculate Cohen's Kappa for two raters.

    Args:
        ratings1: List of ratings from rater 1 (0=incorrect, 1=partial, 2=correct)
        ratings2: List of ratings from rater 2

    Returns:
        Kappa value (-1 to 1)
    """
    assert len(ratings1) == len(ratings2), "Both raters must rate the same cases"
    n = len(ratings1)
    if n == 0:
        return 0.0

    categories = sorted(set(ratings1 + ratings2))
    k = len(categories)

    # Build confusion matrix
    matrix = {}
    for cat in categories:
        matrix[cat] = {c: 0 for c in categories}

    for r1, r2 in zip(ratings1, ratings2):
        matrix[r1][r2] += 1

    # Observed agreement
    p_o = sum(matrix[c][c] for c in categories) / n

    # Expected agreement (by chance)
    p_e = 0
    for c in categories:
        row_total = sum(matrix[c].values()) / n
        col_total = sum(matrix[r][c] for r in categories) / n
        p_e += row_total * col_total

    if p_e >= 1.0:
        return 1.0

    kappa = (p_o - p_e) / (1 - p_e)
    return kappa


def calculate_agreement_with_gt(ratings: List[Dict]) -> Dict:
    """
    Calculate agreement between expert ratings and ground truth.

    Ground truth defines expected problem_list:
    - If GT has problems and expert says "correct" → agreement
    - If GT has no problems and expert says "correct" → agreement
    """
    if not ratings:
        return {"agreement_pct": 0, "n_rated": 0}

    correct_count = sum(1 for r in ratings if r["rating"] == "correct")
    partial_count = sum(1 for r in ratings if r["rating"] == "partial")
    incorrect_count = sum(1 for r in ratings if r["rating"] == "incorrect")
    n = len(ratings)

    # Weighted agreement: correct=1.0, partial=0.5, incorrect=0.0
    weighted = (correct_count * 1.0 + partial_count * 0.5) / n if n > 0 else 0

    return {
        "n_rated": n,
        "correct": correct_count,
        "partial": partial_count,
        "incorrect": incorrect_count,
        "agreement_pct": (correct_count / n * 100) if n > 0 else 0,
        "weighted_agreement": weighted,
    }


# ============================================================================
# GRADIO INTERFACE
# ============================================================================

def create_app(cases: List[Dict]):
    """Create Gradio expert validation interface."""

    ratings_data = load_existing_ratings()
    current_case_idx = [0]

    def get_case_html(idx: int) -> str:
        """Generate HTML for a single case."""
        if idx >= len(cases):
            return "<div style='text-align:center; padding:40px;'><h2>✅ จบการประเมินทั้งหมดแล้ว</h2></div>"

        case = cases[idx]
        case_id = case.get("case_id", f"case_{idx}")
        category = case.get("category", "ไม่ทราบ")
        complexity = case.get("complexity", "ไม่ทราบ")
        query = case.get("case_description", "")

        # Expected diagnosis
        expected = case.get("expected_diagnosis", {})
        problem_list = expected.get("problem_list", [])
        tools = expected.get("recommended_tools", [])

        # Problem cards
        problem_html = ""
        if problem_list:
            for p in problem_list:
                sev = p.get("severity", 1)
                sev_color = "#dc3545" if sev >= 4 else "#ffc107" if sev >= 3 else "#28a745"
                sev_label = "สูง" if sev >= 4 else "ปานกลาง" if sev >= 3 else "ต่ำ"
                problem_html += f"""
                <div style='background:var(--background-fill-primary); border-left:4px solid {sev_color}; padding:10px 14px;
                     border-radius:6px; margin-bottom:6px; box-shadow:0 1px 3px rgba(0,0,0,0.1); border:1px solid var(--border-color-primary);'>
                    <div style='display:flex; justify-content:space-between; align-items:center;'>
                        <span style='font-weight:600;'>{p.get('code', '?')} — {p.get('category', '?')}</span>
                        <span style='background:{sev_color}; color:white; padding:2px 8px;
                               border-radius:12px; font-size:0.75em;'>ความรุนแรง {sev} ({sev_label})</span>
                    </div>
                    <div style='font-size:0.85em; color:var(--body-text-color-subdued); margin-top:4px;'>{p.get('details', '')}</div>
                </div>
                """
        else:
            problem_html = "<div style='color:var(--body-text-color-subdued); padding:10px; text-align:center;'>ไม่พบปัญหาในเคสนี้ (Negative case)</div>"

        tools_html = ", ".join(tools) if tools else "ไม่มี"

        # Is this a polarity test case?
        is_polarity = case_id.startswith("NEG_")
        is_negated = case.get("is_negated", case.get("has_negation", False))
        polarity_badge = ""
        if is_polarity:
            badge_color = "#dc3545" if is_negated else "#28a745"
            badge_text = "NEG (ปฏิเสธ)" if is_negated else "AFF (ยืนยัน)"
            polarity_badge = f"<span style='background:{badge_color}; color:white; padding:2px 8px; border-radius:12px; font-size:0.75em; margin-left:8px;'>{badge_text}</span>"

        return f"""
        <div style='max-width:800px; margin:0 auto;'>
            <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;'>
                <h3 style='margin:0; color:var(--body-text-color);'>เคสที่ {idx + 1}/{len(cases)}</h3>
                <span style='color:var(--body-text-color-subdued);'>ID: {case_id}{polarity_badge}</span>
            </div>

            <div style='display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; margin-bottom:16px;'>
                <div style='background:var(--background-fill-secondary); border:1px solid var(--border-color-primary); border-top:3px solid #667eea; padding:8px 12px; border-radius:8px; text-align:center;'>
                    <div style='font-size:0.75em; color:var(--body-text-color-subdued);'>หมวดหมู่</div>
                    <div style='font-weight:600; font-size:0.9em; color:var(--body-text-color);'>{category}</div>
                </div>
                <div style='background:var(--background-fill-secondary); border:1px solid var(--border-color-primary); border-top:3px solid #28a745; padding:8px 12px; border-radius:8px; text-align:center;'>
                    <div style='font-size:0.75em; color:var(--body-text-color-subdued);'>ความซับซ้อน</div>
                    <div style='font-weight:600; font-size:0.9em; color:var(--body-text-color);'>{complexity}</div>
                </div>
                <div style='background:var(--background-fill-secondary); border:1px solid var(--border-color-primary); border-top:3px solid #dc3545; padding:8px 12px; border-radius:8px; text-align:center;'>
                    <div style='font-size:0.75em; color:var(--body-text-color-subdued);'>ปัญหาที่ตรวจพบ</div>
                    <div style='font-weight:600; font-size:0.9em; color:var(--body-text-color);'>{len(problem_list)} ปัญหา</div>
                </div>
            </div>

            <div style='background:var(--background-fill-secondary); padding:16px; border-radius:10px; margin-bottom:16px;
                 border:1px solid var(--border-color-primary);'>
                <div style='font-weight:600; color:var(--body-text-color); margin-bottom:8px;'>📝 คำอธิบายเคส</div>
                <div style='line-height:1.7; color:var(--body-text-color);'>{query}</div>
            </div>

            <div style='margin-bottom:16px;'>
                <div style='font-weight:600; color:var(--body-text-color); margin-bottom:8px;'>🔍 ผลวินิจฉัย (จากระบบ H2L)</div>
                {problem_html}
            </div>

            <div style='background:var(--background-fill-secondary); border:1px solid var(--border-color-primary); border-left:4px solid #667eea; padding:10px 14px; border-radius:8px; margin-bottom:16px;'>
                <span style='font-weight:600; color:var(--body-text-color);'>🛠 เครื่องมือที่แนะนำ:</span> 
                <span style='color:var(--body-text-color);'>{tools_html}</span>
            </div>
        </div>
        """

    def submit_rating(rating: str, comment: str, expert_name: str) -> Tuple[str, str, str]:
        """Submit a rating and advance to next case."""
        if not expert_name.strip():
            return get_case_html(current_case_idx[0]), "⚠️ กรุณาระบุชื่อผู้เชี่ยวชาญ", ""

        idx = current_case_idx[0]
        if idx >= len(cases):
            return get_case_html(idx), "✅ จบการประเมินแล้ว", ""

        case = cases[idx]
        rating_entry = {
            "case_id": case.get("case_id", f"case_{idx}"),
            "expert_name": expert_name.strip(),
            "rating": rating,
            "comment": comment.strip(),
            "timestamp": datetime.now().isoformat(),
            "case_category": case.get("category", ""),
            "case_complexity": case.get("complexity", ""),
            "n_expected_problems": len(case.get("expected_diagnosis", {}).get("problem_list", [])),
        }

        ratings_data["ratings"].append(rating_entry)
        if expert_name not in ratings_data["experts"]:
            ratings_data["experts"][expert_name] = {"first_rated": datetime.now().isoformat()}
        save_ratings(ratings_data)

        current_case_idx[0] += 1
        status = f"✅ บันทึกเคสที่ {idx + 1} แล้ว ({rating})"

        return get_case_html(current_case_idx[0]), status, ""

    def get_stats_html() -> str:
        """Generate statistics HTML."""
        data = load_existing_ratings()
        all_ratings = data.get("ratings", [])

        if not all_ratings:
            return "<div style='text-align:center; padding:20px; color:#888;'>ยังไม่มีข้อมูลการประเมิน</div>"

        stats = calculate_agreement_with_gt(all_ratings)

        # Per-expert breakdown
        expert_stats = {}
        for r in all_ratings:
            name = r["expert_name"]
            if name not in expert_stats:
                expert_stats[name] = {"correct": 0, "partial": 0, "incorrect": 0, "total": 0}
            expert_stats[name][r["rating"]] += 1
            expert_stats[name]["total"] += 1

        expert_rows = ""
        for name, s in expert_stats.items():
            pct = (s["correct"] / s["total"] * 100) if s["total"] > 0 else 0
            pct_color = "#28a745" if pct >= 80 else "#ffc107" if pct >= 60 else "#dc3545"
            expert_rows += f"""
            <tr>
                <td style='padding:8px; font-weight:600;'>{name}</td>
                <td style='text-align:center;'>{s['total']}</td>
                <td style='text-align:center; color:#28a745;'>{s['correct']}</td>
                <td style='text-align:center; color:#ffc107;'>{s['partial']}</td>
                <td style='text-align:center; color:#dc3545;'>{s['incorrect']}</td>
                <td style='text-align:center; color:{pct_color}; font-weight:700;'>{pct:.0f}%</td>
            </tr>
            """

        # Cohen's Kappa (if 2+ experts rated same cases)
        kappa_html = ""
        expert_names = list(expert_stats.keys())
        if len(expert_names) >= 2:
            # Find common cases between first two experts
            e1_ratings = {r["case_id"]: r["rating"] for r in all_ratings if r["expert_name"] == expert_names[0]}
            e2_ratings = {r["case_id"]: r["rating"] for r in all_ratings if r["expert_name"] == expert_names[1]}
            common = set(e1_ratings.keys()) & set(e2_ratings.keys())

            if len(common) >= 3:
                rating_map = {"correct": 2, "partial": 1, "incorrect": 0}
                r1 = [rating_map[e1_ratings[c]] for c in common]
                r2 = [rating_map[e2_ratings[c]] for c in common]
                kappa = cohens_kappa(r1, r2)
                kappa_color = "#28a745" if kappa >= 0.6 else "#ffc107" if kappa >= 0.4 else "#dc3545"
                kappa_label = "ดีมาก" if kappa >= 0.8 else "ดี" if kappa >= 0.6 else "พอใช้" if kappa >= 0.4 else "ต่ำ"

                kappa_html = f"""
                <div style='background:linear-gradient(135deg, {kappa_color}, {kappa_color}dd);
                     padding:16px; border-radius:10px; text-align:center; color:white; margin-bottom:16px;'>
                    <div style='font-size:0.8em; opacity:0.9;'>Cohen's Kappa ({expert_names[0]} vs {expert_names[1]})</div>
                    <div style='font-size:2em; font-weight:700;'>κ = {kappa:.3f}</div>
                    <div style='font-size:0.9em;'>{kappa_label} ({len(common)} เคสร่วม)</div>
                </div>
                """

        agreement_color = "#28a745" if stats["weighted_agreement"] >= 0.8 else "#ffc107" if stats["weighted_agreement"] >= 0.6 else "#dc3545"

        return f"""
        <div style='max-width:800px; margin:0 auto;'>
            <h3 style='color:var(--body-text-color);'>📊 สรุปผลการประเมินโดยผู้เชี่ยวชาญ</h3>

            <div style='display:grid; grid-template-columns:repeat(4, 1fr); gap:10px; margin-bottom:16px;'>
                <div style='background:linear-gradient(135deg, #667eea, #764ba2); padding:14px;
                     border-radius:10px; text-align:center; color:white;'>
                    <div style='font-size:1.8em; font-weight:700;'>{stats['n_rated']}</div>
                    <div style='font-size:0.8em; opacity:0.9;'>เคสที่ประเมิน</div>
                </div>
                <div style='background:linear-gradient(135deg, #28a745, #218838); padding:14px;
                     border-radius:10px; text-align:center; color:white;'>
                    <div style='font-size:1.8em; font-weight:700;'>{stats['correct']}</div>
                    <div style='font-size:0.8em; opacity:0.9;'>ถูกต้อง</div>
                </div>
                <div style='background:linear-gradient(135deg, #ffc107, #e0a800); padding:14px;
                     border-radius:10px; text-align:center; color:white;'>
                    <div style='font-size:1.8em; font-weight:700;'>{stats['partial']}</div>
                    <div style='font-size:0.8em; opacity:0.9;'>ถูกบางส่วน</div>
                </div>
                <div style='background:linear-gradient(135deg, #dc3545, #c82333); padding:14px;
                     border-radius:10px; text-align:center; color:white;'>
                    <div style='font-size:1.8em; font-weight:700;'>{stats['incorrect']}</div>
                    <div style='font-size:0.8em; opacity:0.9;'>ไม่ถูกต้อง</div>
                </div>
            </div>

            <div style='display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:16px;'>
                <div style='background:var(--background-fill-secondary); border:1px solid var(--border-color-primary); border-left:4px solid #28a745; padding:12px; border-radius:8px;'>
                    <div style='font-weight:600; color:var(--body-text-color-subdued);'>% ถูกต้อง</div>
                    <div style='font-size:1.5em; font-weight:700; color:#28a745;'>{stats['agreement_pct']:.0f}%</div>
                </div>
                <div style='background:var(--background-fill-secondary); border:1px solid var(--border-color-primary); border-left:4px solid {agreement_color}; padding:12px; border-radius:8px;'>
                    <div style='font-weight:600; color:var(--body-text-color-subdued);'>Weighted Agreement</div>
                    <div style='font-size:1.5em; font-weight:700; color:{agreement_color};'>{stats['weighted_agreement']:.3f}</div>
                </div>
            </div>

            {kappa_html}

            <h4 style='color:var(--body-text-color);'>👥 ตามผู้เชี่ยวชาญ</h4>
            <table style='width:100%; border-collapse:collapse; font-size:0.9em;
                   border-radius:8px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.1); border:1px solid var(--border-color-primary);'>
                <tr style='background:var(--background-fill-secondary); color:var(--body-text-color); border-bottom:1px solid var(--border-color-primary);'>
                    <th style='padding:8px;'>ผู้เชี่ยวชาญ</th>
                    <th style='padding:8px;'>ประเมินแล้ว</th>
                    <th style='padding:8px;'>✅ ถูก</th>
                    <th style='padding:8px;'>⚠️ บางส่วน</th>
                    <th style='padding:8px;'>❌ ผิด</th>
                    <th style='padding:8px;'>%ถูก</th>
                </tr>
                {expert_rows}
            </table>
        </div>
        """

    def generate_report() -> str:
        """Generate and save markdown report."""
        data = load_existing_ratings()
        all_ratings = data.get("ratings", [])

        if not all_ratings:
            return "ยังไม่มีข้อมูล"

        stats = calculate_agreement_with_gt(all_ratings)

        report = [
            "# Expert Validation Report",
            f"\n**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"**Total Ratings**: {stats['n_rated']}",
            f"**Experts**: {len(data.get('experts', {}))}",
            "",
            "## Agreement Statistics",
            f"- Correct: {stats['correct']} ({stats['agreement_pct']:.0f}%)",
            f"- Partial: {stats['partial']}",
            f"- Incorrect: {stats['incorrect']}",
            f"- Weighted Agreement: {stats['weighted_agreement']:.3f}",
        ]

        with open(REPORT_FILE, 'w', encoding='utf-8') as f:
            f.write('\n'.join(report))

        return f"✅ รายงานถูกบันทึกที่ {REPORT_FILE}"

    # Build Gradio interface
    with gr.Blocks(
        title="H2L Expert Validation Panel",
        theme=gr.themes.Soft(),
    ) as app:
        gr.Markdown("# 👨‍⚕️ H2L Expert Validation Panel\nระบบประเมินผลลัพธ์โดยผู้เชี่ยวชาญ")

        with gr.Tab("📋 ประเมินเคส"):
            expert_name = gr.Textbox(
                label="ชื่อผู้เชี่ยวชาญ",
                placeholder="เช่น นพ.สมชาย, อ.สมหญิง",
                max_lines=1,
            )
            case_display = gr.HTML(get_case_html(0))
            status_msg = gr.Textbox(label="สถานะ", interactive=False)

            with gr.Row():
                rating = gr.Radio(
                    choices=["correct", "partial", "incorrect"],
                    label="การประเมิน",
                    value="correct",
                    info="correct=ถูกต้อง, partial=ถูกบางส่วน, incorrect=ไม่ถูกต้อง"
                )

            comment = gr.Textbox(
                label="หมายเหตุ (optional)",
                placeholder="เหตุผลที่ให้คะแนนนี้...",
                max_lines=3,
            )

            submit_btn = gr.Button("📨 บันทึกและไปเคสถัดไป", variant="primary", size="lg")
            submit_btn.click(
                submit_rating,
                inputs=[rating, comment, expert_name],
                outputs=[case_display, status_msg, comment],
            )

        with gr.Tab("📊 สถิติ"):
            stats_html = gr.HTML()
            refresh_btn = gr.Button("🔄 รีเฟรช", variant="secondary")
            refresh_btn.click(get_stats_html, outputs=[stats_html])

            report_btn = gr.Button("📝 สร้างรายงาน", variant="primary")
            report_status = gr.Textbox(label="สถานะ", interactive=False)
            report_btn.click(generate_report, outputs=[report_status])

    return app


# ============================================================================
# MAIN
# ============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="H2L Expert Validation Panel")
    parser.add_argument("--max-cases", type=int, default=30,
                        help="Max cases to evaluate (default: 30)")
    parser.add_argument("--gt-path", type=str, default="expanded_ground_truth.json",
                        help="Ground truth file")
    parser.add_argument("--port", type=int, default=7862,
                        help="Port for Gradio server")
    args = parser.parse_args()

    cases = load_cases(args.gt_path, args.max_cases)
    logger.info(f"📦 Loaded {len(cases)} cases for validation")

    app = create_app(cases)
    app.launch(server_port=args.port, share=True)


if __name__ == "__main__":
    main()
