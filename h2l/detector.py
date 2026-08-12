#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
H2L-Detect V3: Generic Context-Aware Detection
================================================
🎯 ออกแบบให้รองรับปัญหาทางสังคมที่หลากหลาย
🎯 ไม่ Hardcode - ใช้ Context Rules จาก Taxonomy
🎯 แยกแยะ "ใคร" กระทำต่อ "ใคร" ได้อัตโนมัติ

หลักการ:
1. ทุก Problem Code มี "context_actors" ที่ระบุว่าต้องการบริบทอะไร
2. ถ้า keyword match แต่ไม่มี context → ลด confidence + flag L2
3. L2 LLM จะวิเคราะห์ความสัมพันธ์แบบ semantic

ตัวอย่าง Context Rules (จาก category):
- 01: คู่สมรส → ต้องมี ["สามี", "ภรรยา", "คู่สมรส", "แฟน", "สามีภรรยา"]
- 02: พ่อแม่-ลูก → ต้องมี ["พ่อ", "แม่", "บิดา", "มารดา", "ลูก", "บุตร"]
- 03: ครอบครัว → ต้องมี ["ครอบครัว", "พี่น้อง", "ญาติ"]
- X60-X84: ทำร้ายตัวเอง → ต้องมี ["ตัวเอง", "ตนเอง"] หรือไม่มีการระบุผู้อื่น
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, List, Dict, Optional, Tuple, Set
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

REFERENCE_TERMS = [
    "เขา", "เธอ", "รายนี้", "รายดังกล่าว", "รายเดิม",
    "คนนี้", "คนดังกล่าว", "คนเดิม",
]

DOCUMENT_REVIEW_CODES = {"1302", "1304", "1306", "1307"}
DOCUMENT_REVIEW_HINTS = [
    "ตรวจเอกสาร", "เอกสาร", "ทะเบียน", "สัญชาติ", "พาสปอร์ต", "วีซ่า",
    "สิทธิ", "ประกันสังคม", "บัตรทอง", "ใบส่งต่อ", "ขึ้นทะเบียน",
]


def classify_review_status_dict(item: Dict, *, filtered: bool = False, baseline: bool = False) -> Dict:
    code = str(item.get("code") or "")
    confidence = float(item.get("confidence", 0.0) or 0.0)
    detection_level = str(item.get("detection_level") or "")
    context_valid = bool(item.get("context_valid", True))
    reasoning_bits = " ".join(
        str(item.get(field, "") or "")
        for field in ("reasoning", "validation_notes", "polarity_reason")
    ).lower()
    needs_documents = code in DOCUMENT_REVIEW_CODES or any(hint in reasoning_bits for hint in DOCUMENT_REVIEW_HINTS)

    if filtered:
        if needs_documents:
            status = "verify_documents"
            label = "Verify Documents"
            action = "verify_documents"
            note = "ยังไม่ควรสรุปจนกว่าจะตรวจเอกสารหรือสิทธิที่เกี่ยวข้อง"
            tone = "warning"
        elif baseline:
            status = "baseline_filtered"
            label = "Baseline Filtered"
            action = "baseline_preview"
            note = "เป็น candidate จาก baseline preview ที่ยังไม่ควรใช้สรุปเป็นผลยืนยัน"
            tone = "neutral"
        else:
            status = "filtered"
            label = "Filtered"
            action = "discard"
            note = "ระบบลดน้ำหนักหรือคัดออกจากผลลัพธ์สุดท้าย"
            tone = "neutral"
        return {
            **item,
            "review_status": status,
            "review_label": label,
            "review_action": action,
            "review_note": note,
            "review_tone": tone,
        }

    if baseline:
        status = "baseline_candidate"
        label = "Baseline Candidate"
        action = "baseline_preview"
        note = "แสดงเป็น lexical/context preview ของ baseline ยังไม่ถือเป็นผลยืนยัน"
        tone = "neutral"
    elif needs_documents:
        status = "verify_documents"
        label = "Verify Documents"
        action = "verify_documents"
        note = "มีสัญญาณปัญหา แต่ควรยืนยันด้วยเอกสารหรือหลักฐานสิทธิ"
        tone = "warning"
    elif context_valid and confidence >= 0.6 and detection_level in {"L1", "L2"}:
        status = "confirmed"
        label = "Confirmed"
        action = "keep"
        note = "บริบทและความเชื่อมั่นเพียงพอสำหรับสรุปเป็นปัญหาหลัก"
        tone = "live"
    else:
        status = "needs_review"
        label = "Needs Review"
        action = "human_review"
        note = "ควรให้ผู้ใช้หรือผู้เชี่ยวชาญทบทวนบริบทเพิ่มเติม"
        tone = "warning"

    return {
        **item,
        "review_status": status,
        "review_label": label,
        "review_action": action,
        "review_note": note,
        "review_tone": tone,
    }

# =============================================================================
# CONTEXT RULES - Data-Driven, ไม่ Hardcode เฉพาะปัญหาใดปัญหาหนึ่ง
# =============================================================================

# กำหนด Context Actors ตาม Category Prefix
# ระบบจะดูว่า code ขึ้นต้นด้วยอะไร แล้วเช็คว่ามี context words หรือไม่
CATEGORY_CONTEXT_RULES = {
    # หมวด 01: ปัญหาคู่สมรส - ต้องมีการกล่าวถึงคู่สมรส
    "01": {
        "category_name": "ปัญหาคู่สมรสและการครองเรือน",
        "required_actors": ["สามี", "ภรรยา", "คู่สมรส", "แฟน", "สามีภรรยา", "คู่รัก", "แต่งงาน", "สามีตัวเอง", "ภรรยาตัวเอง"],
        "exclude_if_self": True,  # ถ้าเป็นการกระทำต่อตัวเอง ไม่ควร match
    },
    
    # หมวด 02: ปัญหาพ่อแม่-ลูก - ต้องมีการกล่าวถึงครอบครัวสายตรง
    "02": {
        "category_name": "ปัญหาระหว่างบิดา มารดา บุตร",
        "required_actors": ["พ่อ", "แม่", "บิดา", "มารดา", "ลูก", "บุตร", "ลูกชาย", "ลูกสาว", "พ่อเลี้ยง", "แม่เลี้ยง","ผู้ปกครอง"],
        "exclude_if_self": True,
    },
    
    # หมวด 03: ความแตกแยกในครอบครัว
    "03": {
        "category_name": "ปัญหาความแตกแยกในครอบครัว",
        "required_actors": ["ครอบครัว", "บ้านแตก", "หย่า", "แยกกัน", "ทิ้ง"],
        "exclude_if_self": False,
    },
    
    # หมวด 04: เครือญาติ
    "04": {
        "category_name": "ปัญหาความสัมพันธ์ระหว่างเครือญาติ",
        "required_actors": ["ญาติ", "ปู่", "ย่า", "ตา", "ยาย", "ลุง", "ป้า", "น้า", "อา", "พี่", "น้อง", "หลาน"],
        "exclude_if_self": False,
    },
    
    # หมวด F: โรคทางจิตเวช (ICD-10)
    "F": {
        "category_name": "โรคทางจิตเวช (ICD-10)",
        "required_actors": [],
        "exclude_if_other_actor": True,
    },

    # หมวด Z: ปัญหาอื่นๆ (ICD-10)
    "Z": {
        "category_name": "ปัญหาอื่นๆ (ICD-10)",
        "required_actors": [],
        "exclude_if_other_actor": True,
    },
    
    # หมวด 07: ภาระดูแลผู้ป่วย/ผู้สูงอายุ
    "07": {
        "category_name": "ปัญหาภาระในการดูแลผู้เจ็บป่วย/ผู้พิการ/ผู้สูงอายุ",
        "required_actors": ["ผู้ป่วย", "ผู้พิการ", "ผู้สูงอายุ", "ดูแล", "พยาบาล", "เฝ้าไข้"],
        "exclude_if_self": False,
    },
    
    # หมวด 10: การเงิน - ไม่ต้องการ context พิเศษ
    "10": {
        "category_name": "ปัญหาการเงิน",
        "required_actors": [],  # ไม่บังคับ
        "exclude_if_self": False,
    },
    
    # หมวด 11: การศึกษา
    "11": {
        "category_name": "ปัญหาการศึกษา",
        "required_actors": [],  # ไม่บังคับ - "ไม่ไปเรียน" ก็ match ได้
        "exclude_if_self": False,
    },
    
    # หมวด 12: การประกอบอาชีพ
    "12": {
        "category_name": "ปัญหาการประกอบอาชีพ",
        "required_actors": [],
        "exclude_if_self": False,
    },
}

# Context Rules สำหรับ Code เฉพาะที่ต้องการความระวังเป็นพิเศษ
# ใช้สำหรับ codes ที่มี keywords คล้ายกันแต่หมายความต่างกัน
SPECIFIC_CODE_RULES = {
    # X60-X84: ทำร้ายตัวเอง/ฆ่าตัวตาย
    "X60-X84": {
        "requires_self_reference": True,  # ต้องอ้างถึงตัวเอง
        "self_indicators": ["ตัวเอง", "ตนเอง", "ฉัน", "ผม", "ตาย", "ไม่อยากมีชีวิต", "ไม่อยากอยู่"],
        "conflicting_codes": ["0102", "0206", "T74"],  # codes ที่ keywords คล้ายกัน
    },
    
    # T74: ทารุณกรรม - ต้องเป็นการถูกกระทำ
    "T74": {
        "requires_passive": True,  # ต้องเป็น passive voice
        "passive_indicators": ["ถูก", "โดน", "ถูกทำร้าย", "ถูกทารุณ", "ถูกกระทำ"],
        "conflicting_codes": ["X60-X84"],
    },
    
    # F32: ซึมเศร้า
    "F32": {
        "requires_self_reference": True,
        "self_indicators": ["เศร้า", "ซึม", "ท้อแท้", "หมดหวัง", "ไม่มีความสุข"],
        "conflicting_codes": [],
    },

    # F43.2: Adjustment/stress reaction - plain "เครียด" needs functional context
    "F43.2": {
        "requires_distress_context": True,
        "distress_indicators": [
            "เครียด", "ความเครียด", "ภาวะเครียด", "วิตกกังวล", "กังวล",
            "กดดัน", "ปรับตัวไม่ได้", "รับมือไม่ไหว"
        ],
        "impact_indicators": [
            "ไม่อยากไปโรงเรียน", "ไม่อยากไปเรียน", "ไม่อยากเรียน",
            "ไม่อยากทำงาน", "ทำงานไม่ได้", "เรียนไม่ได้", "ไม่อยากออกจากบ้าน",
            "นอนไม่หลับ", "ไม่อยากกินข้าว", "กินข้าวไม่ได้", "ร้องไห้",
            "ไม่มีสมาธิ", "ปวดท้อง", "ปวดหัว"
        ],
        "stressor_indicators": [
            "ดุด่า", "ทำร้าย", "ทารุณ", "ข่มขู่", "ทอดทิ้ง",
            "รังแก", "กลั่นแกล้ง", "ล้อเลียน",
            "โพสต์รูปล้อเลียน", "รายได้น้อย", "ไม่มีรายได้", "หนี้",
            "ตกงาน", "ถูกไล่ออก", "ครอบครัว", "ทะเลาะ", "แฟนทิ้ง",
            "หย่า", "สูญเสีย", "เจ็บป่วย", "ดูแลผู้ป่วย", "คดี"
        ],
        "severity_indicators": ["มาก", "หนัก", "รุนแรง", "สะสม", "จน", "ไม่ไหว", "เป็นประจำ", "บ่อย"],
        "mild_indicators": ["นิดหน่อย", "เล็กน้อย", "ตามปกติ", "ยังทำงานได้", "ยังเรียนได้"],
        "minimum_signal_count": 2,
        "conflicting_codes": [],
    },

    "0501": {
        "requires_romantic_context": True,
        "partner_terms": ["แฟน", "คนรัก", "คู่รัก", "สามี", "ภรรยา"],
        "problem_indicators": ["ผิดหวัง", "อกหัก", "ถูกปฏิเสธ", "ตัดสัมพันธ์", "ถูกหลอก", "เสียใจ"],
        "neutral_indicators": ["รัก", "คบกัน", "มีแฟน"],
    },

    "0502": {
        "requires_romantic_context": True,
        "partner_terms": ["แฟน", "คนรัก", "คู่รัก", "สามี", "ภรรยา"],
        "problem_indicators": ["ทะเลาะ", "ขัดแย้ง", "เลิกกัน", "งอน", "ไม่เข้าใจกัน", "นอกใจ"],
        "neutral_indicators": ["แฟน", "คนรัก"],
    },

    "0506": {
        "requires_romantic_context": True,
        "partner_terms": ["แฟน", "คนรัก", "คู่รัก", "สามี", "ภรรยา", "ชีวิตคู่"],
        "problem_indicators": ["กลัว", "วิตกกังวล", "กังวล", "ไม่มั่นใจ", "ระแวง"],
        "neutral_indicators": ["ชีวิตคู่", "ความรัก"],
    },

    "0703": {
        "requires_caregiver_burden_context": True,
        "prefer_specific_codes": ["0701", "0702", "1405", "1406"],
        "problem_indicators": [
            "ภาระดูแล", "เหนื่อยดูแล", "เครียดดูแล", "ดูแลไม่ไหว", "ไม่มีคนช่วยดูแล",
            "พักผ่อนไม่พอ", "ผู้ดูแลล้า", "รับภาระลำพัง",
        ],
        "neutral_indicators": ["ดูแล", "ช่วยดูแล", "เป็นผู้ดูแล"],
    },

    # 1005: generic money words need real financial-problem context
    "1005": {
        "requires_financial_context": True,
        "prefer_specific_codes": ["1001", "1002", "1003", "1004"],
        "problem_indicators": [
            "หนี้", "หนี้สิน", "หนี้นอกระบบ", "กู้ยืม", "ดอก", "ดอกร้อยละ",
            "ค้างชำระ", "ค้างค่าเช่า", "ค่าเช่า", "ค่าใช้จ่าย", "รายได้ไม่พอ",
            "รายได้ไม่เพียงพอ", "เงินไม่พอ", "ไม่มีเงิน", "ไม่พอจ่าย", "จ่ายไม่ไหว",
            "หมุนเวียน", "นำส่ง", "ยังไม่ได้นำส่ง", "ขาดเงินทุน",
        ],
        "denial_indicators": [
            "ไม่มีปัญหาการเงิน", "ไม่ได้มีปัญหาเรื่องเงิน", "ไม่ติดหนี้",
        ],
    },

    # 1205: neutral occupation mentions must not become an occupation problem
    "1205": {
        "requires_occupation_problem_context": True,
        "prefer_specific_codes": ["1201", "1202", "1203", "1204"],
        "problem_indicators": [
            "ว่างงาน", "ตกงาน", "ไม่มีงาน", "ทำงานไม่ได้", "งานไม่มั่นคง",
            "รายได้ไม่แน่นอน", "ถูกเลิกจ้าง", "ถูกไล่ออก", "เปลี่ยนงานบ่อย",
            "หางาน", "ไม่มีอาชีพ", "อาชีพไม่มั่นคง", "งานหนัก", "ทำงานเสี่ยง",
        ],
        "neutral_indicators": [
            "อาชีพ", "ทำงาน", "รับจ้าง", "ขาย", "เปิดร้าน", "เดิมทำงาน",
        ],
    },

    "1106": {
        "requires_education_problem_context": True,
        "prefer_specific_codes": ["1101", "1102", "1103", "1104", "1105"],
        "problem_indicators": [
            "มีปัญหาการศึกษา", "เรียนไม่ได้", "ไม่อยากไปโรงเรียน", "ขาดเรียน",
            "เรียนไม่จบ", "สอบตก", "ออกจากโรงเรียน", "ไม่มีค่าเทอม", "โดน bully",
        ],
        "neutral_indicators": ["เรียน", "การศึกษา", "จบชั้น", "กำลังเรียน", "เคยเรียน"],
    },

    "0901": {
        "requires_external_relationship_context": True,
        "external_terms": ["เพื่อนบ้าน", "เพื่อนร่วมงาน", "เจ้าของบ้านเช่า", "ผู้พักร่วม", "เพื่อน"],
        "problem_indicators": ["เข้ากับ", "ทะเลาะ", "มีปัญหากับ", "ขัดแย้ง", "ไม่ถูกกัน", "อยู่ร่วมไม่ได้"],
        "neutral_indicators": ["เพื่อนบ้าน", "เพื่อนร่วมงาน", "ผู้พักร่วม"],
    },

    "0902": {
        "requires_external_harm_context": True,
        "external_terms": ["เพื่อนบ้าน", "เพื่อนร่วมงาน", "เพื่อน", "เจ้าของบ้านเช่า", "คนอื่น", "คนนอก"],
        "problem_indicators": ["ข่มขู่", "ดูถูก", "ล้อเลียน", "ใส่ร้าย", "กลั่นแกล้ง", "หลอก", "เอาเปรียบ", "นินทา"],
    },

    "0401": {
        "requires_external_relationship_context": True,
        "external_terms": ["ญาติ", "ญาติพี่น้อง", "วงศ์ญาติ", "พี่", "น้อง", "ลุง", "ป้า", "น้า", "อา", "หลาน"],
        "problem_indicators": ["ไม่เข้าใจกัน", "ทะเลาะ", "ไม่ไว้วางใจ", "แตกร้าว", "ขัดแย้ง"],
        "neutral_indicators": ["ญาติพี่น้อง", "วงศ์ญาติ", "ญาติ"],
    },

    "1102": {
        "requires_education_impairment_context": True,
        "learning_indicators": ["เรียนไม่ทัน", "บกพร่องทางการเรียนรู้", "LD", "มีปัญหาการเรียน", "เรียนช้า"],
        "impairment_indicators": ["สมาธิสั้น", "สติปัญญา", "ปัญหาทางสมอง", "อุบัติเหตุ", "บกพร่อง", "พิการ"],
    },

    "1302": {
        "requires_labor_rights_context": True,
        "issue_indicators": [
            "นายจ้างไม่ส่งประกันสังคม", "ไม่ส่งประกันสังคม", "ถูกปฏิเสธเงินทดแทน",
            "เบิกประกันสังคมไม่ได้", "เคลมไม่ได้", "ค้างค่าแรง", "ไม่จ่ายค่าแรง",
            "ถูกหลอกใช้แรงงาน", "ละเมิดสิทธิแรงงาน",
        ],
        "neutral_indicators": ["ประกันสังคม", "คุ้มครองแรงงาน", "เงินทดแทน"],
    },

    "1304": {
        "requires_healthcare_rights_context": True,
        "issue_indicators": [
            "ใช้สิทธิไม่ได้", "สิทธิขาด", "สิทธิหมด", "ถูกปฏิเสธสิทธิ",
            "ค่ารักษาเกินสิทธิ์", "เบิกไม่ได้", "ไม่มีสิทธิรักษา", "ส่งต่อไม่ได้",
            "ต้องขอใบส่งต่อ", "ขอใบส่งต่อ",
        ],
        "neutral_indicators": ["สิทธิการรักษา", "หลักประกันสุขภาพ", "บัตรทอง", "เบิกจ่ายตรง"],
    },

    # 1306: country names alone are not enough; require migration/legal-status context
    "1306": {
        "requires_migration_context": True,
        "migration_indicators": [
            "ต่างด้าว", "ต่างชาติ", "แรงงานข้ามชาติ", "เข้าเมือง", "หลบหนีเข้าเมือง",
            "ข้ามชาติ", "สัญชาติ", "พาสปอร์ต", "หนังสือเดินทาง", "วีซ่า",
            "เอกสาร", "ทะเบียน", "บัตร", "บัตรต่างด้าว", "ขึ้นทะเบียน",
        ],
        "country_terms": ["เมียนมา", "กัมพูชา", "ลาว"],
        "non_migration_contexts": ["แกง", "อาหาร", "ภาษา", "สำเนียง", "เพลง"],
    },

    "1307": {
        "requires_legal_issue_context": True,
        "prefer_specific_codes": ["1301", "1302", "1303", "1304", "1305", "1306"],
        "issue_indicators": ["คดี", "ฟ้อง", "ฟ้องร้อง", "ถูกจับ", "ดำเนินคดี", "ข้อพิพาท", "ศาล", "หมายเรียก", "ละเมิดสิทธิ"],
        "neutral_indicators": ["กฎหมาย"],
    },

    "Z59": {
        "prefer_specific_codes": ["Z59.0", "0801", "0806", "1001", "1002", "1003"],
    },

    "Z63": {
        "prefer_specific_codes": ["0201", "0202", "0301", "0302", "0401", "0701", "0702", "1405", "1406"],
    },
}

EXACT_DUPLICATE_CODE_GROUPS = [
    {
        "codes": ["0801", "Z59.0"],
        "preferred": "0801",
        "label": "ภาวะไม่มีที่อยู่อาศัย/เร่ร่อน",
    },
]


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class DetectedProblem:
    code: str
    name: str
    category: str
    severity: int
    confidence: float
    detection_level: str  # "L1", "L1-NeedsValidation", "L2"
    reasoning: str
    matched_keywords: List[str] = field(default_factory=list)
    matched_spans: List[Dict] = field(default_factory=list)
    evidence_spans: List[Dict] = field(default_factory=list)
    context_valid: bool = True
    validation_notes: str = ""


# =============================================================================
# L1 DETECTOR - Generic Context-Aware
# =============================================================================

class L1ContextAwareDetector:
    """
    L1 Detector ที่ตรวจสอบ Context โดยอัตโนมัติ
    
    กระบวนการ:
    1. Keyword Matching (เหมือนเดิม)
    2. Context Validation (ใหม่)
       - ดูว่า code อยู่ในหมวดไหน
       - เช็คว่ามี required_actors หรือไม่
       - ถ้าไม่มี → ลด confidence + flag NeedsValidation
    3. Conflict Resolution (ใหม่)
       - ถ้ามี conflicting codes → ให้ L2 ตัดสิน
    """
    
    def __init__(self, taxonomy_path: str = None, taxonomy: Dict = None):
        self.taxonomy = {}
        if taxonomy:
            self.taxonomy = taxonomy
        elif taxonomy_path:
            self._load_taxonomy(taxonomy_path)
        
        # Build keyword index for fast lookup
        self._build_keyword_index()
        
        logger.info(f"✅ [L1-ContextAware] Loaded {len(self.taxonomy)} problem codes")
    
    def _load_taxonomy(self, path_str: str):
        """โหลด Taxonomy จากไฟล์"""
        path = Path(path_str)
        
        # Try multiple locations
        search_paths = [
            path,
            Path(path.name),
            Path("data") / path.name,
            Path("..") / "data" / path.name,
        ]
        
        for p in search_paths:
            if p.exists():
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        self.taxonomy = json.load(f)
                    logger.info(f"✅ Loaded taxonomy from: {p}")
                    return
                except Exception as e:
                    logger.warning(f"Failed to load {p}: {e}")
        
        logger.error(f"❌ Could not load taxonomy from any location")
    
    def _build_keyword_index(self):
        """สร้าง index สำหรับค้นหา keyword เร็วขึ้น + cache lowercased keywords per code"""
        self.keyword_to_codes: Dict[str, List[str]] = {}
        # Cache of lowercased keywords per code to avoid .lower() per detect() call
        self._lowered_keywords: Dict[str, List[str]] = {}
        
        for code, info in self.taxonomy.items():
            keywords = info.get("keywords", [])
            lowered = [kw.lower() for kw in keywords if kw]
            self._lowered_keywords[code] = lowered
            for kw_lower in lowered:
                if kw_lower not in self.keyword_to_codes:
                    self.keyword_to_codes[kw_lower] = []
                self.keyword_to_codes[kw_lower].append(code)

    def _boundary_follow_cues(self) -> Tuple[str, ...]:
        return tuple(sorted({
            *self._actor_lexicon(),
            *REFERENCE_TERMS,
            "ไม่", "ไม่ได้", "ไม่เคย", "ถูก", "โดน",
            "ตี", "ดุด่า", "ทำร้าย", "ทุบตี", "รังแก", "ทอดทิ้ง",
            "ดูแล", "กรีด", "ตัดเอง",
        }, key=len, reverse=True))

    def _scan_boundaries(
        self,
        text_lower: str,
        position: int,
        markers: List[str],
    ) -> Tuple[int, int]:
        left_boundaries = [0]
        right_boundaries = [len(text_lower)]
        guarded_markers = {"และ", "โดย", "ว่า", "ส่วน"}
        follow_cues = self._boundary_follow_cues()

        def marker_is_boundary(found: int, marker: str) -> bool:
            if marker not in guarded_markers:
                return True
            marker_end = found + len(marker)
            prev_window = text_lower[max(0, found - 18):found]
            next_window = text_lower[marker_end:min(len(text_lower), marker_end + 18)]
            if marker == "ว่า":
                return any(cue in prev_window for cue in ("บอก", "ระบุ", "แจ้ง", "เล่า", "ยืนยัน"))
            return any(cue in next_window for cue in follow_cues)

        for marker in markers:
            search_at = 0
            while True:
                found = text_lower.find(marker, search_at)
                if found < 0:
                    break
                marker_end = found + len(marker)
                if not marker_is_boundary(found, marker):
                    search_at = marker_end
                    continue
                if marker_end <= position:
                    left_boundaries.append(marker_end)
                elif found >= position:
                    right_boundaries.append(found)
                search_at = marker_end
        return max(left_boundaries), min(right_boundaries)

    def _find_keyword_occurrences(self, text_lower: str, keywords: List[str]) -> List[Dict[str, int | str]]:
        occurrences: List[Dict[str, int | str]] = []
        for keyword in keywords:
            if not keyword:
                continue
            start = text_lower.find(keyword)
            while start >= 0:
                occurrences.append({
                    "keyword": keyword,
                    "start": start,
                    "end": start + len(keyword),
                })
                start = text_lower.find(keyword, start + len(keyword))
        occurrences.sort(key=lambda item: (int(item["start"]), -(int(item["end"]) - int(item["start"]))))
        filtered: List[Dict[str, int | str]] = []
        for occurrence in occurrences:
            overlaps = any(
                int(occurrence["start"]) < int(existing["end"]) and int(existing["start"]) < int(occurrence["end"])
                for existing in filtered
            )
            if not overlaps:
                filtered.append(occurrence)
        return filtered

    def _coerce_match_spans(
        self,
        text_lower: str,
        matched_keywords: List[str],
        matched_spans: Optional[List[Dict[str, int | str]]] = None,
    ) -> List[Dict[str, int | str]]:
        if matched_spans:
            normalized: List[Dict[str, int | str]] = []
            for span in matched_spans:
                keyword = str(span.get("keyword", "") or "").lower()
                start = int(span.get("start", -1) or -1)
                end = int(span.get("end", -1) or -1)
                if not keyword or start < 0 or end <= start:
                    continue
                normalized.append({
                    "keyword": keyword,
                    "start": start,
                    "end": end,
                    "position_source": str(span.get("position_source", "") or ("user_adjusted" if span.get("user_adjusted") else "provided")),
                    "user_adjusted": bool(span.get("user_adjusted", False) or span.get("position_source") == "user_adjusted"),
                })
            if normalized:
                normalized.sort(key=lambda item: (int(item["start"]), -(int(item["end"]) - int(item["start"]))))
                return normalized
        return self._find_keyword_occurrences(text_lower, matched_keywords)
    
    def _get_category_prefix(self, code: str) -> str:
        """ดึง prefix ของ category (2 ตัวแรก)"""
        # Handle special codes like X60-X84, T74, F32
        if code.startswith(("X", "T", "F", "Z", "C", "I", "G")):
            # If we just want broad categories for F and Z:
            if code.startswith("F"): return "F"
            if code.startswith("Z"): return "Z"
            return code  # Return full code for other special ICD codes
        
        # Normal codes: 0101, 0201, etc.
        return code[:2] if len(code) >= 2 else code
    
    def _check_context_validity(
        self, 
        code: str, 
        text: str, 
        matched_keywords: List[str],
        matched_spans: Optional[List[Dict[str, int | str]]] = None,
    ) -> Tuple[bool, float, str]:
        """
        ตรวจสอบว่า context ถูกต้องหรือไม่ โดยให้เหตุผลที่เป็นมาตรฐานวิชาการ
        
        Returns:
            (is_valid, confidence_multiplier, reason)
        """
        text_lower = text.lower()
        # Lookup taxonomy info for evidence-based reasoning
        code_info = self.taxonomy.get(code, {})
        code_name = code_info.get("name", code)
        code_category = code_info.get("category", "")
        kw_evidence = ", ".join(f"'{k}'" for k in matched_keywords[:3])
        
        # 1. Check specific code rules first
        if code in SPECIFIC_CODE_RULES:
            rule = SPECIFIC_CODE_RULES[code]
            local_contexts = self._keyword_windows(text_lower, matched_keywords, radius=40, matched_spans=matched_spans)
            
            # Check self-reference requirement
            if rule.get("requires_self_reference", False):
                self_indicators = rule.get("self_indicators", [])
                has_self = any(any(ind in context for ind in self_indicators) for context in local_contexts)
                
                # Check if there's NO mention of another person near the matched evidence
                other_person_mentioned = self._has_other_person_mention(local_contexts)
                
                if has_self and not other_person_mentioned:
                    return True, 1.0, f"ตรวจพบการระบุถึงตนเอง (Self-reference) ซึ่งสอดคล้องกับนิยามของ {code_name}"
                elif not has_self:
                    return False, 0.3, f"ไม่พบหลักฐานการอ้างถึงตนเองตามเกณฑ์ของ {code_name} (พบเพียงบริบทบุคคลอื่นหรือบริบททั่วไป)"
            
            # Check passive requirement
            if rule.get("requires_passive", False):
                passive_indicators = rule.get("passive_indicators", [])
                has_passive = any(ind in text_lower for ind in passive_indicators)
                
                if has_passive:
                    return True, 1.0, f"ตรวจพบรูปแบบการถูกกระทำ (Passive voice) สอดคล้องกับเกณฑ์วินิจฉัยของ {code_name}"
                else:
                    return False, 0.4, f"ไม่พบรูปแบบการถูกกระทำ (Passive voice) ซึ่งเป็นเงื่อนไขสำคัญสำหรับรหัส {code_name}"

            # Check distress-context requirement for broad mental-health terms
            if rule.get("requires_distress_context", False):
                return self._check_distress_context(code_name, text_lower, matched_keywords, rule, matched_spans=matched_spans)

            if rule.get("requires_financial_context", False):
                return self._check_financial_context(code_name, text_lower, matched_keywords, rule, matched_spans=matched_spans)

            if rule.get("requires_occupation_problem_context", False):
                return self._check_occupation_context(code_name, text_lower, matched_keywords, rule, matched_spans=matched_spans)

            if rule.get("requires_education_problem_context", False):
                return self._check_education_context(code_name, text_lower, matched_keywords, rule, matched_spans=matched_spans)

            if rule.get("requires_caregiver_burden_context", False):
                return self._check_caregiver_burden_context(code_name, text_lower, matched_keywords, rule, matched_spans=matched_spans)

            if rule.get("requires_external_relationship_context", False):
                return self._check_external_relationship_context(code_name, text_lower, matched_keywords, rule, matched_spans=matched_spans)

            if rule.get("requires_external_harm_context", False):
                return self._check_external_harm_context(code_name, text_lower, matched_keywords, rule, matched_spans=matched_spans)

            if rule.get("requires_romantic_context", False):
                return self._check_romantic_context(code_name, text_lower, matched_keywords, rule, matched_spans=matched_spans)

            if rule.get("requires_education_impairment_context", False):
                return self._check_education_impairment_context(code_name, text_lower, matched_keywords, rule, matched_spans=matched_spans)

            if rule.get("requires_labor_rights_context", False):
                return self._check_issue_context(
                    code_name,
                    text_lower,
                    matched_keywords,
                    rule,
                    matched_spans=matched_spans,
                    positive_label="ข้อพิพาทหรือการถูกปฏิเสธสิทธิแรงงาน/ประกันสังคม",
                    neutral_label="การกล่าวถึงสิทธิแรงงานหรือประกันสังคมทั่วไป",
                )

            if rule.get("requires_healthcare_rights_context", False):
                return self._check_issue_context(
                    code_name,
                    text_lower,
                    matched_keywords,
                    rule,
                    matched_spans=matched_spans,
                    positive_label="ปัญหาการใช้สิทธิรักษาหรือการถูกปฏิเสธสิทธิจริง",
                    neutral_label="การกล่าวถึงสิทธิการรักษาทั่วไป",
                )

            if rule.get("requires_legal_issue_context", False):
                return self._check_issue_context(
                    code_name,
                    text_lower,
                    matched_keywords,
                    rule,
                    matched_spans=matched_spans,
                    positive_label="ข้อพิพาทหรือเหตุทางกฎหมายที่เป็นปัญหาจริง",
                    neutral_label="การกล่าวถึงคำว่ากฎหมายทั่วไป",
                )

            if rule.get("requires_migration_context", False):
                return self._check_migration_context(code_name, text_lower, matched_keywords, rule, matched_spans=matched_spans)
        
        # 2. Check category-level rules
        prefix = self._get_category_prefix(code)
        
        if prefix in CATEGORY_CONTEXT_RULES:
            rule = CATEGORY_CONTEXT_RULES[prefix]
            required_actors = rule.get("required_actors", [])
            local_contexts = self._evidence_segments(text_lower, matched_keywords, matched_spans=matched_spans)
            local_contexts.extend(self._keyword_windows(text_lower, matched_keywords, radius=48, matched_spans=matched_spans))
            
            # 1. Check exclusions first
            if rule.get("exclude_if_self", False):
                if any(self._is_self_action(context) for context in local_contexts):
                    return False, 0.1, f"บริบทระบุว่าเป็นการกระทำต่อตนเอง จึงไม่เข้าเกณฑ์ของกลุ่ม {rule['category_name']}"
            
            if rule.get("exclude_if_other_actor", False) and matched_spans:
                for span in matched_spans:
                    end = int(span["end"])
                    # Look ahead 60 characters for explicit possession by another actor
                    window_after = text_lower[end:end+60]
                    other_possessions = [
                        "ของพี่", "ของน้อง", "ของลูก", "ของสามี", "ของภรรยา", "ของแฟน", 
                        "ของเพื่อน", "ของแม่", "ของพ่อ", "ของปู่", "ของย่า", "ของตา", 
                        "ของยาย", "ของญาติ", "ของหลาน", "ของคนอื่น", "ของเขา", "ของเธอ"
                    ]
                    if any(marker in window_after for marker in other_possessions):
                        return False, 0.4, f"พบคำสำคัญ {kw_evidence} แต่มีบริบทระบุว่าเป็นของบุคคลอื่น ({window_after.strip()[:20]}) ไม่ใช่ของผู้รับบริการ"

            # 2. If no required actors, context is valid based on lexical match (and passed exclusions)
            if not required_actors:
                return True, 1.0, f"ตรวจพบคำสำคัญ {kw_evidence} ซึ่งสอดคล้องกับนิยามในกลุ่ม {code_category}"
            
            # 3. Check if any required actor is mentioned
            found_actors = [
                actor for actor in required_actors
                if any(actor in context for context in local_contexts)
            ]
            
            if found_actors:
                actors_str = ", ".join(f"'{a}'" for a in found_actors[:2])
                return True, 1.0, f"พบบริบทบุคคลที่เกี่ยวข้องใกล้กับหลักฐานคำสำคัญ ({actors_str}) สนับสนุนการวิเคราะห์รหัส {code_name}"
            else:
                return False, 0.4, f"พบคำสำคัญ {kw_evidence} แต่ขาดบริบทบุคคลที่เกี่ยวข้องในช่วงข้อความเดียวกันตามมาตรฐานของ {rule['category_name']}"
        
        # 3. Default: Lexical match with evidence
        return True, 1.0, f"ตรวจพบหลักฐานเชิงประจักษ์จากคำสำคัญ {kw_evidence} ตรงกับเกณฑ์ของ {code_name}"

    def _keyword_windows(
        self,
        text_lower: str,
        matched_keywords: List[str],
        *,
        radius: int = 28,
        matched_spans: Optional[List[Dict[str, int | str]]] = None,
    ) -> List[str]:
        windows: List[str] = []
        for span in self._coerce_match_spans(text_lower, matched_keywords, matched_spans):
            start = int(span["start"])
            end = int(span["end"])
            sentence_left, sentence_right = self._sentence_bounds(text_lower, start)
            clause_left, clause_right = self._clause_bounds(text_lower, start)
            left = max(sentence_left, clause_left, start - radius)
            right = min(sentence_right, clause_right, end + radius)
            windows.append(self._resolve_references_in_span(text_lower, left, right))
        return windows or [text_lower]

    def _sentence_bounds(self, text_lower: str, position: int) -> Tuple[int, int]:
        left = 0
        right = len(text_lower)
        sentence_markers = [".", "。", "!", "?", "\n", ";", "；"]
        for marker in sentence_markers:
            search_at = 0
            while True:
                found = text_lower.find(marker, search_at)
                if found < 0:
                    break
                marker_end = found + len(marker)
                if marker_end <= position:
                    left = max(left, marker_end)
                elif found >= position:
                    right = min(right, found)
                    break
                search_at = marker_end
        return left, right

    def _clause_bounds(self, text_lower: str, position: int) -> Tuple[int, int]:
        boundary_markers = [
            ",", "，", ".", "。", ";", "；", "\n", "(", ")",
            " แต่", " แล้ว", " จึง", " จน", " เพราะ", " เนื่องจาก",
            " อย่างไรก็ตาม", " ขณะเดียวกัน", " ส่วน", " อีกทั้ง", " โดย", " และ", " ว่า", "ว่า",
            "แต่", "แล้ว", "จึง", "จน", "เพราะ", "เนื่องจาก",
            "อย่างไรก็ตาม", "ขณะเดียวกัน", "ส่วน", "อีกทั้ง", "โดย", "และ",
        ]
        return self._scan_boundaries(text_lower, position, boundary_markers)

    def _evidence_segments(
        self,
        text_lower: str,
        matched_keywords: List[str],
        *,
        matched_spans: Optional[List[Dict[str, int | str]]] = None,
    ) -> List[str]:
        segments: List[str] = []
        seen: Set[Tuple[int, int]] = set()
        for span in self._coerce_match_spans(text_lower, matched_keywords, matched_spans):
            start = int(span["start"])
            bounds = self._sentence_bounds(text_lower, start)
            if bounds not in seen:
                seen.add(bounds)
                segment = self._resolve_references_in_span(text_lower, bounds[0], bounds[1]).strip()
                if segment:
                    segments.append(segment)
        return segments or [text_lower]

    def _evidence_span_records(
        self,
        text: str,
        matched_keywords: List[str],
        *,
        matched_spans: Optional[List[Dict[str, int | str]]] = None,
    ) -> List[Dict[str, Any]]:
        text_lower = text.lower()
        spans = self._coerce_match_spans(text_lower, matched_keywords, matched_spans)
        seen: Set[Tuple[str, int, int]] = set()
        records: List[Dict[str, Any]] = []
        for span in spans:
            start = int(span["start"])
            sentence_left, sentence_right = self._sentence_bounds(text_lower, start)
            clause_left, clause_right = self._clause_bounds(text_lower, start)
            for scope, left, right in (
                ("clause", clause_left, clause_right),
                ("sentence", sentence_left, sentence_right),
            ):
                key = (scope, left, right)
                if key in seen:
                    continue
                seen.add(key)
                records.append({
                    "scope": scope,
                    "start": left,
                    "end": right,
                    "text": text[max(0, left):min(len(text), right)].strip(),
                })
        return records

    def _actor_lexicon(self) -> List[str]:
        actors: Set[str] = set()
        for rule in CATEGORY_CONTEXT_RULES.values():
            actors.update(rule.get("required_actors", []))
        for rule in SPECIFIC_CODE_RULES.values():
            actors.update(rule.get("external_terms", []))
            actors.update(rule.get("partner_terms", []))
        actors.update([
            "ผู้ป่วย", "ผู้รับบริการ", "เด็ก", "บุตร", "ลูก", "ลูกชาย", "ลูกสาว",
            "บิดา", "มารดา", "พ่อ", "แม่", "สามี", "ภรรยา", "แฟน", "คู่รัก",
            "พี่ชาย", "พี่สาว", "น้องชาย", "น้องสาว", "พี่", "น้อง",
            "ปู่", "ย่า", "ตา", "ยาย", "ลุง", "ป้า", "น้า", "อา", "หลาน",
            "ญาติ", "เพื่อน", "เพื่อนบ้าน", "เพื่อนร่วมงาน", "นายจ้าง", "เจ้าหนี้", "ผู้ปกครอง",
        ])
        return sorted((actor for actor in actors if actor), key=len, reverse=True)

    def _reference_clause_bounds(self, text_lower: str, position: int) -> Tuple[int, int]:
        boundary_markers = [
            ",", "，", ".", "。", ";", "；", "\n", "(", ")",
            " แต่", " แล้ว", " จึง", " จน", " เพราะ", " เนื่องจาก",
            " อย่างไรก็ตาม", " ขณะเดียวกัน", " ส่วน", " อีกทั้ง", " โดย", " และ", " ว่า", "ว่า",
            "แต่", "แล้ว", "จึง", "จน", "เพราะ", "เนื่องจาก",
            "อย่างไรก็ตาม", "ขณะเดียวกัน", "ส่วน", "อีกทั้ง", "โดย", "และ",
        ]
        return self._scan_boundaries(text_lower, position, boundary_markers)

    def _explicit_actor_mentions_before(self, text_lower: str, position: int) -> List[Dict[str, int | str]]:
        mentions: List[Dict[str, int | str]] = []
        for actor in self._actor_lexicon():
            start = text_lower.find(actor)
            while start >= 0 and start < position:
                end = start + len(actor)
                if end <= position:
                    mentions.append({"actor": actor, "start": start, "end": end})
                start = text_lower.find(actor, start + len(actor))
        mentions.sort(key=lambda item: (int(item["start"]), -(int(item["end"]) - int(item["start"]))))
        return mentions

    def _best_explicit_actor(self, text_lower: str, position: int, *, reference_term: str = "") -> str:
        candidates = self._explicit_actor_mentions_before(text_lower, position)
        if not candidates:
            return ""

        sentence_start, _sentence_end = self._sentence_bounds(text_lower, position)
        clause_start, _clause_end = self._reference_clause_bounds(text_lower, position)
        same_sentence = [item for item in candidates if sentence_start <= int(item["start"]) < position]
        same_clause = [item for item in candidates if clause_start <= int(item["start"]) < position]
        prev_sentence = [
            item for item in candidates
            if int(item["end"]) <= sentence_start and sentence_start - int(item["end"]) <= 180
        ]
        reporting_context = any(
            cue in text_lower[sentence_start:position]
            for cue in ("บอก", "ระบุ", "แจ้ง", "เล่า", "ยืนยัน", "ว่า")
        )
        sentence_subject = same_sentence[0] if same_sentence else None
        deferred_refs = {"รายนี้", "รายดังกล่าว", "รายเดิม", "คนนี้", "คนดังกล่าว", "คนเดิม"}

        best_actor = ""
        best_score = None
        for candidate in candidates:
            distance = max(0, position - int(candidate["end"]))
            score = max(0, 220 - distance)
            if candidate in same_clause:
                score += 160
            elif candidate in same_sentence:
                score += 95
            elif candidate in prev_sentence:
                score += 70
            if reference_term in deferred_refs and candidate in prev_sentence:
                score += 35
            if reporting_context and sentence_subject is not None:
                if candidate is sentence_subject:
                    score += 55
                elif len(same_sentence) > 1 and candidate is same_sentence[-1]:
                    score -= 35
            if best_score is None or score > best_score:
                best_actor = str(candidate["actor"])
                best_score = score
        return best_actor

    def _resolve_references_in_span(self, text_lower: str, start: int, end: int) -> str:
        span_text = text_lower[start:end]
        if not any(term in span_text for term in REFERENCE_TERMS):
            return span_text
        resolved = span_text
        occurrences: List[Tuple[int, int, str]] = []
        for term in sorted(REFERENCE_TERMS, key=len, reverse=True):
            local_start = span_text.find(term)
            while local_start >= 0:
                occurrences.append((start + local_start, start + local_start + len(term), term))
                local_start = span_text.find(term, local_start + len(term))
        for abs_start, abs_end, term in sorted(occurrences, key=lambda item: item[0], reverse=True):
            antecedent = self._best_explicit_actor(text_lower, abs_start, reference_term=term)
            if not antecedent:
                continue
            rel_start = abs_start - start
            rel_end = abs_end - start
            resolved = f"{resolved[:rel_start]}{antecedent}{resolved[rel_end:]}"
        return resolved

    def _cooccurs_in_window(self, windows: List[str], primary_terms: List[str], supporting_terms: List[str]) -> bool:
        return any(
            any(primary in window for primary in primary_terms)
            and any(supporting in window for supporting in supporting_terms)
            for window in windows
        )

    def _check_financial_context(
        self,
        code_name: str,
        text_lower: str,
        matched_keywords: List[str],
        rule: Dict,
        *,
        matched_spans: Optional[List[Dict[str, int | str]]] = None,
    ) -> Tuple[bool, float, str]:
        windows = self._keyword_windows(text_lower, matched_keywords, radius=36, matched_spans=matched_spans)
        segments = self._evidence_segments(text_lower, matched_keywords, matched_spans=matched_spans)
        denial_indicators = rule.get("denial_indicators", [])
        problem_indicators = rule.get("problem_indicators", [])

        if any(indicator in segment for segment in segments for indicator in denial_indicators):
            return False, 0.2, f"ข้อความปฏิเสธปัญหาการเงินโดยตรง จึงยังไม่สนับสนุน {code_name}"

        if any(indicator in window for window in windows for indicator in problem_indicators):
            return True, 0.9, f"พบคำทางการเงินร่วมกับบริบทปัญหาชัดเจน เช่น หนี้/ค้างชำระ/จ่ายไม่ไหว จึงสนับสนุน {code_name}"

        return False, 0.3, f"พบเพียงคำกว้างอย่างเงิน/การเงิน แต่ยังไม่มีบริบทว่ากำลังเป็นปัญหาการเงินโดยตรงสำหรับ {code_name}"

    def _check_occupation_context(
        self,
        code_name: str,
        text_lower: str,
        matched_keywords: List[str],
        rule: Dict,
        *,
        matched_spans: Optional[List[Dict[str, int | str]]] = None,
    ) -> Tuple[bool, float, str]:
        windows = self._keyword_windows(text_lower, matched_keywords, radius=36, matched_spans=matched_spans)
        problem_indicators = rule.get("problem_indicators", [])
        neutral_indicators = rule.get("neutral_indicators", [])

        if any(indicator in window for window in windows for indicator in problem_indicators):
            return True, 0.85, f"พบบริบทการประกอบอาชีพที่เป็นปัญหาจริง เช่น ว่างงาน/ตกงาน/งานไม่มั่นคง จึงสนับสนุน {code_name}"

        if any(indicator in window for window in windows for indicator in neutral_indicators):
            return False, 0.25, f"พบเพียงการเล่าข้อมูลอาชีพหรือการทำงานตามปกติ แต่ยังไม่พบว่าการประกอบอาชีพนั้นเป็นปัญหาโดยตรงสำหรับ {code_name}"

        return False, 0.3, f"ยังไม่พบบริบทว่าประเด็นด้านงานหรืออาชีพเป็นปัญหาโดยตรงสำหรับ {code_name}"

    def _check_education_context(
        self,
        code_name: str,
        text_lower: str,
        matched_keywords: List[str],
        rule: Dict,
        *,
        matched_spans: Optional[List[Dict[str, int | str]]] = None,
    ) -> Tuple[bool, float, str]:
        windows = self._keyword_windows(text_lower, matched_keywords, radius=36, matched_spans=matched_spans)
        problem_indicators = rule.get("problem_indicators", [])
        neutral_indicators = rule.get("neutral_indicators", [])

        if any(indicator in window for window in windows for indicator in problem_indicators):
            return True, 0.85, f"พบบริบทว่าการศึกษาเป็นปัญหาจริง เช่น ขาดเรียน/เรียนไม่ได้/ขาดโอกาส จึงสนับสนุน {code_name}"

        if any(indicator in window for window in windows for indicator in neutral_indicators):
            return False, 0.25, f"พบเพียงการเล่าประวัติการเรียนหรือระดับการศึกษา แต่ยังไม่พบบริบทว่าการศึกษาเป็นปัญหาโดยตรงสำหรับ {code_name}"

        return False, 0.3, f"ยังไม่พบบริบทว่าประเด็นด้านการศึกษาเป็นปัญหาโดยตรงสำหรับ {code_name}"

    def _check_caregiver_burden_context(
        self,
        code_name: str,
        text_lower: str,
        matched_keywords: List[str],
        rule: Dict,
        *,
        matched_spans: Optional[List[Dict[str, int | str]]] = None,
    ) -> Tuple[bool, float, str]:
        windows = self._keyword_windows(text_lower, matched_keywords, radius=40, matched_spans=matched_spans)
        problem_indicators = rule.get("problem_indicators", [])
        neutral_indicators = rule.get("neutral_indicators", [])
        caregiving_terms = ["ดูแล", "ผู้ดูแล", "ช่วยดูแล", "เฝ้าไข้", "พาไปโรงพยาบาล", "ดูแลมารดา", "ดูแลบิดา"]

        if self._cooccurs_in_window(windows, caregiving_terms, problem_indicators):
            return True, 0.9, f"พบบริบทว่าเกิดภาระดูแลจริง เช่น ดูแลไม่ไหว/เหนื่อยดูแล/รับภาระลำพัง จึงสนับสนุน {code_name}"

        if any(indicator in window for window in windows for indicator in neutral_indicators):
            return False, 0.25, f"พบเพียงการกล่าวว่ามีบทบาทดูแล แต่ยังไม่พบว่าการดูแลนั้นกลายเป็นภาระปัญหาโดยตรงสำหรับ {code_name}"

        return False, 0.3, f"ยังไม่พบบริบทภาระดูแลที่ชัดเจนพอสำหรับ {code_name}"

    def _check_external_relationship_context(
        self,
        code_name: str,
        text_lower: str,
        matched_keywords: List[str],
        rule: Dict,
        *,
        matched_spans: Optional[List[Dict[str, int | str]]] = None,
    ) -> Tuple[bool, float, str]:
        windows = self._keyword_windows(text_lower, matched_keywords, radius=40, matched_spans=matched_spans)
        external_terms = rule.get("external_terms", [])
        problem_indicators = rule.get("problem_indicators", [])
        neutral_indicators = rule.get("neutral_indicators", [])

        if self._cooccurs_in_window(windows, external_terms, problem_indicators):
            return True, 0.85, f"พบบุคคลนอกครอบครัวร่วมกับคำที่ชี้ความขัดแย้งหรืออยู่ร่วมไม่ได้ จึงสนับสนุน {code_name}"

        if any(indicator in window for window in windows for indicator in neutral_indicators):
            return False, 0.25, f"พบเพียงการกล่าวถึงบุคคลนอกครอบครัว เช่น เพื่อนบ้าน/เพื่อนร่วมงาน แต่ยังไม่พบว่าความสัมพันธ์นั้นเป็นปัญหาโดยตรงสำหรับ {code_name}"

        return False, 0.3, f"ยังไม่พบบริบทความขัดแย้งกับบุคคลนอกครอบครัวที่ชัดเจนพอสำหรับ {code_name}"

    def _check_external_harm_context(
        self,
        code_name: str,
        text_lower: str,
        matched_keywords: List[str],
        rule: Dict,
        *,
        matched_spans: Optional[List[Dict[str, int | str]]] = None,
    ) -> Tuple[bool, float, str]:
        windows = self._keyword_windows(text_lower, matched_keywords, radius=40, matched_spans=matched_spans)
        external_terms = rule.get("external_terms", [])
        problem_indicators = rule.get("problem_indicators", [])
        if self._cooccurs_in_window(windows, external_terms, problem_indicators):
            return True, 0.88, f"พบบุคคลนอกครอบครัวร่วมกับพฤติกรรมคุกคาม/เอาเปรียบ/ดูหมิ่น จึงสนับสนุน {code_name}"
        return False, 0.3, f"ยังไม่พบบริบทว่าการคุกคามหรือการเอาเปรียบจากคนนอกครอบครัวเกิดขึ้นชัดเจนพอสำหรับ {code_name}"

    def _check_romantic_context(
        self,
        code_name: str,
        text_lower: str,
        matched_keywords: List[str],
        rule: Dict,
        *,
        matched_spans: Optional[List[Dict[str, int | str]]] = None,
    ) -> Tuple[bool, float, str]:
        windows = self._keyword_windows(text_lower, matched_keywords, radius=36, matched_spans=matched_spans)
        partner_terms = rule.get("partner_terms", [])
        problem_indicators = rule.get("problem_indicators", [])
        neutral_indicators = rule.get("neutral_indicators", [])

        if self._cooccurs_in_window(windows, partner_terms, problem_indicators):
            return True, 0.85, f"พบบริบทคู่รัก/ชีวิตคู่ร่วมกับสัญญาณปัญหาความรักโดยตรง จึงสนับสนุน {code_name}"

        if any(indicator in window for window in windows for indicator in neutral_indicators):
            return False, 0.25, f"พบเพียงการกล่าวถึงความรักหรือคู่รักทั่วไป แต่ยังไม่พบบริบทว่าความสัมพันธ์นั้นเป็นปัญหาโดยตรงสำหรับ {code_name}"

        return False, 0.3, f"ยังไม่พบบริบทปัญหาความรักหรือชีวิตคู่ที่ชัดเจนพอสำหรับ {code_name}"

    def _check_education_impairment_context(
        self,
        code_name: str,
        text_lower: str,
        matched_keywords: List[str],
        rule: Dict,
        *,
        matched_spans: Optional[List[Dict[str, int | str]]] = None,
    ) -> Tuple[bool, float, str]:
        windows = self._keyword_windows(text_lower, matched_keywords, radius=36, matched_spans=matched_spans)
        learning_indicators = rule.get("learning_indicators", [])
        impairment_indicators = rule.get("impairment_indicators", [])
        has_local_joint_context = self._cooccurs_in_window(windows, learning_indicators, impairment_indicators)

        if has_local_joint_context:
            return True, 0.88, f"พบบริบทว่าความเจ็บป่วย/ความบกพร่องส่งผลต่อการเรียนโดยตรง จึงสนับสนุน {code_name}"

        return False, 0.25, f"พบคำที่เกี่ยวกับความบกพร่องหรืออุบัติเหตุ แต่ยังไม่พบหลักฐานว่ากระทบการเรียนโดยตรงสำหรับ {code_name}"

    def _check_issue_context(
        self,
        code_name: str,
        text_lower: str,
        matched_keywords: List[str],
        rule: Dict,
        *,
        matched_spans: Optional[List[Dict[str, int | str]]] = None,
        positive_label: str,
        neutral_label: str,
    ) -> Tuple[bool, float, str]:
        windows = self._keyword_windows(text_lower, matched_keywords, radius=40, matched_spans=matched_spans)
        issue_indicators = rule.get("issue_indicators", [])
        neutral_indicators = rule.get("neutral_indicators", [])

        if any(indicator in window for window in windows for indicator in issue_indicators):
            return True, 0.88, f"พบ{positive_label} จึงสนับสนุน {code_name}"

        if any(indicator in window for window in windows for indicator in neutral_indicators):
            return False, 0.25, f"พบเพียง{neutral_label} แต่ยังไม่พบว่ามีข้อพิพาทหรือการถูกปฏิเสธสิทธิโดยตรงสำหรับ {code_name}"

        return False, 0.3, f"ยังไม่พบบริบทข้อพิพาทหรือการใช้สิทธิที่เป็นปัญหาชัดเจนพอสำหรับ {code_name}"

    def _check_migration_context(
        self,
        code_name: str,
        text_lower: str,
        matched_keywords: List[str],
        rule: Dict,
        *,
        matched_spans: Optional[List[Dict[str, int | str]]] = None,
    ) -> Tuple[bool, float, str]:
        windows = self._keyword_windows(text_lower, matched_keywords, radius=24, matched_spans=matched_spans)
        migration_indicators = rule.get("migration_indicators", [])
        country_terms = set(rule.get("country_terms", []))
        non_migration_contexts = rule.get("non_migration_contexts", [])

        if any(indicator in window for window in windows for indicator in migration_indicators):
            return True, 0.9, f"พบคำที่ชี้ถึงสถานะต่างชาติ/เอกสาร/การเข้าเมืองโดยตรง จึงสนับสนุน {code_name}"

        matched_country_only = all(keyword in country_terms for keyword in matched_keywords if keyword)
        if matched_country_only:
            if any(context in window for window in windows for context in non_migration_contexts):
                return False, 0.2, f"พบเพียงชื่อประเทศในบริบทที่ไม่ชี้สถานะการเข้าเมือง เช่น อาหาร/ภาษา จึงยังไม่ควรสรุปเป็น {code_name}; ควรตรวจเอกสารทะเบียน/สัญชาติ"
            return False, 0.28, f"พบเพียงชื่อประเทศหรือสัญชาติ แต่ยังไม่มีข้อเท็จจริงชัดว่ามีสถานะต่างด้าวหรือเข้าเมืองผิดกฎหมาย จึงควรระบุเป็นข้อสงสัยและตรวจเอกสารทะเบียน/สัญชาติก่อน"

        return False, 0.3, f"ยังไม่พบบริบทด้านการเข้าเมืองหรือสถานะเอกสารที่เพียงพอสำหรับ {code_name}"

    def _check_distress_context(
        self,
        code_name: str,
        text_lower: str,
        matched_keywords: List[str],
        rule: Dict,
        *,
        matched_spans: Optional[List[Dict[str, int | str]]] = None,
    ) -> Tuple[bool, float, str]:
        """Validate broad distress terms with intensity, stressor, or daily-life impact."""
        segments = self._evidence_segments(text_lower, matched_keywords, matched_spans=matched_spans)
        distress_terms = rule.get("distress_indicators", [])
        impact_terms = rule.get("impact_indicators", [])
        stressor_terms = rule.get("stressor_indicators", [])
        severity_terms = rule.get("severity_indicators", [])
        mild_terms = rule.get("mild_indicators", [])
        minimum_signal_count = int(rule.get("minimum_signal_count", 2))

        distress_matches = [
            term for term in distress_terms
            if term in matched_keywords or any(term in segment for segment in segments)
        ]
        impact_matches = [term for term in impact_terms if any(term in segment for segment in segments)]
        stressor_matches = [term for term in stressor_terms if any(term in segment for segment in segments)]
        severity_matches = [term for term in severity_terms if any(term in segment for segment in segments)]
        mild_matches = [term for term in mild_terms if any(term in segment for segment in segments)]

        if not distress_matches:
            return False, 0.25, f"ยังไม่พบคำบ่งชี้ความเครียดหรือความกังวลที่สอดคล้องกับ {code_name}"

        signal_count = sum(
            1 for matches in (impact_matches, stressor_matches, severity_matches)
            if matches
        )

        if mild_matches and not impact_matches and not severity_matches:
            mild_text = ", ".join(mild_matches[:2])
            return False, 0.25, f"พบคำบอกความเครียด แต่มีบริบทว่าอาการเล็กน้อยหรือยังใช้ชีวิตได้ตามปกติ ({mild_text})"

        if impact_matches:
            impact_text = ", ".join(impact_matches[:2])
            support_bits = []
            if stressor_matches:
                support_bits.append(f"เหตุเครียด: {', '.join(stressor_matches[:2])}")
            if severity_matches:
                support_bits.append(f"ความรุนแรง: {', '.join(severity_matches[:2])}")
            support_text = f" ร่วมกับ{'; '.join(support_bits)}" if support_bits else ""
            return True, 1.0, f"พบความเครียดที่มีผลต่อชีวิตประจำวัน ({impact_text}){support_text} จึงสนับสนุน {code_name}"

        if signal_count >= minimum_signal_count:
            evidence = []
            if stressor_matches:
                evidence.append(f"เหตุเครียด: {', '.join(stressor_matches[:2])}")
            if severity_matches:
                evidence.append(f"ความรุนแรง: {', '.join(severity_matches[:2])}")
            evidence_text = "; ".join(evidence)
            return True, 0.85, f"พบความเครียดพร้อมบริบทสนับสนุน ({evidence_text}) จึงควรติดตามเป็น {code_name}"

        return False, 0.35, f"พบคำว่าเครียด แต่ยังไม่พบผลกระทบต่อชีวิตประจำวันหรือเหตุเครียดชัดเจนพอสำหรับ {code_name}"

    def _calculate_confidence(
        self,
        text_lower: str,
        matched_keywords: List[str],
        all_keywords: List[str],
        confidence_multiplier: float,
    ) -> float:
        """Calculate a differentiated confidence score from match strength.

        The old score used only the number of matched keywords, so many
        one-keyword matches landed on the exact same confidence. This keeps the
        score deterministic while adding evidence quality: keyword specificity,
        taxonomy coverage, and repeated mentions in the case text.
        """
        unique_matches = list(dict.fromkeys(matched_keywords))
        if not unique_matches:
            return 0.0

        match_count_score = min(0.24, 0.10 * len(unique_matches))
        coverage = len(unique_matches) / max(len(all_keywords), 1)
        coverage_score = min(0.10, coverage * 0.18)
        avg_keyword_length = sum(len(keyword) for keyword in unique_matches) / len(unique_matches)
        specificity_score = min(0.12, (avg_keyword_length / 24) * 0.12)
        phrase_bonus = 0.04 if any(len(keyword) >= 10 or " " in keyword for keyword in unique_matches) else 0.0
        occurrences = sum(text_lower.count(keyword) for keyword in unique_matches)
        repetition_score = min(0.06, max(0, occurrences - len(unique_matches)) * 0.03)

        raw_confidence = (
            0.50
            + match_count_score
            + coverage_score
            + specificity_score
            + phrase_bonus
            + repetition_score
        )
        final_confidence = raw_confidence * confidence_multiplier
        return round(max(0.05, min(0.95, final_confidence)), 4)
    
    def _has_other_person_mention(self, text: Any) -> bool:
        """ตรวจสอบว่ามีการกล่าวถึงบุคคลอื่นหรือไม่"""
        other_person_words = [
            "สามี", "ภรรยา", "แฟน", "พ่อ", "แม่", "ลูก", 
            "พี่", "น้อง", "เพื่อน", "คนอื่น", "ใคร" ,"เขา", "ญาติ","กิ๊ก","ชู้" , "หลาน", "ปู่ย่าตายาย", "คุณครู", "ครู", "ครูฝึก", "ครูฝึกสอน","นายจ้าง","ลูกจ้าง","เพื่อนบ้าน","เพื่อนร่วมงาน","เพื่อนสมัยเรียน"
        ]
        if isinstance(text, list):
            return any(any(word in segment for word in other_person_words) for segment in text if isinstance(segment, str))
        return any(word in str(text) for word in other_person_words)
    
    def _is_self_action(self, text: str) -> bool:
        """ตรวจสอบว่าเป็นการกระทำต่อตัวเองหรือไม่"""
        self_patterns = [
            "ตัวเอง", "ตนเอง", "ร่างกายตัวเอง", 
            "ทำร้ายตัวเอง", "ทำร้ายร่างกายตัวเอง",
            "ฆ่าตัวตาย", "ไม่อยากมีชีวิต", "ไม่อยากอยู่",
            "แอบทำ", "กรีดข้อมือ", "เจ็บตัวเอง" , "กรีดข้อมือตัวเอง"
        ]
        return any(pattern in text for pattern in self_patterns)
    
    def _find_conflicting_codes(self, detected_codes: Set[str]) -> Dict[str, List[str]]:
        """หา codes ที่ conflict กัน"""
        conflicts = {}
        
        for code in detected_codes:
            if code in SPECIFIC_CODE_RULES:
                conflicting = SPECIFIC_CODE_RULES[code].get("conflicting_codes", [])
                overlaps = [c for c in conflicting if c in detected_codes]
                if overlaps:
                    conflicts[code] = overlaps
        
        return conflicts

    def _downgrade_generic_codes(
        self,
        results: List[DetectedProblem]
    ) -> List[DetectedProblem]:
        present_codes = {problem.code for problem in results}
        for problem in results:
            rule = SPECIFIC_CODE_RULES.get(problem.code, {})
            preferred = rule.get("prefer_specific_codes", [])
            overlapping = [code for code in preferred if code in present_codes]
            if not overlapping:
                continue
            problem.context_valid = False
            problem.detection_level = "L1-NeedsValidation"
            problem.confidence = min(problem.confidence, 0.24)
            problem.reasoning = (
                f"พบรหัสเฉพาะกว่าในหมวดเดียวกันแล้ว ({', '.join(overlapping[:3])}) "
                f"จึงลดน้ำหนัก {problem.name} เพื่อหลีกเลี่ยงการสรุปซ้ำแบบรหัสอื่นๆ"
            )
            problem.validation_notes = problem.reasoning
        return results

    def _dedupe_exact_issue_codes(
        self,
        results: List[DetectedProblem],
    ) -> Tuple[List[DetectedProblem], List[DetectedProblem]]:
        kept_results = list(results)
        removed_results: List[DetectedProblem] = []

        for group in EXACT_DUPLICATE_CODE_GROUPS:
            group_codes = set(group.get("codes", []))
            present = [problem for problem in kept_results if problem.code in group_codes]
            if len(present) <= 1:
                continue

            preferred_code = group.get("preferred", "")
            chosen = next((problem for problem in present if problem.code == preferred_code), None)
            if chosen is None:
                chosen = max(present, key=lambda problem: (problem.confidence, problem.severity, problem.code))

            survivors: List[DetectedProblem] = []
            for problem in kept_results:
                if problem.code not in group_codes or problem.code == chosen.code:
                    survivors.append(problem)
                    continue

                problem.context_valid = False
                problem.detection_level = "L1-NeedsValidation"
                problem.confidence = min(problem.confidence, 0.24)
                problem.reasoning = (
                    f"พบรหัสที่สื่อประเด็นเดียวกันอยู่แล้ว ({chosen.code} {chosen.name}) "
                    f"จึงลดน้ำหนัก {problem.code} {problem.name} เพื่อหลีกเลี่ยงการสรุปซ้ำของ {group.get('label', 'ประเด็นเดียวกัน')}"
                )
                problem.validation_notes = problem.reasoning
                removed_results.append(problem)

            kept_results = survivors

        return kept_results, removed_results
    
    def detect(self, text: str) -> Tuple[List[DetectedProblem], Dict]:
        """
        ตรวจจับปัญหาพร้อม Context Validation
        
        Returns:
            (problems, metadata)
            metadata includes: conflicts, needs_l2_codes, etc.
        """
        if not text or not self.taxonomy:
            return [], {}
        
        text_lower = text.lower()
        results = []
        detected_codes = set()
        needs_l2_codes = []
        
        # Phase 1: Keyword Matching
        for code, info in self.taxonomy.items():
            # Use cached lowered keywords (optimization 7)
            lowered_kws = self._lowered_keywords.get(code, [])
            if not lowered_kws:
                continue
            
            matched = [kw for kw in lowered_kws if kw in text_lower]
            matched_spans = self._find_keyword_occurrences(text_lower, matched)
            
            if matched:
                detected_codes.add(code)
                evidence_spans = self._evidence_span_records(text, matched, matched_spans=matched_spans)
                
                # Phase 2: Context Validation
                is_valid, conf_mult, reason = self._check_context_validity(
                    code, text, matched, matched_spans=matched_spans
                )
                
                final_confidence = self._calculate_confidence(
                    text_lower=text_lower,
                    matched_keywords=matched,
                    all_keywords=lowered_kws,
                    confidence_multiplier=conf_mult,
                )
                
                # Determine detection level
                if is_valid and conf_mult >= 0.8:
                    detection_level = "L1"
                else:
                    detection_level = "L1-NeedsValidation"
                    needs_l2_codes.append(code)
                
                results.append(DetectedProblem(
                    code=code,
                    name=info.get("name", code),
                    category=info.get("category", "General"),
                    severity=info.get("severity", 1),
                    confidence=final_confidence,
                    detection_level=detection_level,
                    reasoning=reason,
                    matched_keywords=matched,
                    matched_spans=[dict(span) for span in matched_spans],
                    evidence_spans=evidence_spans,
                    context_valid=is_valid,
                    validation_notes=reason if not is_valid else ""
                ))
        
        # Phase 3: Find Conflicts
        conflicts = self._find_conflicting_codes(detected_codes)
        
        # Mark conflicting codes for L2 validation
        for code, conflict_list in conflicts.items():
            for result in results:
                if result.code == code or result.code in conflict_list:
                    if result.detection_level == "L1":
                        result.detection_level = "L1-NeedsValidation"
                        result.validation_notes = f"Conflict with: {conflict_list}"
                        if result.code not in needs_l2_codes:
                            needs_l2_codes.append(result.code)
        
        # Sort by severity and confidence
        results.sort(key=lambda x: (x.severity, x.confidence), reverse=True)

        # Phase 3.5: downgrade broad "other" codes when a more specific sibling is present
        results = self._downgrade_generic_codes(results)

        # Phase 3.6: collapse exact duplicate codes that describe the same issue
        results, dedup_filtered_out = self._dedupe_exact_issue_codes(results)

        # Phase 4: Pre-filter strongly invalid context matches
        # Items with context_valid=False AND very low confidence are removed at L1
        # This ensures filtering happens even when L2 is not available
        pre_filtered = []
        l1_filtered_out = []
        for r in results:
            if not r.context_valid and r.confidence < 0.3:
                logger.info(f"  🚫 L1-Filtered: [{r.code}] {r.name} (conf={r.confidence:.0%}, reason={r.reasoning})")
                l1_filtered_out.append(r)
                continue
            pre_filtered.append(r)
        results = pre_filtered
        
        metadata = {
            "total_detected": len(results),
            "needs_l2_validation": needs_l2_codes,
            "conflicts": conflicts,
            "has_conflicts": len(conflicts) > 0,
            "l1_filtered_out": l1_filtered_out + dedup_filtered_out
        }
        
        return results, metadata
    
    def get_taxonomy(self) -> Dict:
        return self.taxonomy


# =============================================================================
# L2 DETECTOR - LLM-based Semantic Analysis
# =============================================================================

class L2SemanticDetector:
    """
    L2 Detector ที่ใช้ LLM วิเคราะห์ความหมายเชิง semantic
    
    ใช้สำหรับ:
    1. Validate L1 candidates ที่ needs_validation
    2. ค้นหาปัญหาซ่อนเร้น (implicit)
    3. แก้ conflict ระหว่าง codes
    """
    
    # System Prompt ที่เป็น Generic - ไม่ Hardcode เฉพาะปัญหา
    SYSTEM_PROMPT = """You are an expert social worker specialized in analyzing social problems.
You MUST respond in Thai language. Never use Chinese. Use Thai for all text fields.

Your tasks:
1. Validate whether the problem codes detected by the system are correct
2. Analyze context: WHO did WHAT to WHOM
3. Find hidden/implicit problems that keyword matching missed
4. Extract the patient's demographic / age group from the context

Analysis principles:
- If the action is toward "oneself" → should NOT be family problem (01, 02)
- If mentioning "husband/wife/spouse" → may be spousal problem (01)
- If mentioning "father/mother/child" → may be family problem (02)
- If no relationship specified → infer from overall context
- Infer demographic group from terms like "อนุบาล/เด็ก/ลูก" (child), "วัยรุ่น/มัธยม" (teen), "ทำงาน" (adult), "คนแก่/ชรา/เกษียณ/ปู่ยา" (elderly). If unknown, output "general".

⚠️ CRITICAL SAFETY RULES (must follow strictly):
- 🛑 NEGATION RULE: If the text explicitly DENIES or NEGATES a problem (e.g., "ปฏิเสธการทำร้ายตัวเอง", "ไม่ได้คิดฆ่าตัวตาย", "ไม่เคยถูกทำร้าย"), you MUST set `is_valid: false` for that code and explain that the patient denied it. Do not validate a problem if the patient explicitly denies it.
- NEVER invalidate crisis-level codes (X60-X84 self-harm/suicide, T74 abuse, F32-F33 depression)
  when there is ANY POSITIVE textual evidence in the case, even if indirect
- For crisis codes: ALWAYS set is_valid=true if keywords matched AND not negated. Prefer false positive over false negative
- Self-harm disambiguation: "ทำร้ายตัวเอง/ทำร้ายร่างกายตัวเอง" = X60-X84, NOT T74
- "ไม่อยากมีชีวิต/ไม่อยากอยู่" = suicidal ideation → X60-X84 is_valid=true
- When X60-X84 and T74 conflict: if text mentions "ตัวเอง" → X60-X84 is valid, T74 may be invalid
- You should ADD implicit problems generously for crisis cases, not filter them out

Output Format (JSON only):
{
  "validated_codes": [
    {"code": "code_id", "is_valid": true/false, "reason": "เหตุผลเป็นภาษาไทย"}
  ],
  "implicit_problems": [
    {
      "code": "code_id",
      "name": "ชื่อปัญหาเป็นภาษาไทย",
      "category": "หมวดหมู่",
      "severity": 1-5,
      "confidence": 0.0-1.0,
      "reasoning": "เหตุผลสั้นๆ เป็นภาษาไทย",
      "evidence": "ข้อความจากเคส"
    }
  ],
  "context_analysis": {
    "primary_actor": "ผู้กระทำ",
    "target": "ผู้ถูกกระทำ",
    "relationship": "ความสัมพันธ์",
    "demographic_group": "child|teen|adult|elderly|general",
    "has_crisis": true/false
  }
}"""

    def __init__(self, config=None):
        self.config = config
        self.client = None
        self.model = "qwen2.5:7b"
        self.is_ready = False
        self._setup_llm()
    
    def _setup_llm(self):
        """Setup LLM client"""
        try:
            from openai import OpenAI
            
            base_url = "http://localhost:11434/v1"
            api_key = "ollama"
            
            if self.config:
                if getattr(self.config, 'USE_LOCAL_LLM', True):
                    base_url = getattr(self.config, 'LOCAL_LLM_BASE_URL', base_url)
                    self.model = getattr(self.config, 'LOCAL_LLM_MODEL', self.model)
                else:
                    base_url = "https://openrouter.ai/api/v1"
                    self.model = getattr(self.config, 'OPENROUTER_MODEL', 'openai/gpt-4o-mini')
                    api_key = getattr(self.config, 'OPENROUTER_API_KEY', '')
            
            self.client = OpenAI(base_url=base_url, api_key=api_key)
            self.is_ready = True
            logger.info(f"✅ [L2-Semantic] Ready with model: {self.model}")
            
        except ImportError:
            logger.warning("⚠️ OpenAI library not available")
            self.is_ready = False
        except Exception as e:
            logger.error(f"❌ Failed to setup L2: {e}")
            self.is_ready = False
    
    def validate_and_detect(
        self, 
        text: str, 
        l1_candidates: List[DetectedProblem],
        needs_validation: List[str],
        conflicts: Dict[str, List[str]],
        taxonomy: Dict = None,
        model: Optional[str] = None,
    ) -> Tuple[List[DetectedProblem], List[DetectedProblem], Dict]:
        """
        Validate L1 candidates และค้นหา implicit problems
        
        Returns:
            (validated_problems, implicit_problems, context_analysis)
        """
        if not self.is_ready:
            logger.warning("⚠️ L2 not ready, returning L1 as-is")
            return l1_candidates, [], {}
        
        # Build prompt with L1 context
        l1_info = self._format_l1_context(l1_candidates, needs_validation, conflicts)
        
        try:
            selected_model = model or self.model
            messages = [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": f"Case: \"{text}\"\n\n{l1_info}"},
            ]
            request_options = {
                "model": selected_model,
                "messages": messages,
                "temperature": 0.2,
                "seed": 42,
                "max_tokens": (
                    getattr(self.config, "LLM_MAX_TOKENS", 2048)
                    if self.config
                    else 2048
                ),
                "response_format": {"type": "json_object"},
            }
            response = self.client.chat.completions.create(**request_options)
            response_content = response.choices[0].message.content
            data = self._parse_json(response_content)

            shape_errors = self._payload_shape_errors(data)
            if shape_errors:
                logger.warning(
                    "Malformed L2 response schema (%s); retrying once with corrective instructions",
                    ", ".join(shape_errors),
                )
                corrective_messages = messages + [
                    {"role": "assistant", "content": response_content or ""},
                    {
                        "role": "user",
                        "content": (
                            "The previous response was malformed. Return one complete JSON object only. "
                            "validated_codes and implicit_problems must be arrays of objects; "
                            "context_analysis must be an object. Do not use prose fragments or omit fields."
                        ),
                    },
                ]
                retry_options = dict(request_options)
                retry_options.update({
                    "messages": corrective_messages,
                    "temperature": 0,
                    "seed": 43,
                })
                response = self.client.chat.completions.create(**retry_options)
                data = self._parse_json(response.choices[0].message.content)
                shape_errors = self._payload_shape_errors(data)

            if shape_errors:
                logger.error(
                    "L2 response schema remains malformed after retry: %s",
                    ", ".join(shape_errors),
                )
                return l1_candidates, [], {}
            
            validation_data = self._dict_items(
                data.get("validated_codes", []), "validated_codes"
            )
            implicit_data = self._dict_items(
                data.get("implicit_problems", []), "implicit_problems"
            )

            # Process validation results
            validated = self._process_validation(
                l1_candidates,
                validation_data,
                validation_targets=set(needs_validation or []),
            )

            # Process implicit problems
            implicit = self._process_implicit(
                implicit_data,
                l1_candidates,
                full_text=text,
                taxonomy=taxonomy,
            )
            
            # Get context analysis
            context = data.get("context_analysis", {})
            if not isinstance(context, dict):
                logger.warning(
                    "Ignoring malformed L2 context_analysis of type %s",
                    type(context).__name__,
                )
                context = {}
            
            return validated, implicit, context
            
        except Exception as e:
            logger.error(f"❌ L2 error: {e}")
            return l1_candidates, [], {}

    @staticmethod
    def _payload_shape_errors(value) -> List[str]:
        """Return schema errors that require a corrective LLM retry."""
        if not isinstance(value, dict) or not value:
            return [f"root={type(value).__name__}"]

        errors = []
        for field_name in ("validated_codes", "implicit_problems"):
            field_value = value.get(field_name)
            if not isinstance(field_value, list):
                errors.append(f"{field_name}={type(field_value).__name__}")
            elif any(not isinstance(item, dict) for item in field_value):
                errors.append(f"{field_name}=contains_non_object")
        context = value.get("context_analysis")
        if not isinstance(context, dict):
            errors.append(f"context_analysis={type(context).__name__}")
        return errors

    @staticmethod
    def _dict_items(value, field_name: str) -> List[Dict]:
        """Keep valid object entries from occasionally malformed LLM arrays."""
        if isinstance(value, dict):
            value = [value]
        if not isinstance(value, list):
            logger.warning(
                "Ignoring malformed L2 %s of type %s",
                field_name,
                type(value).__name__,
            )
            return []
        valid = [item for item in value if isinstance(item, dict)]
        dropped = len(value) - len(valid)
        if dropped:
            logger.warning(
                "Ignored %d non-object entr%s in L2 %s",
                dropped,
                "y" if dropped == 1 else "ies",
                field_name,
            )
        return valid
    
    def _format_l1_context(
        self, 
        candidates: List[DetectedProblem],
        needs_validation: List[str],
        conflicts: Dict[str, List[str]]
    ) -> str:
        """Format L1 results for LLM"""
        lines = ["📊 L1 Detection Results:"]
        
        for p in candidates:
            status = "⚠️ NEEDS_VALIDATION" if p.code in needs_validation else "✅"
            lines.append(f"  {status} [{p.code}] {p.name} (conf: {p.confidence:.0%})")
            if p.validation_notes:
                lines.append(f"      Note: {p.validation_notes}")
        
        if conflicts:
            lines.append("\n⚡ Conflicts detected:")
            for code, conflict_with in conflicts.items():
                lines.append(f"  - {code} conflicts with {conflict_with}")
        
        return "\n".join(lines)
    
    # High-severity codes that must never be completely dropped
    CRISIS_SEVERITY_THRESHOLD = 4
    
    def _process_validation(
        self, 
        l1_candidates: List[DetectedProblem],
        validation_results: List[Dict],
        validation_targets: Optional[Set[str]] = None,
    ) -> List[DetectedProblem]:
        """Process LLM validation results with severity-based safety net"""
        validated = []
        validation_map = {v.get("code"): v for v in validation_results}
        target_codes = set(validation_targets or [])
        
        for p in l1_candidates:
            # Preserve L1-positive candidates that were not explicitly queued for
            # L2 adjudication. This prevents broad LLM invalidation from removing
            # clear lexical/context matches such as 1001/1201 in long narratives.
            if p.code not in target_codes:
                if p.context_valid:
                    validated.append(p)
                continue

            if p.code in validation_map:
                v = validation_map[p.code]
                if v.get("is_valid", True):
                    # If L1 context was invalid, don't blindly trust L2 validation
                    if not p.context_valid:
                        # L2 disagrees with L1 context analysis — keep but with reduced confidence
                        p.detection_level = "L1-Validated"
                        p.confidence = min(0.4, p.confidence)
                        p.reasoning = v.get("reason", p.reasoning)
                        p.validation_notes = f"L2 validated but L1 context invalid: {p.validation_notes}"
                        validated.append(p)
                        logger.info(f"  ⚠️ L2 validated but L1 context invalid: [{p.code}] - kept with low conf")
                    else:
                        p.detection_level = "L1-Validated"
                        p.confidence = min(0.95, p.confidence * 1.2)
                        p.reasoning = v.get("reason", p.reasoning)
                        validated.append(p)
                else:
                    # Safety net: only keep if BOTH high-severity AND L1 context was valid
                    # This prevents keeping irrelevant codes (e.g., 0102 spousal violence
                    # when text is about self-harm) while protecting genuine crisis codes
                    if p.severity >= self.CRISIS_SEVERITY_THRESHOLD and p.context_valid:
                        p.detection_level = "L1-Validated"
                        p.confidence = max(0.4, p.confidence * 0.6)
                        p.reasoning = v.get("reason", p.reasoning)
                        p.validation_notes = f"L2 flagged but kept (severity={p.severity}, context confirmed)"
                        validated.append(p)
                        logger.info(f"  ⚠️ Kept (crisis+context): [{p.code}] {p.name} - {v.get('reason')}")
                    else:
                        # Filter: either low severity OR L1 context was invalid
                        logger.info(f"  ❌ Filtered: [{p.code}] (sev={p.severity}, ctx={p.context_valid}) - {v.get('reason')}")
            else:
                # Not in validation list - keep if context_valid
                if p.context_valid:
                    validated.append(p)
        
        return validated

    def _implicit_requires_anchor(self, code: str) -> bool:
        # Any implicit code proposed by L2 must still be anchored by at least one
        # taxonomy keyword in either the quoted evidence or the source case text.
        # This keeps L2 from inventing sibling-family problems such as 0205 when
        # the case only contains abuse language for 0206.
        return True

    def _implicit_has_taxonomy_anchor(
        self,
        code: str,
        evidence_text: str,
        full_text: str,
        taxonomy: Optional[Dict],
    ) -> bool:
        if not taxonomy or code not in taxonomy:
            return False

        info = taxonomy.get(code, {})
        keywords = [str(keyword).lower() for keyword in info.get("keywords", []) if keyword]
        if not keywords:
            return False

        evidence_lower = (evidence_text or "").lower()
        full_text_lower = (full_text or "").lower()

        return any(keyword in evidence_lower or keyword in full_text_lower for keyword in keywords)

    def _process_implicit(
        self, 
        implicit_data: List[Dict],
        l1_candidates: List[DetectedProblem],
        full_text: str = "",
        taxonomy: Dict = None
    ) -> List[DetectedProblem]:
        """Process implicit problems from LLM — only accept codes that exist in taxonomy"""
        l1_codes = {p.code for p in l1_candidates}
        implicit = []
        
        for p in implicit_data:
            code = p.get("code", "")
            if not code or code in l1_codes:
                continue
            # Reject codes not in taxonomy (prevents LLM hallucinated codes like "02")
            if taxonomy and code not in taxonomy:
                logger.info(f"  🚫 L2-Implicit rejected: [{code}] not in taxonomy")
                continue
            evidence = p.get("evidence", "") or p.get("reasoning", "")
            if self._implicit_requires_anchor(code) and not self._implicit_has_taxonomy_anchor(code, evidence, full_text, taxonomy):
                logger.info(
                    f"  🚫 L2-Implicit rejected: [{code}] lacks taxonomy anchor in evidence/text "
                    f"for high-precision category"
                )
                continue
            # Use taxonomy name/category if available
            name = taxonomy[code].get("name", p.get("name", "")) if taxonomy and code in taxonomy else p.get("name", "")
            category = taxonomy[code].get("category", p.get("category", "Implicit")) if taxonomy and code in taxonomy else p.get("category", "Implicit")
            implicit.append(DetectedProblem(
                code=code,
                name=name,
                category=category,
                severity=int(p.get("severity", 3)),
                confidence=float(p.get("confidence", 0.75)),
                detection_level="L2",
                reasoning=p.get("reasoning", "LLM Inferred"),
                matched_keywords=[p.get("evidence", "")] if p.get("evidence") else [],
                matched_spans=[],
                evidence_spans=[],
                context_valid=True
            ))
        
        return implicit
    
    def _parse_json(self, content: str) -> Optional[Dict]:
        """Parse JSON from LLM response"""
        try:
            # Try JSON block first
            match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            
            # Try raw JSON
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            
            return json.loads(content)
        except:
            return None


# =============================================================================
# MAIN H2L DETECTOR CLASS
# =============================================================================

class H2LDetectorV3:
    """
    H2L Detector V3 - Generic Context-Aware Detection
    
    Features:
    1. Data-Driven Context Rules (ไม่ Hardcode)
    2. Automatic Conflict Detection
    3. Two-Level Detection (L1 + L2)
    4. รองรับทุก 204+ problem codes
    """
    
    def __init__(
        self, 
        config=None, 
        taxonomy_path: str = "data/problem_codes.json",
        taxonomy: Dict = None,
        enable_l2: bool = True
    ):
        # Initialize L1
        self.l1_detector = L1ContextAwareDetector(taxonomy_path, taxonomy)
        
        # Initialize L2 (optional)
        self.l2_detector = None
        if enable_l2:
            self.l2_detector = L2SemanticDetector(config)
        
        logger.info(f"✅ [H2LDetectorV3] Initialized (L2: {'enabled' if enable_l2 else 'disabled'})")
    
    def detect_problems(
        self, 
        text: str, 
        use_l2: bool = True,
        l2_model: Optional[str] = None,
    ) -> List[Dict]:
        """
        Main detection method
        
        Args:
            text: Case description
            use_l2: Whether to use L2 for validation
        
        Returns:
            List of detected problems as dicts
        """
        if not text:
            return []
        
        # Phase 1: L1 Detection with Context Validation
        l1_results, metadata = self.l1_detector.detect(text)
        
        logger.info(f"\n{'='*60}")
        logger.info(f"📋 [H2L-V3] Detection Results")
        logger.info(f"{'='*60}")
        logger.info(f"L1 Detected: {len(l1_results)} problems")
        logger.info(f"Needs Validation: {len(metadata.get('needs_l2_validation', []))} codes")
        logger.info(f"Conflicts: {metadata.get('conflicts', {})}")
        
        # Phase 2: L2 Validation (if enabled)
        l2_results = []
        context = {}
        
        if use_l2 and self.l2_detector and self.l2_detector.is_ready:
            needs_validation = metadata.get("needs_l2_validation", [])
            conflicts = metadata.get("conflicts", {})
            
            if needs_validation or conflicts:
                logger.info("\n🔍 Running L2 Validation...")
                l1_results, l2_results, context = self.l2_detector.validate_and_detect(
                    text, l1_results, needs_validation, conflicts,
                    taxonomy=self.l1_detector.taxonomy,
                    model=l2_model,
                )
                logger.info(f"L2 Implicit: {len(l2_results)} problems")
        
        # Combine
        all_results = l1_results + l2_results
        
        # Enforce taxonomy names and categories to prevent LLM hallucination
        for p in all_results:
            if p.code in self.l1_detector.taxonomy:
                p.name = self.l1_detector.taxonomy[p.code].get("name", p.name)
                p.category = self.l1_detector.taxonomy[p.code].get("category", p.category)
                
        all_results.sort(key=lambda x: (x.severity, x.confidence), reverse=True)
        
        # Final quality filter: remove items with extremely low confidence
        # These are L1-flagged items that lack proper context
        FINAL_MIN_CONFIDENCE = 0.25
        final_results = [p for p in all_results if p.confidence >= FINAL_MIN_CONFIDENCE]
        filtered = [p for p in all_results if p.confidence < FINAL_MIN_CONFIDENCE]
        for p in filtered:
            logger.info(f"  🚫 Final filter: [{p.code}] {p.name} (conf={p.confidence:.0%})")
        all_results = final_results
        
        # Log final results
        logger.info(f"\n✅ Final: {len(all_results)} problems")
        for p in all_results[:5]:
            logger.info(f"  [{p.code}] {p.name} (sev:{p.severity}, conf:{p.confidence:.0%}, level:{p.detection_level})")
        logger.info(f"{'='*60}\n")
        
        return [classify_review_status_dict(self._to_dict(p)) for p in all_results]
    
    def detect_with_metadata(
        self,
        text: str,
        use_l2: bool = True,
        l2_model: Optional[str] = None,
    ) -> Dict:
        """
        Detection with full metadata
        
        Returns:
            {
                "problems": [...],
                "metadata": {
                    "total": int,
                    "l1_count": int,
                    "l2_count": int,
                    "conflicts": {...},
                    "context_analysis": {...}
                }
            }
        """
        if not text:
            return {"problems": [], "metadata": {}}

        total_started = time.perf_counter()

        # L1
        l1_started = time.perf_counter()
        l1_results, l1_metadata = self.l1_detector.detect(text)
        l1_ms = round((time.perf_counter() - l1_started) * 1000, 2)

        # =====================================================================
        # BASELINE MODE (use_l2=False): Return raw L1 results WITHOUT filtering
        # This ensures baselines show their inherent detection capability only.
        # No L2 validation, no confidence threshold, no context pre-filtering.
        # Reasoning is simplified to keyword-match-only (no context analysis).
        # =====================================================================
        if not use_l2:
            # Include L1 pre-filtered items back into results for baseline
            l1_filtered = l1_metadata.get("l1_filtered_out", [])
            all_baseline = l1_results + l1_filtered
            all_baseline.sort(key=lambda x: (x.severity, x.confidence), reverse=True)
            
            # Enforce taxonomy names + strip context reasoning for baseline
            for p in all_baseline:
                if p.code in self.l1_detector.taxonomy:
                    p.name = self.l1_detector.taxonomy[p.code].get("name", p.name)
                    p.category = self.l1_detector.taxonomy[p.code].get("category", p.category)
                # Baseline: show only what keyword matching found
                kw_list = ", ".join(f"'{k}'" for k in (p.matched_keywords or [])[:5])
                p.reasoning = f"Keyword matching พบคำสำคัญ: {kw_list}" if kw_list else "Keyword matching"
                p.detection_level = "L1"  # Plain L1, no validation status
                p.context_valid = True    # No context judgment in baseline
                p.validation_notes = ""
            
            return {
                "problems": [classify_review_status_dict(self._to_dict(p), baseline=True) for p in all_baseline],
                "filtered_out": [],  # Baseline does NOT filter anything
                "metadata": {
                    "total": len(all_baseline),
                    "l1_count": len(all_baseline),
                    "l2_count": 0,
                    "conflicts": l1_metadata.get("conflicts", {}),
                    "needs_l2_validation": l1_metadata.get("needs_l2_validation", []),
                    "l1_filtered_out": [classify_review_status_dict(self._to_dict(p), filtered=True, baseline=True) for p in l1_metadata.get("l1_filtered_out", [])],
                    "context_analysis": {},
                    "l2_model": None,
                    "l2_attempted": False,
                    "l2_ready": bool(self.l2_detector and self.l2_detector.is_ready),
                    "timings_ms": {
                        "l1": l1_ms,
                        "l2": 0.0,
                        "total_detection": round((time.perf_counter() - total_started) * 1000, 2),
                    },
                }
            }

        # =====================================================================
        # H2L-ENHANCED MODE (use_l2=True): Full L2 validation + filtering
        # =====================================================================
        l2_results = []
        context = {}
        filtered_out = []
        l2_ms = 0.0
        l2_attempted = False
        l2_ready = bool(self.l2_detector and self.l2_detector.is_ready)

        if l2_ready:
            needs_validation = l1_metadata.get("needs_l2_validation", [])
            conflicts = l1_metadata.get("conflicts", {})

            if needs_validation or conflicts:
                # Store original L1 results before validation
                original_l1_results = l1_results.copy()

                # L2 validation
                l2_attempted = True
                l2_started = time.perf_counter()
                l1_results, l2_results, context = self.l2_detector.validate_and_detect(
                    text, l1_results, needs_validation, conflicts,
                    taxonomy=self.l1_detector.taxonomy,
                    model=l2_model,
                )
                l2_ms = round((time.perf_counter() - l2_started) * 1000, 2)

                # Find filtered problems (L1 problems that didn't pass L2 validation)
                validated_codes = {p.code for p in l1_results}

                # Create filtered_out list from original L1 that weren't validated
                for p in original_l1_results:
                    if p.code not in validated_codes:
                        filtered_out.append(self._to_dict(p))

        # If semantic L2 is unavailable or fails open, still apply the
        # deterministic L1 context gate in H2L mode. This keeps the live API from
        # behaving like baseline mode when the LLM endpoint is degraded.
        if use_l2 and (not l2_ready or (l2_attempted and not context and not l2_results)):
            fallback_kept = []
            already_filtered = {item.get("code") for item in filtered_out}
            for p in l1_results:
                if (
                    p.detection_level == "L1-NeedsValidation"
                    and not p.context_valid
                    and p.severity < L2SemanticDetector.CRISIS_SEVERITY_THRESHOLD
                ):
                    if p.code not in already_filtered:
                        p.validation_notes = p.validation_notes or p.reasoning
                        filtered_out.append(self._to_dict(p))
                        already_filtered.add(p.code)
                    continue
                fallback_kept.append(p)
            l1_results = fallback_kept

        # Combine
        all_results = l1_results + l2_results
        
        # Enforce taxonomy names and categories to prevent LLM hallucination
        for p in all_results:
            if p.code in self.l1_detector.taxonomy:
                p.name = self.l1_detector.taxonomy[p.code].get("name", p.name)
                p.category = self.l1_detector.taxonomy[p.code].get("category", p.category)
                
        all_results.sort(key=lambda x: (x.severity, x.confidence), reverse=True)

        # Final quality filter (H2L mode only)
        FINAL_MIN_CONFIDENCE = 0.25
        final_results = [p for p in all_results if p.confidence >= FINAL_MIN_CONFIDENCE]
        final_filtered = [p for p in all_results if p.confidence < FINAL_MIN_CONFIDENCE]
        for p in final_filtered:
            filtered_out.append(self._to_dict(p))
        all_results = final_results

        # Also include L1-filtered items in filtered_out
        l1_filtered = l1_metadata.get("l1_filtered_out", [])
        for p in l1_filtered:
            filtered_out.append(self._to_dict(p))

        # Enforce taxonomy names/categories for filtered_out items as well
        for p_dict in filtered_out:
            code = p_dict.get("code")
            if code in self.l1_detector.taxonomy:
                p_dict["name"] = self.l1_detector.taxonomy[code].get("name", p_dict.get("name"))
                p_dict["category"] = self.l1_detector.taxonomy[code].get("category", p_dict.get("category"))

        annotated_problems = [classify_review_status_dict(self._to_dict(p)) for p in all_results]
        annotated_filtered = [classify_review_status_dict(item, filtered=True) for item in filtered_out]

        return {
            "problems": annotated_problems,
            "filtered_out": annotated_filtered,
            "metadata": {
                "total": len(all_results),
                "l1_count": len([p for p in all_results if p.detection_level.startswith("L1")]),
                "l2_count": len([p for p in all_results if p.detection_level == "L2"]),
                "conflicts": l1_metadata.get("conflicts", {}),
                "needs_l2_validation": l1_metadata.get("needs_l2_validation", []),
                "l1_filtered_out": [classify_review_status_dict(self._to_dict(p), filtered=True) for p in l1_metadata.get("l1_filtered_out", [])],
                "context_analysis": context,
                "l2_model": (l2_model or self.l2_detector.model) if l2_attempted and self.l2_detector else None,
                "l2_ready": l2_ready,
                "l2_attempted": l2_attempted,
                "l2_degraded": use_l2 and ((not l2_ready) or (l2_attempted and not context and not l2_results)),
                "timings_ms": {
                    "l1": l1_ms,
                    "l2": l2_ms,
                    "total_detection": round((time.perf_counter() - total_started) * 1000, 2),
                },
            }
        }
    
    def _to_dict(self, p: DetectedProblem) -> Dict:
        """Convert DetectedProblem to dict"""
        return {
            "code": p.code,
            "name": p.name,
            "category": p.category,
            "severity": p.severity,
            "confidence": p.confidence,
            "detection_level": p.detection_level,
            "reasoning": p.reasoning,
            "matched_keywords": p.matched_keywords,
            "matched_spans": p.matched_spans,
            "evidence_spans": p.evidence_spans,
            "context_valid": p.context_valid,
            "validation_notes": p.validation_notes,
        }
    
    def get_taxonomy(self) -> Dict:
        """Get taxonomy for external use"""
        return self.l1_detector.get_taxonomy()


# =============================================================================
# TESTING
# =============================================================================

def test_h2l_v3():
    """Test cases for H2L V3"""
    
    print("\n" + "="*80)
    print("🧪 H2L-Detect V3 Test Suite")
    print("="*80)
    
    # Create detector
    detector = H2LDetectorV3(
        taxonomy_path="data/problem_codes.json",
        enable_l2=False  # Test L1 only first
    )
    
    test_cases = [
        {
            "name": "Self-harm (should be X60-X84, NOT 0102/0206)",
            "text": "เด็กไม่ได้เข้าเรียน บ่นว่าไม่อยากมีชีวิตอยู่ เคยทำร้ายร่างกายตัวเอง",
            "expected_codes": ["X60-X84", "1101"],
            "should_not_have": ["0102", "0206", "T74"]
        },
        {
            "name": "Spousal violence (should be 0102)",
            "text": "หญิงถูกสามีทำร้ายร่างกาย มีรอยฟกช้ำตามตัว",
            "expected_codes": ["0102"],
            "should_not_have": ["X60-X84"]
        },
        {
            "name": "Child abuse by parent (should be 0206)",
            "text": "เด็กถูกพ่อตี แม่ไม่ยอมพาไปหาหมอ",
            "expected_codes": ["0206"],
            "should_not_have": ["0102", "X60-X84"]
        },
        {
            "name": "Financial problem (no relationship context needed)",
            "text": "ผู้ป่วยไม่มีเงินจ่ายค่ารักษา ตกงานมา 3 เดือน",
            "expected_codes": ["1001", "1204"],
            "should_not_have": []
        },
        {
            "name": "Multiple problems",
            "text": "เด็ก 8 ขวบ พ่อติดเหล้า แม่หนีไป ไม่ได้ไปโรงเรียน พูดเรื่องไม่อยากมีชีวิต",
            "expected_codes": ["0201", "1101", "X60-X84"],
            "should_not_have": []
        }
    ]
    
    for i, tc in enumerate(test_cases, 1):
        print(f"\n{'─'*60}")
        print(f"Test {i}: {tc['name']}")
        print(f"{'─'*60}")
        print(f"Input: \"{tc['text']}\"")
        
        results = detector.detect_problems(tc['text'], use_l2=False)
        detected_codes = [r['code'] for r in results]
        
        print(f"\nDetected: {detected_codes}")
        
        # Check expected
        for expected in tc['expected_codes']:
            if expected in detected_codes:
                print(f"  ✅ Found {expected}")
            else:
                print(f"  ❌ Missing {expected}")
        
        # Check should not have
        for bad in tc['should_not_have']:
            if bad in detected_codes:
                # Check confidence
                for r in results:
                    if r['code'] == bad:
                        if r['confidence'] < 0.5:
                            print(f"  ⚠️  {bad} detected but low confidence ({r['confidence']:.0%}) - needs L2")
                        else:
                            print(f"  ❌ Should NOT have {bad}")
            else:
                print(f"  ✅ Correctly excluded {bad}")
    
    print("\n" + "="*80)
    print("✅ Test Suite Complete")
    print("="*80)


# =============================================================================
# BACKWARD COMPATIBILITY
# =============================================================================

# Alias สำหรับ backward compatibility
H2LDetector = H2LDetectorV3

# Expose main detector class
__all__ = ['H2LDetector', 'H2LDetectorV3', 'L1ContextAwareDetector', 'L2SemanticDetector']


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_h2l_v3()
