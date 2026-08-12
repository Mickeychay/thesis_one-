#!/usr/bin/env python3
"""Export the held-out adversarial cases as a human-readable Thai catalog."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GROUND_TRUTH = ROOT / "data/expanded_ground_truth.json"
TAXONOMY = ROOT / "data/problem_codes.json"
OUTPUT = ROOT / "evaluation_results" / "adversarial_cases_catalog.md"


CHALLENGE_LABELS = {
    "ADV_001": "เหตุการณ์ในอดีต",
    "ADV_002": "คำในข่าว",
    "ADV_003": "บริบทการทำงานเดิม",
    "ADV_004": "เนื้อหาในเกม",
    "ADV_005": "หัวข้อการเรียน",
    "ADV_006": "คำถามคัดกรองและการปฏิเสธ",
    "ADV_007": "คำในข่าว",
    "ADV_008": "ปัญหาของบุคคลอื่น",
    "ADV_009": "สื่อจำลองในการอบรม",
    "ADV_010": "ตัวอย่างในคู่มือ",
    "ADV_011": "การปฏิเสธโดยตรง",
    "ADV_012": "ปัญหาของบุคคลอื่น",
    "ADV_013": "ประวัติของบุคคลอื่น",
    "ADV_014": "ข่าวและบทบาทพยาน",
    "ADV_015": "การปฏิเสธและสาเหตุทางเลือก",
    "ADV_016": "บริบทงานอาสาสมัคร",
    "ADV_017": "ปัญหาของบุคคลอื่น",
    "ADV_018": "โรคของบุคคลอื่น",
    "ADV_019": "โรคของบุคคลอื่น",
    "ADV_020": "เอกสารความรู้และผลตรวจเป็นลบ",
}


def code_label(taxonomy: dict, code: str) -> str:
    info = taxonomy.get(code, {})
    name = info.get("name", "ไม่พบชื่อรหัส") if isinstance(info, dict) else "ไม่พบชื่อรหัส"
    return f"`{code}` {name}"


def main() -> None:
    data = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    taxonomy = json.loads(TAXONOMY.read_text(encoding="utf-8"))
    cases = sorted(
        (
            case
            for case in data["cases"]
            if case.get("augmentation", {}).get("type") == "adversarial"
        ),
        key=lambda case: case["case_id"],
    )

    lines = [
        "# บัญชีเคสท้าทายระบบ (Adversarial Cases)",
        "",
        f"ชุดข้อมูลปัจจุบันมี Adversarial Cases จำนวน {len(cases)} เคส "
        "ทุกเคสอยู่ใน `split=test` และ `evaluation_slice=adversarial_test` ",
        "เคสเหล่านี้จงใจใส่คำที่อาจกระตุ้นรหัสผิด แต่มีบริบทระบุว่าคำนั้นไม่ใช่ปัญหาปัจจุบันของผู้รับบริการ "
        "รหัสที่คาดหวังจึงยึดปัญหาที่มีหลักฐานและต้องการความช่วยเหลือจริง",
        "",
        "> หมายเหตุ: การรายงานผลของบัญชีนี้ต้องอ้างเฉพาะ artifact ที่รันบน test split 95 เคส "
        "และรายงาน Adversarial Cases ทั้ง 20 เคสเป็น stress-test slice แยก ห้ามนำผลจาก artifact ชุดทดสอบ 76 เคสมาใช้แทน",
        "",
        "| เคส | รูปแบบความท้าทาย | ข้อความกรณีศึกษา | รหัสที่ไม่ควรสรุป | รหัสที่คาดหวัง |",
        "|---|---|---|---|---|",
    ]

    for case in cases:
        case_id = case["case_id"]
        augmentation = case["augmentation"]
        false_code = augmentation["false_trigger_code"]
        expected = ", ".join(
            code_label(taxonomy, problem["code"])
            for problem in case["expected_diagnosis"]["problem_list"]
        )
        lines.append(
            f"| `{case_id}` | {CHALLENGE_LABELS.get(case_id, 'บริบทลวง')} | "
            f"{case['case_description']} | {code_label(taxonomy, false_code)} | {expected} |"
        )

    lines.extend(
        [
            "",
            "## เกณฑ์ตรวจรับ",
            "",
            "- รหัสเคสไม่ซ้ำ และข้อความไม่ซ้ำแบบตรงตัว",
            "- รหัสที่คาดหวังและรหัสที่ใช้เป็นกับดักต้องมีอยู่ใน `problem_codes.json`",
            "- รหัสที่คาดหวังต้องมีหลักฐานในข้อความ ส่วนรหัสกับดักต้องถูกลดทอนด้วยบริบท เวลา ประธาน หรือการปฏิเสธ",
            "- ทุกเคสต้องอยู่ในชุดทดสอบแยก และต้องรายงานผลเป็น stress-test slice แยกจากข้อมูลภาคสนาม",
            "",
        ]
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
