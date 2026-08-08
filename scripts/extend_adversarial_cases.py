#!/usr/bin/env python3
"""Add realistic, held-out adversarial cases to the ground-truth dataset."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GROUND_TRUTH = ROOT / "expanded_ground_truth.json"
TAXONOMY = ROOT / "problem_codes.json"


NEW_CASES = [
    {
        "case_id": "ADV_006",
        "description": "แบบคัดกรองมาตรฐานมีคำถามว่าเคยคิดฆ่าตัวตายหรือไม่ ผู้รับบริการยืนยันว่าไม่เคยคิดและไม่มีอาการดังกล่าว ปัจจุบันมาขอความช่วยเหลือหลังตกงานและต้องการหางานใหม่",
        "trigger_word": "คิดฆ่าตัวตาย",
        "false_code": "X60-X84",
        "expected": [("1201", "ไม่มีงานทำ/ว่างงาน", ["ตกงาน", "ต้องการหางานใหม่"])],
        "category": "สุขภาพจิต",
        "rationale": "screening question and denial are not evidence of self-harm; the current problem is unemployment",
    },
    {
        "case_id": "ADV_007",
        "description": "ผู้รับบริการอ่านข่าวยาเสพติดระบาดในชุมชนจากหนังสือพิมพ์ ไม่ได้ใช้สารเสพติดเอง แต่ขอคำปรึกษาเรื่องกลิ่นและเสียงรบกวนจากโรงงานข้างบ้าน",
        "trigger_word": "ยาเสพติดระบาด",
        "false_code": "1602",
        "expected": [("0804", "สภาพแวดล้อมเป็นพิษ", ["กลิ่น", "เสียงรบกวน", "โรงงานข้างบ้าน"])],
        "category": "ปัญหาครอบครัว",
        "rationale": "a news report mentions drugs, while the client reports an environmental nuisance",
    },
    {
        "case_id": "ADV_008",
        "description": "ผู้รับบริการยืนยันว่าโรคจิตเภทเป็นการวินิจฉัยของพี่ชาย ไม่ใช่ของตนเอง ปัจจุบันโรงงานที่ทำงานปิดกิจการจึงตกงานและมาขอคำปรึกษาเรื่องสิทธิประโยชน์ว่างงาน",
        "trigger_word": "โรคจิต",
        "false_code": "F20-F29",
        "expected": [("1201", "ไม่มีงานทำ/ว่างงาน", ["โรงงานปิดกิจการ", "ตกงาน", "ว่างงาน"])],
        "category": "สุขภาพจิต",
        "rationale": "the psychiatric term describes a former patient, not the client",
    },
    {
        "case_id": "ADV_009",
        "description": "ผู้รับบริการซึ่งเป็นครูใช้คลิปจำลองการทำร้ายร่างกายในการอบรม ไม่ได้เกิดเหตุกับตนเอง แต่กำลังถูกทวงหนี้นอกระบบและค้างชำระหลายเดือน",
        "trigger_word": "การทำร้ายร่างกาย",
        "false_code": "T74",
        "expected": [("1002", "มีหนี้สิน", ["ทวงหนี้นอกระบบ", "ค้างชำระหลายเดือน"])],
        "category": "ครอบครัว/หนี้สิน",
        "rationale": "the violence appears in a training simulation; the client's current problem is debt",
    },
    {
        "case_id": "ADV_010",
        "description": "ผู้รับบริการนำคู่มืออบรมเจ้าหน้าที่ซึ่งยกตัวอย่างการทำร้ายร่างกายมาให้ดู ไม่มีเหตุเกิดกับผู้รับบริการเอง แต่ไม่เข้าใจโรคของบุตรและไม่กินยาตามแพทย์สั่ง",
        "trigger_word": "การทำร้ายร่างกาย",
        "false_code": "T74",
        "expected": [("1401", "ขาดความรู้/ความเข้าใจเกี่ยวกับโรค/การรักษา", ["ไม่เข้าใจโรคของบุตร", "ไม่กินยาตามแพทย์สั่ง"])],
        "category": "ผู้ประสบปัญหาสุขภาพจิตและจิตเวช",
        "rationale": "the trigger is an example in a training manual, not an abuse event; the actual concern is treatment understanding",
    },
    {
        "case_id": "ADV_011",
        "description": "ผู้ดูแลยืนยันว่าไม่ดื่มสุราและไม่มีปัญหาแอลกอฮอล์ ปัจจุบันต้องดูแลมารดาอายุ 86 ปีที่ช่วยเหลือตัวเองไม่ได้เพียงลำพังจนเหนื่อยดูแล",
        "trigger_word": "ดื่มสุรา",
        "false_code": "1601",
        "expected": [("0701", "ภาระดูแลผู้สูงอายุ", ["ดูแลมารดา", "ช่วยเหลือตัวเองไม่ได้", "เหนื่อยดูแล"])],
        "category": "ผู้สูงอายุ",
        "rationale": "the alcohol phrase is explicitly denied; the client reports caregiver burden",
    },
    {
        "case_id": "ADV_012",
        "description": "มารดาพาบุตรเข้ารับการบำบัดยาบ้า ย้ำว่าตนเองไม่ใช้ยาเสพติด แต่ต้องดูแลผู้ป่วยสารเสพติดที่บ้านคนเดียวและเครียดดูแล",
        "trigger_word": "ยาเสพติด",
        "false_code": "1602",
        "expected": [("0702", "ภาระดูแลผู้ป่วยเรื้อรัง/สารเสพติด", ["ดูแลผู้ป่วยสารเสพติด", "ดูแลที่บ้านคนเดียว", "เครียดดูแล"])],
        "category": "ผู้ประสบปัญหายาเสพติด",
        "rationale": "substance use belongs to the child; the client's problem is caring for that person",
    },
    {
        "case_id": "ADV_013",
        "description": "ญาติกล่าวถึงพี่ชายที่เคยมีอาการโรคจิต ไม่ใช่การวินิจฉัยของผู้รับบริการเอง ผู้รับบริการไม่เข้าใจโรคของตนเองและไม่กินยาตามแพทย์สั่ง",
        "trigger_word": "อาการโรคจิต",
        "false_code": "F20-F29",
        "expected": [("1401", "ขาดความรู้/ความเข้าใจเกี่ยวกับโรค/การรักษา", ["ไม่เข้าใจโรค", "ไม่กินยาตามแพทย์สั่ง"])],
        "category": "ผู้ประสบปัญหาสุขภาพจิตและจิตเวช",
        "rationale": "the diagnosis is a relative's history; the client has a treatment-understanding problem",
    },
    {
        "case_id": "ADV_014",
        "description": "ผู้รับบริการอ่านข่าวคดีข่มขืนเพื่อเตรียมให้ปากคำในฐานะพยาน ยืนยันว่าไม่ได้เป็นผู้เสียหาย แต่กำลังขอคำปรึกษาด้านกฎหมายแพ่งเกี่ยวกับข้อพิพาทสัญญาเช่าบ้าน",
        "trigger_word": "ข่มขืน",
        "false_code": "0601",
        "expected": [("1301", "ปัญหากฎหมาย", ["ให้ปากคำ", "กฎหมายแพ่ง", "ข้อพิพาทสัญญาเช่าบ้าน"])],
        "category": "ปัญหาครอบครัว",
        "rationale": "the client is a witness to a news case, not a victim; the current issue is legal advice",
    },
    {
        "case_id": "ADV_015",
        "description": "ผู้ป่วยยืนยันว่าไม่ได้ถูกทำร้ายร่างกาย บาดเจ็บจากรถจักรยานยนต์ล้มเอง และมีค่ารักษาพยาบาลส่วนเกินจ่ายไม่ไหว",
        "trigger_word": "ถูกทำร้ายร่างกาย",
        "false_code": "T74.1",
        "expected": [("1003", "ปัญหาค่าใช้จ่ายในการรักษาพยาบาล", ["ค่ารักษาพยาบาลส่วนเกิน", "จ่ายไม่ไหว"])],
        "category": "ผู้ป่วยโรคเรื้อรังไม่ติดต่อ (NCD)",
        "rationale": "the injury is an accident and violence is denied; the actual issue is treatment cost",
    },
    {
        "case_id": "ADV_016",
        "description": "ผู้รับบริการเข้าร่วมกิจกรรมเตรียมงานสำหรับผู้พ้นโทษในฐานะอาสาสมัคร ไม่เคยต้องโทษ ปัจจุบันไม่มีที่อยู่อาศัยและนอนในที่สาธารณะ",
        "trigger_word": "ผู้พ้นโทษ",
        "false_code": "Z65.1",
        "expected": [("0801", "ไม่มีที่อยู่อาศัย/เร่ร่อน", ["ไม่มีที่อยู่อาศัย", "นอนในที่สาธารณะ"])],
        "category": "คนไร้บ้าน",
        "rationale": "the criminal-justice term describes the volunteer program; the client is homeless",
    },
    {
        "case_id": "ADV_017",
        "description": "มารดาพาบุตรสาวที่ตั้งครรภ์ไม่พร้อมมาพบเจ้าหน้าที่ ยืนยันว่าตนเองไม่ได้ตั้งครรภ์ ปัญหาของมารดาคือค่าพาหนะมารักษาไม่พอ",
        "trigger_word": "ตั้งครรภ์ไม่พร้อม",
        "false_code": "1701",
        "expected": [("1003", "ปัญหาค่าใช้จ่ายในการรักษาพยาบาล", ["ค่าพาหนะมารักษา", "ไม่พอ"])],
        "category": "เด็กและสตรี",
        "rationale": "the pregnancy belongs to the daughter; the client's issue is access cost",
    },
    {
        "case_id": "ADV_018",
        "description": "สามีของผู้รับบริการเป็นมะเร็งปอดและอยู่ระหว่างรักษา แต่ผู้รับบริการไม่มีโรคดังกล่าว ต้องดูแลผู้ป่วยเรื้อรังคนเดียวจนเหนื่อยดูแล",
        "trigger_word": "มะเร็งปอด",
        "false_code": "C34",
        "expected": [("0702", "ภาระดูแลผู้ป่วยเรื้อรัง/สารเสพติด", ["ดูแลผู้ป่วยเรื้อรัง", "ดูแลคนเดียว", "เหนื่อยดูแล"])],
        "category": "ผู้ป่วยโรคเรื้อรังไม่ติดต่อ (NCD)",
        "rationale": "the cancer belongs to the spouse; the client reports caregiver burden",
    },
    {
        "case_id": "ADV_019",
        "description": "ผู้รับบริการช่วยมารดาควบคุมอาหารจากโรคเบาหวาน ไม่ได้เป็นโรคเบาหวานเอง ปัญหาที่มาปรึกษาคือมีหนี้นอกระบบและค้างชำระหลายเดือน",
        "trigger_word": "โรคเบาหวาน",
        "false_code": "E11",
        "expected": [("1002", "มีหนี้สิน", ["หนี้นอกระบบ", "ค้างชำระหลายเดือน"])],
        "category": "ครอบครัว/หนี้สิน",
        "rationale": "the medical condition belongs to the mother; the client has debt",
    },
    {
        "case_id": "ADV_020",
        "description": "ผู้รับบริการอ่านแผ่นพับเรื่องวัณโรคปอดและผลตรวจของตนเองเป็นลบ ไม่ได้ติดเชื้อ ปัจจุบันตกงานหลังนายจ้างปิดกิจการ",
        "trigger_word": "วัณโรคปอด",
        "false_code": "A15",
        "expected": [("1201", "ไม่มีงานทำ/ว่างงาน", ["ตกงาน", "นายจ้างปิดกิจการ"])],
        "category": "ปัญหาการประกอบอาชีพ",
        "rationale": "the leaflet and negative test are not a diagnosis; the current issue is unemployment",
    },
]


def code_type(code: str) -> str:
    return "ICD" if re.match(r"^[A-Za-z]", code) else "SOCIAL"


def taxonomy_info(taxonomy: dict, code: str) -> dict:
    value = taxonomy.get(code)
    if isinstance(value, dict):
        return value
    return {"name": code, "category": code, "keywords": [], "severity": 2}


def problem_entry(taxonomy: dict, code: str, details: str, evidence: list[str]) -> dict:
    info = taxonomy_info(taxonomy, code)
    return {
        "code": code,
        "category": info.get("category", code),
        "severity": int(info.get("severity", 2)),
        "details": details,
        "code_type": code_type(code),
        "_evidence": evidence,
    }


def build_keywords(taxonomy: dict, problems: list[dict]) -> dict:
    result = {}
    for problem in problems:
        code = problem["code"]
        info = taxonomy_info(taxonomy, code)
        candidates = list(info.get("keywords", [])) + [info.get("name", ""), problem["details"]]
        candidates += problem.pop("_evidence", [])
        seen = set()
        result[code] = [item.strip() for item in candidates if item and not (item.strip() in seen or seen.add(item.strip()))]
    return result


def replace_existing(case: dict, description: str, false_code: str, trigger_word: str, expected: list[tuple[str, str, list[str]]], taxonomy: dict) -> None:
    problems = [problem_entry(taxonomy, code, details, evidence) for code, details, evidence in expected]
    case["case_description"] = description
    case["split"] = "test"
    case["evaluation_slice"] = "adversarial_test"
    case["expected_diagnosis"]["problem_list"] = problems
    case["relevant_keywords"] = build_keywords(taxonomy, problems)
    case["augmentation"].update(
        {
            "type": "adversarial",
            "false_trigger_code": false_code,
            "trigger_word": trigger_word,
        }
    )


def create_case(spec: dict, taxonomy: dict) -> dict:
    problems = [problem_entry(taxonomy, code, details, evidence) for code, details, evidence in spec["expected"]]
    return {
        "case_id": spec["case_id"],
        "complexity": "moderate",
        # Keep the held-out slice separate from source-domain stratification;
        # the expected problem code remains the authoritative domain label.
        "category": "adversarial_l2_test",
        "case_description": spec["description"],
        "expected_diagnosis": {
            "problem_list": problems,
            "recommended_tools": [],
            "service_plan": {},
        },
        "relevant_keywords": build_keywords(taxonomy, problems),
        "augmentation": {
            "type": "adversarial",
            "description": spec["rationale"],
            "false_trigger_code": spec["false_code"],
            "trigger_word": spec["trigger_word"],
        },
        "split": "test",
        "evaluation_slice": "adversarial_test",
    }


def main() -> None:
    data = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    taxonomy = json.loads(TAXONOMY.read_text(encoding="utf-8"))
    cases = data["cases"]
    by_id = {case["case_id"]: case for case in cases}

    expected_existing = {"ADV_001", "ADV_002", "ADV_003", "ADV_004", "ADV_005"}
    if not expected_existing.issubset(by_id):
        raise RuntimeError("Expected the five existing ADV cases before extension")
    # Re-running the extension replaces generated IDs so the dataset remains
    # deterministic and never accumulates duplicate adversarial cases.
    new_ids = {spec["case_id"] for spec in NEW_CASES}
    if new_ids.intersection(by_id):
        cases[:] = [case for case in cases if case.get("case_id") not in new_ids]
        by_id = {case["case_id"]: case for case in cases}

    replace_existing(
        by_id["ADV_001"],
        "ผู้ป่วยเล่าว่าเคยคิดฆ่าตัวตายเมื่อสิบปีก่อน แต่ปัจจุบันหายดีและไม่มีความคิดดังกล่าว วันนี้มาร้องเรียนเรื่องค่ารักษาพยาบาลส่วนเกินที่จ่ายไม่ไหว",
        "X60-X84",
        "คิดฆ่าตัวตาย",
        [("1003", "ปัญหาค่าใช้จ่ายในการรักษาพยาบาล", ["ค่ารักษาพยาบาลส่วนเกิน", "จ่ายไม่ไหว"])],
        taxonomy,
    )
    replace_existing(
        by_id["ADV_002"],
        "ผู้รับบริการอ่านข่าวยาเสพติดระบาดในชุมชนจากหนังสือพิมพ์ ไม่ได้ใช้สารเสพติดเอง แต่บุตรหลานขาดเรียนเพราะครอบครัวไม่มีเงินซื้ออุปกรณ์การเรียน จึงขอคำปรึกษาเรื่องสิทธิการศึกษา",
        "1602",
        "ยาเสพติดระบาด",
        [("1104", "ขาดโอกาสทางการศึกษา", ["ขาดเรียน", "ไม่มีเงินซื้ออุปกรณ์การเรียน", "สิทธิการศึกษา"])],
        taxonomy,
    )
    replace_existing(
        by_id["ADV_003"],
        "ผู้รับบริการถูกเลิกจ้างจากงานพยาบาลหลังหน่วยงานปรับลดบุคลากร ในประวัติการทำงานเคยดูแลผู้ป่วยโรคจิต ปัจจุบันไม่มีรายได้และกำลังสมัครงานใหม่",
        "F20-F29",
        "โรคจิต",
        [("1201", "ไม่มีงานทำ/ว่างงาน", ["ถูกเลิกจ้าง", "ไม่มีรายได้", "สมัครงานใหม่"])],
        taxonomy,
    )
    replace_existing(
        by_id["ADV_004"],
        "ผู้ปกครองพบว่าลูกชายเล่นเกมออนไลน์ที่มีฉากการทำร้ายร่างกาย แต่เด็กไม่ได้ทำร้ายใคร ปัญหาคือเล่นจนอดนอนและขาดเรียนบ่อย",
        "T74",
        "การทำร้ายร่างกาย",
        [("1101", "ปัญหาพฤติกรรมไม่สนใจเรียน", ["เล่นจนอดนอน", "ขาดเรียนบ่อย"])],
        taxonomy,
    )
    replace_existing(
        by_id["ADV_005"],
        "ครูให้นักเรียนเขียนเรียงความหัวข้อการทำร้ายร่างกาย ไม่มีเหตุการณ์ทำร้ายเกิดขึ้นกับเด็ก ครอบครัวไม่มีเงินจ่ายค่าเล่าเรียนและค่าอุปกรณ์การเรียน",
        "T74",
        "การทำร้ายร่างกาย",
        [("1001", "ไม่มีรายได้/รายได้ไม่เพียงพอ", ["ไม่มีเงินจ่ายค่าเล่าเรียน", "ความยากจน"]), ("1104", "ขาดโอกาสทางการศึกษา", ["ค่าเล่าเรียน", "ค่าอุปกรณ์การเรียน"])],
        taxonomy,
    )

    cases.extend(create_case(spec, taxonomy) for spec in NEW_CASES)

    for case in cases:
        if case.get("augmentation", {}).get("type") == "adversarial":
            case["split"] = "test"
            case["evaluation_slice"] = "adversarial_test"

    counts = Counter(case.get("complexity", "unknown") for case in cases)
    split_counts = Counter(case.get("split", "missing") for case in cases)
    augmentation_counts = Counter(case.get("augmentation", {}).get("type", "original") for case in cases)
    adversarial_count = augmentation_counts["adversarial"]
    if adversarial_count != 20:
        raise RuntimeError(f"Expected 20 adversarial cases, got {adversarial_count}")

    metadata = data.setdefault("metadata", {})
    metadata.update(
        {
            "total_cases": len(cases),
            "generated_cases": 84,
            "complexity_distribution": dict(counts),
            "augmentation_types": {
                "original": 92,
                "paraphrase": augmentation_counts["paraphrase"],
                "complexity_escalation": augmentation_counts["complexity_escalation"],
                "complexity_reduction": augmentation_counts["complexity_reduction"],
                "adversarial": adversarial_count,
            },
            "last_updated": datetime.now().isoformat(),
            "train_cases": split_counts["train"],
            "test_cases": split_counts["test"],
            "split_ratio": "target 70%/30%; held-out adversarial test slice appended",
            "adversarial_cases_added": 15,
            "adversarial_cases_total": adversarial_count,
            "adversarial_test_slice": "adversarial_test",
            "adversarial_test_cases": adversarial_count,
            "headline_metrics_note": "Existing headline artifacts were generated before the 15-case adversarial extension and must be rerun before reporting updated 95-case test metrics.",
        }
    )

    GROUND_TRUTH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {GROUND_TRUTH}: {len(cases)} cases, train={split_counts['train']}, test={split_counts['test']}, adversarial={adversarial_count}")


if __name__ == "__main__":
    main()
