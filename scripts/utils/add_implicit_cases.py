import json
import uuid

# Load existing ground truth
with open('data/expanded_ground_truth.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# The 5 implicit reasoning test cases
new_cases = [
    {
        "case_id": f"IMPLICIT_{uuid.uuid4().hex[:6].upper()}",
        "complexity": "implicit_reasoning",
        "split": "test",
        "category": "ผู้สูงอายุ/ผู้พิการ",
        "case_description": "ลูกสาววัย 45 ปี เล่าว่าไม่ได้นอนมา 3 คืนแล้วเพราะต้องคอยพลิกตัวแม่ตลอดเวลา แถมตอนนี้ที่บ้านโดนตัดน้ำตัดไฟมาตั้งแต่ต้นเดือน อาหารก็ต้องขอแบ่งจากวัด",
        "expected_diagnosis": {
            "problem_list": [
                {"code": "0701", "category": "07: ปัญหาภาระในการดูแลผู้เจ็บป่วย/ผู้พิการ/ผู้สูงอายุ", "severity": 3, "details": "ผู้ดูแลต้องพลิกตัวตลอดเวลา อดนอนติดต่อกัน", "code_type": "SOCIAL"},
                {"code": "1001", "category": "10: ปัญหาการเงิน", "severity": 3, "details": "ถูกตัดน้ำตัดไฟ ต้องขออาหารจากวัด บ่งบอกถึงภาวะยากจนรุนแรง", "code_type": "SOCIAL"}
            ]
        }
    },
    {
        "case_id": f"IMPLICIT_{uuid.uuid4().hex[:6].upper()}",
        "complexity": "implicit_reasoning",
        "split": "test",
        "category": "เด็กและเยาวชน",
        "case_description": "เด็กชายวัย 12 ขวบ ประสบอุบัติเหตุ สอบถามพบว่าไม่ได้ไปโรงเรียนมาสองปีแล้ว เพราะตอนกลางวันต้องออกไปช่วยครอบครัวเก็บของเก่าขายประทังชีวิต",
        "expected_diagnosis": {
            "problem_list": [
                {"code": "1102", "category": "11 - ปัญหาการศึกษา", "severity": 3, "details": "หลุดออกจากระบบการศึกษามา 2 ปี", "code_type": "SOCIAL"},
                {"code": "1001", "category": "10: ปัญหาการเงิน", "severity": 2, "details": "ต้องเก็บของเก่าขายประทังชีวิต แสดงถึงความยากจน", "code_type": "SOCIAL"}
            ]
        }
    },
    {
        "case_id": f"IMPLICIT_{uuid.uuid4().hex[:6].upper()}",
        "complexity": "implicit_reasoning",
        "split": "test",
        "category": "ผู้สูงอายุ/ผู้พิการ",
        "case_description": "ผู้ป่วยหญิงสูงอายุนอนรักษาตัวในวอร์ด เมื่อถึงเวลาจำหน่าย ผู้ป่วยบอกว่าไม่อยากกลับไปนอนใต้สะพานลอยตรงแยกไฟฉายอีกแล้ว เพราะฝนตกหนักทุกวัน",
        "expected_diagnosis": {
            "problem_list": [
                {"code": "0802", "category": "08 - ปัญหาที่อยู่อาศัย", "severity": 3, "details": "นอนใต้สะพานลอย", "code_type": "SOCIAL"},
                {"code": "Z59.0", "category": "ไม่มีที่อยู่อาศัย", "severity": 3, "details": "นอนใต้สะพานลอย", "code_type": "ICD"}
            ]
        }
    },
    {
        "case_id": f"IMPLICIT_{uuid.uuid4().hex[:6].upper()}",
        "complexity": "implicit_reasoning",
        "split": "test",
        "category": "ผู้ป่วยเรื้อรัง",
        "case_description": "คนไข้มะเร็งตับขาดนัดทำคีโมมา 3 ครั้งติดต่อกัน เมื่อโทรติดตาม ญาติบอกว่าต้องเอาเงินไปซื้อข้าวให้ลูกกินก่อน เลยไม่มีค่ารถทัวร์เข้ามาในเมือง",
        "expected_diagnosis": {
            "problem_list": [
                {"code": "1405", "category": "14 - อุปสรรคต่อการดูแลสุขภาพ", "severity": 3, "details": "ขาดนัดคีโม 3 ครั้งเพราะขาดค่าเดินทาง", "code_type": "SOCIAL"},
                {"code": "1001", "category": "10: ปัญหาการเงิน", "severity": 3, "details": "ต้องเลือกซื้อข้าวก่อนจ่ายค่ารถ", "code_type": "SOCIAL"}
            ]
        }
    },
    {
        "case_id": f"IMPLICIT_{uuid.uuid4().hex[:6].upper()}",
        "complexity": "implicit_reasoning",
        "split": "test",
        "category": "สตรีและครอบครัว",
        "case_description": "หญิงตั้งครรภ์มาฝากครรภ์ มีรอยฟกช้ำตามตัวและใบหน้า เมื่อพยาบาลถาม เธอก้มหน้าหลบตาแล้วบอกแค่ว่า 'ลื่นล้มชนขอบโต๊ะที่บ้านตอนเมาเหล้าด้วยกัน' แต่รอยช้ำมีลักษณะคล้ายรอยนิ้วมือ",
        "expected_diagnosis": {
            "problem_list": [
                {"code": "T74.1", "category": "ถูกทำร้ายร่างกาย", "severity": 3, "details": "รอยช้ำคล้ายรอยนิ้วมือ ก้มหน้าหลบตา สงสัยถูกทำร้าย", "code_type": "ICD"},
                {"code": "0501", "category": "05 - ความรุนแรงในครอบครัว", "severity": 3, "details": "ดื่มสุราด้วยกัน รอยช้ำคล้ายรอยนิ้วมือ", "code_type": "SOCIAL"}
            ]
        }
    }
]

# Update metadata
data['metadata']['test_cases'] += len(new_cases)
data['metadata']['total_cases'] += len(new_cases)
data['metadata']['implicit_cases_added'] = len(new_cases)
if 'implicit_reasoning' not in data['metadata']['complexity_distribution']:
    data['metadata']['complexity_distribution']['implicit_reasoning'] = 0
data['metadata']['complexity_distribution']['implicit_reasoning'] += len(new_cases)

# Append cases
data['cases'].extend(new_cases)

# Save
with open('data/expanded_ground_truth.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"Successfully added {len(new_cases)} implicit reasoning cases. Total test cases is now {data['metadata']['test_cases']}.")
