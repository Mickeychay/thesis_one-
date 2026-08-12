#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ground Truth Expansion — Augment 92 cases to 200+ with relevance labels
========================================================================
Generates augmented test cases by:
1. Creating paraphrased variants of existing cases
2. Adding cross-complexity variants (simple → complex, complex → simple)
3. Adding adversarial cases for L2 filtering validation
4. Each case includes `relevant_keywords` for document-level relevance judgment

Usage:
    python expand_ground_truth.py                      # Generate expanded dataset
    python expand_ground_truth.py --validate-only      # Validate without generating
    python expand_ground_truth.py --output expanded_ground_truth.json
"""

import json
import copy
import random
import hashlib
import argparse
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

random.seed(42)  # Reproducibility

# ============================================================================
# THAI LANGUAGE AUGMENTATION
# ============================================================================

# Synonyms for common Thai social work terms
THAI_SYNONYMS = {
    "ปัญหา": ["อุปสรรค", "ข้อยุ่งยาก", "ความยากลำบาก"],
    "ช่วยเหลือ": ["สนับสนุน", "อุดหนุน", "ดูแล"],
    "ครอบครัว": ["ครัวเรือน", "สมาชิกในบ้าน"],
    "เด็ก": ["บุตร", "ยเธอ", "ผู้เยาว์"],
    "ผู้สูงอายุ": ["คนชรา", "วัยชรา", "คนสูงวัย"],
    "รายได้": ["เงินได้", "ค่าตอบแทน"],
    "ไม่เพียงพอ": ["ไม่พอ", "ขาดแคลน", "ไม่เพียงพอต่อ"],
    "ทะเลาะ": ["วิวาท", "ขัดแย้ง", "มีปากเสียง"],
    "ความรุนแรง": ["การทำร้าย", "การกระทำรุนแรง"],
    "ซึมเศร้า": ["เศร้าหมอง", "หดหู่", "ท้อแท้"],
    "ยาเสพติด": ["สารเสพติด", "สิ่งเสพติด"],
    "ที่อยู่อาศัย": ["บ้านพัก", "ที่พักอาศัย"],
    "พิการ": ["ทุพพลภาพ", "มีความบกพร่อง"],
    "สุขภาพ": ["ร่างกาย", "สภาพร่างกาย"],
    "การศึกษา": ["เล่าเรียน", "การเรียน"],
    "ตั้งครรภ์": ["มีครรภ์", "ท้อง"],
    "หยุดเรียน": ["ขาดเรียน", "ออกจากโรงเรียน"],
}

# Severity descriptors for complexity escalation
SEVERITY_ESCALATION_PHRASES = {
    1: ["มีอาการเล็กน้อย", "ต้องการคำปรึกษา"],
    2: ["มีอาการปานกลาง", "ต้องการการติดตาม"],
    3: ["มีอาการค่อนข้างรุนแรง", "ต้องการการดูแลอย่างใกล้ชิด"],
    4: ["มีอาการร้ายแรง", "ต้องการการดำเนินการเร่งด่วน"],
    5: ["มีอาการวิกฤต", "ต้องการการแทรกแซงฉุกเฉิน"],
}

# Adversarial templates — queries that trigger L1 false positives
ADVERSARIAL_TEMPLATES = [
    {
        "template": "ผู้ป่วยเล่าว่าเคย {trigger_word} ในอดีต แต่ปัจจุบันหายดีแล้ว มาร้องเรียนเรื่อง {actual_problem}",
        "trigger_word": "คิดฆ่าตัวตาย",
        "false_code": "X60-X84",
        "actual_problem": "สิทธิสวัสดิการที่ไม่ได้รับ",
        "actual_codes": ["Z59.7"],
        "description": "L1 false positive: suicide keyword in historical context"
    },
    {
        "template": "อ่านข่าว {trigger_word} ในหนังสือพิมพ์ ผู้รับบริการกังวลเกี่ยวกับ {actual_problem}",
        "trigger_word": "ยาเสพติดระบาด",
        "false_code": "F10-F19",
        "actual_problem": "ความปลอดภัยของลูกหลานในละแวกบ้าน",
        "actual_codes": ["Z63.0"],
        "description": "L1 false positive: drug keyword in news context"
    },
    {
        "template": "ผู้รับบริการทำงานเป็นพยาบาลดูแลผู้ป่วย {trigger_word} ต้องการคำปรึกษาเรื่องความเครียดจากงาน",
        "trigger_word": "โรคจิต",
        "false_code": "F20-F29",
        "actual_problem": "ความเครียดจากการทำงาน",
        "actual_codes": ["Z56"],
        "description": "L1 false positive: psychiatric keyword in occupational context"
    },
    {
        "template": "ลูกชายวัยรุ่นชอบเล่นเกมที่มีเนื้อหา {trigger_word} ผู้ปกครองกังวลเรื่อง {actual_problem}",
        "trigger_word": "ความรุนแรง",
        "false_code": "T74",
        "actual_problem": "พฤติกรรมเด็กติดเกม",
        "actual_codes": ["F63"],
        "description": "L1 false positive: violence keyword in game context"
    },
    {
        "template": "ครูรายงานว่านักเรียนเขียนเรียงความเรื่อง {trigger_word} ครอบครัวเด็กมีปัญหาเรื่อง {actual_problem}",
        "trigger_word": "การทำร้ายร่างกาย",
        "false_code": "T74",
        "actual_problem": "ความยากจนและค่าเล่าเรียน",
        "actual_codes": ["1001", "1101"],
        "description": "L1 false positive: violence keyword in essay context"
    },
]


# ============================================================================
# AUGMENTATION FUNCTIONS
# ============================================================================

def substitute_synonyms(text: str, num_subs: int = 2) -> str:
    """Replace random words with Thai synonyms"""
    modified = text
    candidates = [(word, syns) for word, syns in THAI_SYNONYMS.items() if word in text]
    
    if not candidates:
        return text
    
    selected = random.sample(candidates, min(num_subs, len(candidates)))
    for word, syns in selected:
        replacement = random.choice(syns)
        modified = modified.replace(word, replacement, 1)
    
    return modified


def escalate_complexity(case: Dict, target_complexity: str) -> Dict:
    """Create a variant with different complexity level"""
    new_case = copy.deepcopy(case)
    problems = new_case.get('expected_diagnosis', {}).get('problem_list', [])
    
    if target_complexity == 'complex' and case.get('complexity') == 'simple':
        # Add more problems, increase severity
        if problems:
            # Increase severity of existing problems
            for p in problems:
                p['severity'] = min(p.get('severity', 1) + 1, 5)
            # Add a complicating problem
            complication = {
                "code": "F32",
                "category": "โรคซึมเศร้า",
                "severity": 3,
                "details": "มีอาการซึมเศร้าร่วม เนื่องจากสถานการณ์ที่เผชิญ"
            }
            problems.append(complication)
        
        new_case['complexity'] = 'complex'
        desc = new_case.get('case_description', '')
        new_case['case_description'] = desc + " มีอาการซึมเศร้าร่วม เริ่มแยกตัว ไม่ยอมพูดคุยกับคนรอบข้าง"
        
    elif target_complexity == 'simple' and case.get('complexity') == 'complex':
        # Reduce problems, lower severity
        if len(problems) > 2:
            new_case['expected_diagnosis']['problem_list'] = problems[:2]
        for p in new_case['expected_diagnosis']['problem_list']:
            p['severity'] = max(p.get('severity', 3) - 1, 1)
        
        new_case['complexity'] = 'simple'
        desc = new_case.get('case_description', '')
        # Truncate to create simpler variant
        sentences = desc.split(' ')
        if len(sentences) > 3:
            new_case['case_description'] = ' '.join(sentences[:3])
    
    return new_case


def create_adversarial_cases(taxonomy: Dict) -> List[Dict]:
    """Create adversarial cases that trigger L1 false positives"""
    cases = []
    
    for i, template_data in enumerate(ADVERSARIAL_TEMPLATES):
        # Build the case text from template
        case_text = template_data['template'].format(
            trigger_word=template_data['trigger_word'],
            actual_problem=template_data['actual_problem']
        )
        
        # Build expected problems from actual codes
        problem_list = []
        for code in template_data['actual_codes']:
            tax_entry = taxonomy.get(code, {})
            problem_list.append({
                "code": code,
                "category": tax_entry.get('category', code),
                "severity": tax_entry.get('severity', 2),
                "details": template_data['actual_problem']
            })
        
        case = {
            "case_id": f"ADV_{i+1:03d}",
            "complexity": "moderate",
            "category": "adversarial_l2_test",
            "case_description": case_text,
            "expected_diagnosis": {
                "problem_list": problem_list,
                "recommended_tools": [],
                "service_plan": {}
            },
            "augmentation": {
                "type": "adversarial",
                "description": template_data['description'],
                "false_trigger_code": template_data['false_code'],
                "trigger_word": template_data['trigger_word'],
            }
        }
        cases.append(case)
    
    return cases


def generate_case_id(original_id: str, aug_type: str, index: int) -> str:
    """Generate unique case ID for augmented cases"""
    return f"{original_id}_{aug_type}_{index:02d}"


# ============================================================================
# MAIN EXPANSION
# ============================================================================

def expand_ground_truth(
    input_path: str = "data/expanded_ground_truth.json",
    taxonomy_path: str = "data/problem_codes.json",
    target_count: int = 200
) -> Dict:
    """
    Expand ground truth from 92 to target_count cases.
    
    Strategy:
    1. Keep all 92 original cases
    2. Generate paraphrased variants (~92 more)  
    3. Generate cross-complexity variants (~20)
    4. Add adversarial L2 test cases (~5-10)
    5. Add relevant_keywords to each case for evaluation
    """
    # Load data
    with open(input_path, 'r', encoding='utf-8') as f:
        gt_data = json.load(f)
    
    with open(taxonomy_path, 'r', encoding='utf-8') as f:
        taxonomy = json.load(f)
    
    original_cases = gt_data.get('cases', [])
    expanded_cases = list(original_cases)  # Keep originals
    
    print(f"📦 Original cases: {len(original_cases)}")
    
    # 1. Paraphrased variants
    paraphrase_count = 0
    for case in original_cases:
        variant = copy.deepcopy(case)
        original_desc = case.get('case_description', '')
        
        paraphrased = substitute_synonyms(original_desc, num_subs=2)
        if paraphrased != original_desc:
            variant['case_id'] = generate_case_id(case['case_id'], 'PAR', 1)
            variant['case_description'] = paraphrased
            variant['augmentation'] = {
                'type': 'paraphrase',
                'source_case_id': case['case_id']
            }
            expanded_cases.append(variant)
            paraphrase_count += 1
    
    print(f"✅ Paraphrased variants: +{paraphrase_count}")
    
    # 2. Cross-complexity variants
    simple_cases = [c for c in original_cases if c.get('complexity') == 'simple']
    complex_cases = [c for c in original_cases if c.get('complexity') == 'complex']
    
    complexity_count = 0
    for case in simple_cases[:10]:
        variant = escalate_complexity(case, 'complex')
        variant['case_id'] = generate_case_id(case['case_id'], 'ESC', 1)
        variant['augmentation'] = {
            'type': 'complexity_escalation',
            'source_case_id': case['case_id'],
            'from_complexity': 'simple',
            'to_complexity': 'complex'
        }
        expanded_cases.append(variant)
        complexity_count += 1
    
    for case in complex_cases[:10]:
        variant = escalate_complexity(case, 'simple')
        variant['case_id'] = generate_case_id(case['case_id'], 'SIM', 1)
        variant['augmentation'] = {
            'type': 'complexity_reduction',
            'source_case_id': case['case_id'],
            'from_complexity': 'complex',
            'to_complexity': 'simple'
        }
        expanded_cases.append(variant)
        complexity_count += 1
    
    print(f"✅ Complexity variants: +{complexity_count}")
    
    # 3. Adversarial cases
    adversarial_cases = create_adversarial_cases(taxonomy)
    expanded_cases.extend(adversarial_cases)
    print(f"✅ Adversarial cases: +{len(adversarial_cases)}")
    
    # 4. Add relevant_keywords to ALL cases for evaluation
    for case in expanded_cases:
        problems = case.get('expected_diagnosis', {}).get('problem_list', [])
        keywords_by_problem = {}
        
        for prob in problems:
            code = prob.get('code', '')
            kw_list = []
            
            # From taxonomy
            if code in taxonomy:
                tax = taxonomy[code]
                kw_list.extend(tax.get('keywords', []))
                name = tax.get('name', '')
                if name:
                    kw_list.append(name)
            
            # From problem entry itself
            cat = prob.get('category', '')
            if cat:
                parts = cat.split(' - ')
                for p in parts:
                    if p.strip() and not p.strip().isdigit():
                        kw_list.append(p.strip())
            
            details = prob.get('details', '')
            if details:
                kw_list.append(details)
            
            # Deduplicate
            seen = set()
            clean = []
            for kw in kw_list:
                kw_clean = kw.strip()
                if kw_clean and kw_clean not in seen:
                    clean.append(kw_clean)
                    seen.add(kw_clean)
            
            if clean:
                keywords_by_problem[code] = clean
        
        case['relevant_keywords'] = keywords_by_problem
    
    # Build output
    from collections import Counter
    complexity_dist = Counter(c.get('complexity', 'unknown') for c in expanded_cases)
    aug_types = Counter(c.get('augmentation', {}).get('type', 'original') for c in expanded_cases)
    
    output = {
        "metadata": {
            "version": "2.0-expanded",
            "total_cases": len(expanded_cases),
            "original_cases": len(original_cases),
            "generated_cases": len(expanded_cases) - len(original_cases),
            "complexity_distribution": dict(complexity_dist),
            "augmentation_types": dict(aug_types),
            "generated_at": datetime.now().isoformat(),
            "categories": len(set(c.get('category', '') for c in expanded_cases)),
        },
        "cases": expanded_cases
    }
    
    print(f"\n📊 Total expanded cases: {len(expanded_cases)}")
    print(f"   Complexity: {dict(complexity_dist)}")
    print(f"   Augmentation types: {dict(aug_types)}")
    
    return output


def validate_ground_truth(data: Dict) -> bool:
    """Validate ground truth structure"""
    cases = data.get('cases', [])
    errors = []
    
    if len(cases) < 90:
        errors.append(f"Too few cases: {len(cases)} (expected >= 90)")
    
    seen_ids = set()
    for i, case in enumerate(cases):
        cid = case.get('case_id', '')
        if not cid:
            errors.append(f"Case {i}: missing case_id")
        if cid in seen_ids:
            errors.append(f"Case {i}: duplicate case_id '{cid}'")
        seen_ids.add(cid)
        
        if not case.get('case_description'):
            errors.append(f"Case {cid}: missing case_description")
        
        diag = case.get('expected_diagnosis', {})
        problems = diag.get('problem_list', [])
        if not problems:
            errors.append(f"Case {cid}: empty problem_list")
        
        for j, prob in enumerate(problems):
            if not prob.get('code'):
                errors.append(f"Case {cid}, problem {j}: missing code")
            if 'severity' not in prob:
                errors.append(f"Case {cid}, problem {j}: missing severity")
    
    if errors:
        print("❌ Validation errors:")
        for e in errors[:20]:
            print(f"  - {e}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more errors")
        return False
    
    print(f"✅ Validation passed: {len(cases)} cases, all valid")
    return True


def main():
    parser = argparse.ArgumentParser(description='Expand H2L Ground Truth')
    parser.add_argument('--validate-only', action='store_true',
                       help='Only validate existing ground truth')
    parser.add_argument('--output', default='data/expanded_ground_truth.json',
                       help='Output file path (default: expanded_ground_truth.json)')
    parser.add_argument('--input', default='data/expanded_ground_truth.json',
                       help='Input ground truth file')
    parser.add_argument('--target', type=int, default=200,
                       help='Target number of cases')
    
    args = parser.parse_args()
    
    if args.validate_only:
        with open(args.input, 'r', encoding='utf-8') as f:
            data = json.load(f)
        validate_ground_truth(data)
        return
    
    # Expand
    expanded = expand_ground_truth(
        input_path=args.input,
        target_count=args.target
    )
    
    # Validate
    if not validate_ground_truth(expanded):
        print("⚠️ Validation failed but saving anyway...")
    
    # Save
    output_path = Path(args.output)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(expanded, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ Expanded ground truth saved to: {output_path}")


if __name__ == "__main__":
    main()
