# Mermaid Flowchart: 6 กรณีของ Context Multiplier

## Overview: 6 กรณีตัวอย่างการใช้งาน Context Multiplier

```mermaid
flowchart TD
    A[Context Multiplier: 6 กรณีตัวอย่าง] --> B[1. Valid Context<br/>conf_mult = 1.0]
    A --> C[2. Missing Actor<br/>conf_mult = 0.4]
    A --> D[3. Missing Self-reference<br/>conf_mult = 0.3]
    A --> E[4. Wrong Actor Context<br/>conf_mult = 0.1]
    A --> F[5. Missing Passive Voice<br/>conf_mult = 0.4]
    A --> G[6. Insufficient Distress Signals<br/>conf_mult = 0.4]
    
    B --> B1["ผู้รับบริการถูกสามีทำร้ายร่างกาย"<br/>Code: 0102<br/>✓ actor + passive + victim]
    
    C --> C1["ถูกทำร้าย"<br/>Code: 0102<br/>✓ passive ✗ actor]
    
    D --> D1["พยายามฆ่าตัวตาย"<br/>Code: X60-X84<br/>✗ self-reference]
    
    E --> E1["ลูกชายพยายามฆ่าตัวตาย"<br/>Code: X60-X84<br/>✗ wrong actor]
    
    F --> F1["ทำร้ายร่างกาย"<br/>Code: 0102<br/>✗ passive voice]
    
    G --> G1["รู้สึกเครียด"<br/>Code: F43.2<br/>signal_count < 2]
    
    B1 --> B2[raw = 0.80<br/>final = 0.80 × 1.0 = 0.80<br/>Level: L1 ✓]
    
    C1 --> C2[raw = 0.60<br/>final = 0.60 × 0.4 = 0.24<br/>Level: L1-NeedsValidation]
    
    D1 --> D2[raw = 0.70<br/>final = 0.70 × 0.3 = 0.21<br/>Level: L1-NeedsValidation]
    
    E1 --> E2[raw = 0.75<br/>final = 0.75 × 0.1 = 0.075<br/>Level: Filtered ✗]
    
    F1 --> F2[raw = 0.60<br/>final = 0.60 × 0.4 = 0.24<br/>Level: L1-NeedsValidation]
    
    G1 --> G2[raw = 0.65<br/>final = 0.65 × 0.4 = 0.26<br/>Level: L1-NeedsValidation]
    
    style B fill:#c8e6c9
    style B1 fill:#c8e6c9
    style B2 fill:#c8e6c9
    style C fill:#fff9c4
    style D fill:#fff9c4
    style E fill:#ffcdd2
    style F fill:#fff9c4
    style G fill:#fff9c4
```

---

## กรณีที่ 1: Valid Context (conf_mult = 1.0)

**ตัวอย่าง:** "ผู้รับบริการถูกสามีทำร้ายร่างกาย หลายครั้ง"

```mermaid
flowchart TD
    A["ประโยค:<br/>ผู้รับบริการถูกสามีทำร้ายร่างกาย หลายครั้ง"] --> B[Code: 0102<br/>ความรุนแรงระหว่างคู่สมรส]
    
    B --> C[Matched Keywords:<br/>ทำร้าย, ร่างกาย]
    
    C --> D[_check_context_validity<br/>radius = 40 chars]
    
    D --> E{ตรวจสอบบริบท}
    
    E --> F[✓ victim: ผู้รับบริการ<br/>✓ actor: สามี<br/>✓ passive: ถูก]
    
    F --> G[is_valid = True<br/>conf_mult = 1.0<br/>reason: พบ actor + passive ชัดเจน]
    
    G --> H[คำนวณ raw_confidence]
    
    H --> I[base: 0.50<br/>match: 0.10 2 keywords<br/>coverage: 0.08 40%<br/>specificity: 0.06 avg_len=7<br/>phrase_bonus: 0.00 ไม่มีวลียาว<br/>repetition: 0.06 ซ้ำ 2 ครั้ง]
    
    I --> J[raw = 0.80]
    
    J --> K[final = 0.80 × 1.0 = 0.80]
    
    K --> L[clamp 0.05 to 0.95 = 0.80]
    
    L --> M{is_valid AND conf_mult >= 0.8?}
    
    M -->|ใช่| N[detection_level = L1<br/>ผ่านโดยตรง ✓]
    
    style G fill:#c8e6c9
    style N fill:#c8e6c9
```

---

## กรณีที่ 2: Missing Actor (conf_mult = 0.4)

**ตัวอย่าง:** "ถูกทำร้าย"

```mermaid
flowchart TD
    A["ประโยค:<br/>ถูกทำร้าย"] --> B[Code: 0102<br/>ความรุนแรงระหว่างคู่สมรส]
    
    B --> C[Matched Keywords:<br/>ทำร้าย]
    
    C --> D[_check_context_validity<br/>radius = 40 chars]
    
    D --> E{ตรวจสอบบริบท}
    
    E --> F[✓ passive: ถูก<br/>✗ actor: ไม่มี<br/>✗ victim: ไม่ระบุ]
    
    F --> G[is_valid = False<br/>conf_mult = 0.4<br/>reason: missing actor]
    
    G --> H[คำนวณ raw_confidence]
    
    H --> I[base: 0.50<br/>match: 0.10 1 keyword<br/>coverage: 0.04<br/>specificity: 0.03<br/>phrase_bonus: 0.00<br/>repetition: 0.00]
    
    I --> J[raw = 0.60]
    
    J --> K[final = 0.60 × 0.4 = 0.24]
    
    K --> L[clamp 0.05 to 0.95 = 0.24]
    
    L --> M{is_valid AND conf_mult >= 0.8?}
    
    M -->|ไม่| N[detection_level = L1-NeedsValidation<br/>ส่ง L2 ตรวจสอบ]
    
    style G fill:#fff9c4
    style N fill:#fff9c4
```

---

## กรณีที่ 3: Missing Self-reference (conf_mult = 0.3)

**ตัวอย่าง:** "พยายามฆ่าตัวตาย"

```mermaid
flowchart TD
    A["ประโยค:<br/>พยายามฆ่าตัวตาย"] --> B[Code: X60-X84<br/>การพยายามฆ่าตัวตาย<br/>Self-action problem]
    
    B --> C[Matched Keywords:<br/>พยายามฆ่าตัวตาย]
    
    C --> D[_check_context_validity<br/>radius = 40 chars]
    
    D --> E{requires_self_reference?}
    
    E -->|ใช่| F[ตรวจสอบ self_indicators:<br/>ตัวเอง, ฉัน, ผู้ป่วย, ผู้รับบริการ]
    
    F --> G[✗ has_self = False<br/>ไม่พบ self-reference]
    
    G --> H[is_valid = False<br/>conf_mult = 0.3<br/>reason: missing self-reference]
    
    H --> I[คำนวณ raw_confidence]
    
    I --> J[base: 0.50<br/>match: 0.10<br/>coverage: 0.05<br/>specificity: 0.07 avg_len=17<br/>phrase_bonus: 0.04 len>=10<br/>repetition: 0.00]
    
    J --> K[raw = 0.70]
    
    K --> L[final = 0.70 × 0.3 = 0.21]
    
    L --> M[clamp 0.05 to 0.95 = 0.21]
    
    M --> N{is_valid AND conf_mult >= 0.8?}
    
    N -->|ไม่| O[detection_level = L1-NeedsValidation<br/>กรองออก หรือส่ง L2]
    
    style H fill:#fff9c4
    style O fill:#fff9c4
```

---

## กรณีที่ 4: Wrong Actor Context (conf_mult = 0.1)

**ตัวอย่าง:** "ลูกชายพยายามฆ่าตัวตาย" (เคสของแม่)

```mermaid
flowchart TD
    A["ประโยค:<br/>ลูกชายพยายามฆ่าตัวตาย<br/>Context: ผู้รับบริการคือแม่"] --> B[Code: X60-X84<br/>การพยายามฆ่าตัวตาย<br/>Self-action problem]
    
    B --> C[Matched Keywords:<br/>พยายามฆ่าตัวตาย]
    
    C --> D[_check_context_validity<br/>radius = 40 chars]
    
    D --> E{requires_self_reference?}
    
    E -->|ใช่| F[ตรวจสอบ self_indicators]
    
    F --> G[✗ has_self = False<br/>ตรวจสอบ other_person]
    
    G --> H[✓ other_person = True<br/>พบ: ลูกชาย other_person_keywords]
    
    H --> I[is_valid = False<br/>conf_mult = 0.1<br/>reason: wrong actor context]
    
    I --> J[คำนวณ raw_confidence]
    
    J --> K[base: 0.50<br/>match: 0.10<br/>coverage: 0.05<br/>specificity: 0.06<br/>phrase_bonus: 0.04 len>=10<br/>repetition: 0.00]
    
    K --> L[raw = 0.75]
    
    L --> M[final = 0.75 × 0.1 = 0.075]
    
    M --> N[clamp 0.05 to 0.95 = 0.075]
    
    N --> O{is_valid AND conf_mult >= 0.8?}
    
    O -->|ไม่| P[detection_level = L1-NeedsValidation<br/>กรองออก ✗]
    
    style I fill:#ffcdd2
    style P fill:#ffcdd2
```

---

## กรณีที่ 5: Missing Passive Voice (conf_mult = 0.4)

**ตัวอย่าง:** "ทำร้ายร่างกาย" (ไม่มี passive voice)

```mermaid
flowchart TD
    A["ประโยค:<br/>ทำร้ายร่างกาย"] --> B[Code: 0102<br/>ความรุนแรงระหว่างคู่สมรส<br/>Relational problem]
    
    B --> C[Matched Keywords:<br/>ทำร้าย, ร่างกาย]
    
    C --> D[_check_context_validity<br/>radius = 40 chars]
    
    D --> E{requires_passive?}
    
    E -->|ใช่| F[ตรวจสอบ passive_indicators:<br/>ถูก, โดน, ได้รับ]
    
    F --> G[✗ has_passive = False<br/>ไม่พบ passive voice]
    
    G --> H[is_valid = False<br/>conf_mult = 0.4<br/>reason: missing passive voice]
    
    H --> I[คำนวณ raw_confidence]
    
    I --> J[base: 0.50<br/>match: 0.10<br/>coverage: 0.04<br/>specificity: 0.03<br/>phrase_bonus: 0.00<br/>repetition: 0.00]
    
    J --> K[raw = 0.60]
    
    K --> L[final = 0.60 × 0.4 = 0.24]
    
    L --> M[clamp 0.05 to 0.95 = 0.24]
    
    M --> N{is_valid AND conf_mult >= 0.8?}
    
    N -->|ไม่| O[detection_level = L1-NeedsValidation<br/>ส่ง L2 ตรวจสอบ]
    
    style H fill:#fff9c4
    style O fill:#fff9c4
```

---

## กรณีที่ 6: Insufficient Distress Signals (conf_mult = 0.4)

**ตัวอย่าง:** "รู้สึกเครียด" (F43.2 - Adjustment Disorder)

```mermaid
flowchart TD
    A["ประโยค:<br/>รู้สึกเครียด"] --> B[Code: F43.2<br/>Adjustment Disorder<br/>requires_distress_context]
    
    B --> C[Matched Keywords:<br/>เครียด]
    
    C --> D[_check_context_validity<br/>radius = 40 chars]
    
    D --> E{requires_distress_context?}
    
    E -->|ใช่| F[นับ signal_count<br/>จาก 4 กลุ่ม]
    
    F --> G[1. distress_indicators: เครียด ✓<br/>2. impact_indicators: ✗<br/>3. stressor_indicators: ✗<br/>4. severity_indicators: ✗]
    
    G --> H[signal_count = 1]
    
    H --> I{signal_count >= 2?}
    
    I -->|ไม่| J[is_valid = False<br/>conf_mult = 0.4<br/>reason: ความเครียดระดับเล็กน้อย]
    
    J --> K[คำนวณ raw_confidence]
    
    K --> L[base: 0.50<br/>match: 0.10<br/>coverage: 0.05<br/>specificity: 0.03<br/>phrase_bonus: 0.00<br/>repetition: 0.00]
    
    L --> M[raw = 0.65]
    
    M --> N[final = 0.65 × 0.4 = 0.26]
    
    N --> O[clamp 0.05 to 0.95 = 0.26]
    
    O --> P{is_valid AND conf_mult >= 0.8?}
    
    P -->|ไม่| Q[detection_level = L1-NeedsValidation<br/>ส่ง L2 ตรวจสอบ]
    
    style J fill:#fff9c4
    style Q fill:#fff9c4
```

---

## สรุปผลลัพธ์ทั้ง 6 กรณี

| กรณี | conf_mult | raw | final | Level | ผลลัพธ์ |
|------|-----------|-----|-------|-------|---------|
| 1. Valid Context | 1.0 | 0.80 | 0.80 | L1 | ✅ ผ่านโดยตรง |
| 2. Missing Actor | 0.4 | 0.60 | 0.24 | L1-NeedsValidation | ⚠️ ส่ง L2 |
| 3. Missing Self-ref | 0.3 | 0.70 | 0.21 | L1-NeedsValidation | ⚠️ กรองออก/ส่ง L2 |
| 4. Wrong Actor | 0.1 | 0.75 | 0.075 | Filtered | ❌ กรองออก |
| 5. Missing Passive | 0.4 | 0.60 | 0.24 | L1-NeedsValidation | ⚠️ ส่ง L2 |
| 6. Insufficient Signals | 0.4 | 0.65 | 0.26 | L1-NeedsValidation | ⚠️ ส่ง L2 |

**หมายเหตุ:**
- ✅ **L1** (conf_mult = 1.0, final ≥ 0.72): ผ่านโดยตรง ไม่ต้องส่ง L2
- ⚠️ **L1-NeedsValidation** (conf_mult < 0.8, final 0.21-0.40): ส่ง L2 ตรวจสอบ
- ❌ **Filtered** (final < 0.20): กรองออกทันที
- เกณฑ์เก็บผลสุดท้าย: **final_confidence ≥ 0.25**
