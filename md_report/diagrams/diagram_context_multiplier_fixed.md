# Mermaid Diagrams: กลไก Context Multiplier (Fixed)

## Diagram 1: Overview Flow ของ Context Multiplier

```mermaid
flowchart TD
    A[ข้อความกรณีศึกษา + Matched Keywords] --> B[_check_context_validity]
    
    B --> C{Code อยู่ใน<br/>SPECIFIC_CODE_RULES?}
    
    C -->|ใช่| D[อ่าน rule จาก<br/>SPECIFIC_CODE_RULES]
    C -->|ไม่| Z[Default: Valid<br/>conf_mult = 1.0]
    
    D --> E[สร้าง keyword_window<br/>radius = 40 chars]
    
    E --> F{ประเภท Rule?}
    
    F -->|self-reference| G[ตรวจสอบ<br/>self_indicators]
    F -->|passive| H[ตรวจสอบ<br/>passive_indicators]
    F -->|distress| I[ตรวจสอบ<br/>distress context]
    F -->|other| J[ตรวจสอบบริบทเฉพาะ]
    
    G --> K{มี self-ref<br/>ไม่มี other_person?}
    K -->|ใช่| L[Valid<br/>conf_mult = 1.0]
    K -->|ไม่มี self-ref| M[Invalid<br/>conf_mult = 0.3]
    K -->|มี other_person| N[Invalid<br/>conf_mult = 0.1]
    
    H --> O{มี passive voice?}
    O -->|ใช่| L
    O -->|ไม่| P[Invalid<br/>conf_mult = 0.4]
    
    I --> Q{มี signals >= 2?}
    Q -->|ใช่| L
    Q -->|ไม่| P
    
    J --> R{มี context ครบ?}
    R -->|ใช่| L
    R -->|ไม่| P
    
    L --> S[is_valid = True<br/>conf_mult = 1.0]
    M --> T[is_valid = False<br/>conf_mult = 0.3]
    N --> U[is_valid = False<br/>conf_mult = 0.1]
    P --> V[is_valid = False<br/>conf_mult = 0.4]
    Z --> S
    
    S --> W[Return is_valid, conf_mult, reason]
    T --> W
    U --> W
    V --> W
    
    W --> X[_calculate_confidence]
    
    X --> Y[คำนวณ raw_confidence<br/>Base 0.50 + 5 scores]
    
    Y --> AA[final_confidence<br/>= raw × conf_mult]
    
    AA --> AB[clamp 0.05 to 0.95]
    
    AB --> AC{is_valid AND<br/>conf_mult >= 0.8?}
    
    AC -->|ใช่| AD[detection_level = L1]
    AC -->|ไม่| AE[detection_level = L1-NeedsValidation]
    
    AD --> AF[DetectedProblem]
    AE --> AF

    style L fill:#c8e6c9
    style M fill:#ffcdd2
    style N fill:#ffcdd2
    style P fill:#ffcdd2
    style AD fill:#c8e6c9
    style AE fill:#fff9c4
```

---

## Diagram 2: Self-Reference Validation Flow

```mermaid
flowchart TD
    A[Rule: requires_self_reference = True] --> B[self_indicators: ตัวเอง, ตนเอง, ฉัน]
    
    B --> C[สร้าง keyword_windows<br/>radius = 40 chars]
    
    C --> D[ตรวจสอบ has_self]
    
    D --> E{has_self?}
    
    E -->|ใช่| F[ตรวจสอบ other_person<br/>สามี, ภริยา, แฟน, พ่อ, แม่, ลูก]
    E -->|ไม่| G[conf_mult = 0.3<br/>ไม่พบ self-reference]
    
    F --> H{other_person?}
    
    H -->|มี| I[conf_mult = 0.1<br/>wrong actor context]
    H -->|ไม่มี| J[conf_mult = 1.0<br/>ตรวจพบ self-reference]
    
    style J fill:#c8e6c9
    style G fill:#ffcdd2
    style I fill:#ffcdd2
```

---

## Diagram 3: Passive Voice Validation Flow

```mermaid
flowchart TD
    A[Rule: requires_passive = True] --> B[passive_indicators: ถูก, โดน, ถูกทำร้าย]
    
    B --> C[ตรวจสอบ has_passive]
    
    C --> D{has_passive?}
    
    D -->|ใช่| E[conf_mult = 1.0<br/>ตรวจพบ Passive voice]
    D -->|ไม่| F[conf_mult = 0.4<br/>ไม่พบ Passive voice]
    
    style E fill:#c8e6c9
    style F fill:#ffcdd2
```

---

## Diagram 4: Distress Context Validation (F43.2)

```mermaid
flowchart TD
    A[Rule: requires_distress_context] --> B[minimum_signal_count = 2]
    
    B --> C[4 กลุ่มคำบ่งชี้]
    
    C --> D[1. distress_indicators]
    C --> E[2. impact_indicators]
    C --> F[3. stressor_indicators]
    C --> G[4. severity_indicators]
    
    D --> H[นับ signal_count]
    E --> H
    F --> H
    G --> H
    
    H --> I{signal_count >= 2?}
    
    I -->|ใช่| J[conf_mult = 1.0<br/>เครียด + impact]
    I -->|ไม่| K{มี mild_indicators?}
    
    K -->|มี| L[conf_mult = 0.4<br/>ความเครียดระดับเล็กน้อย]
    K -->|ไม่มี| M[conf_mult = 0.4<br/>ไม่มีบริบทผลกระทบ]
    
    style J fill:#c8e6c9
    style L fill:#ffcdd2
    style M fill:#ffcdd2
```

---

## Diagram 5: Confidence Calculation with conf_mult

```mermaid
flowchart LR
    A[Matched Keywords] --> B[คำนวณ Base + 5 scores]
    
    B --> C[1. match_count_score<br/>max 0.24]
    B --> D[2. coverage_score<br/>max 0.10]
    B --> E[3. specificity_score<br/>max 0.12]
    B --> F[4. phrase_bonus<br/>0 หรือ 0.04]
    B --> G[5. repetition_score<br/>max 0.06]
    
    C --> H[raw_confidence<br/>= 0.50 + sum<br/>max = 1.06]
    D --> H
    E --> H
    F --> H
    G --> H
    
    H --> I[conf_mult]
    
    I --> J[final_confidence<br/>= raw × conf_mult]
    
    J --> K[clamp 0.05 to 0.95]
    
    style H fill:#e1f5ff
    style K fill:#fff9c4
```

---

## Diagram 6: Case Study 1 - Valid Context

```mermaid
flowchart TD
    A[ผู้รับบริการถูกสามีทำร้ายร่างกาย หลายครั้ง] --> B[Code: 0102]
    
    B --> C[Matched: ทำร้าย, ร่างกาย]
    
    C --> D[_check_context_validity]
    
    D --> E[พบ: actor = สามี<br/>passive = ถูก<br/>victim = ผู้รับบริการ]
    
    E --> F[is_valid = True<br/>conf_mult = 1.0]
    
    F --> G[raw = 0.80<br/>base 0.50 + match 0.10 + coverage 0.08<br/>+ spec 0.06 + phrase_bonus 0.00 + rep 0.06]
    
    G --> H[final = 0.80 × 1.0 = 0.80]
    
    H --> I[detection_level = L1]
    
    style F fill:#c8e6c9
    style I fill:#c8e6c9
```

---

## Diagram 7: Case Study 2 - Wrong Actor

```mermaid
flowchart TD
    A[ลูกชายพยายามฆ่าตัวตาย] --> B[Code: X60-X84]
    
    B --> C[Matched: พยายามฆ่าตัวตาย]
    
    C --> D[_check_context_validity]
    
    D --> E[พบ: actor = ลูกชาย<br/>self-ref = ไม่มี<br/>other_person = มี]
    
    E --> F[is_valid = False<br/>conf_mult = 0.1]
    
    F --> G[raw = 0.75<br/>base 0.50 + match 0.10 + coverage 0.05<br/>+ spec 0.06 + phrase_bonus 0.04 + rep 0.00]
    
    G --> H[final = 0.75 × 0.1 = 0.075]
    
    H --> I[detection_level = L1-NeedsValidation<br/>กรองออก]
    
    style F fill:#ffcdd2
    style I fill:#ffcdd2
```

---

## Diagram 8: Case Study 3 - Missing Actor

```mermaid
flowchart TD
    A[ถูกทำร้าย] --> B[Code: 0102]
    
    B --> C[Matched: ทำร้าย]
    
    C --> D[_check_context_validity]
    
    D --> E[พบ: passive = ถูก<br/>actor = ไม่มี]
    
    E --> F[is_valid = False<br/>conf_mult = 0.4]
    
    F --> G[raw = 0.60<br/>base 0.50 + match 0.10<br/>+ phrase_bonus 0.00]
    
    G --> H[final = 0.60 × 0.4 = 0.24]
    
    H --> I[detection_level = L1-NeedsValidation<br/>ส่ง L2 ตรวจสอบ]
    
    style F fill:#fff9c4
    style I fill:#fff9c4
```

---

## Diagram 9: conf_mult Summary Table

```mermaid
flowchart TD
    A[Context Multiplier] --> B[1.0 - Valid Context]
    A --> C[0.4 - Missing Actor/Passive]
    A --> D[0.3 - Missing Self-reference]
    A --> E[0.1 - Wrong Actor Context]
    
    B --> B1[บริบทครบถ้วน<br/>ผู้รับบริการถูกสามีทำร้าย]
    
    C --> C1[พบ keyword แต่บริบทไม่พอ<br/>ถูกทำร้าย]
    
    D --> D1[Self-action แต่ไม่มี self-ref<br/>พยายามฆ่าตัวตาย]
    
    E --> E1[Actor ไม่ใช่ผู้รับบริการ<br/>ลูกพยายามฆ่าตัวตาย]
    
    style B fill:#c8e6c9
    style C fill:#fff9c4
    style D fill:#fff9c4
    style E fill:#ffcdd2
```

---

## Diagram 10: Detection Level Decision

```mermaid
flowchart TD
    A[final_confidence คำนวณเสร็จ] --> B{is_valid = True<br/>AND<br/>conf_mult >= 0.8?}
    
    B -->|ใช่| C[detection_level = L1<br/>ผ่านโดยตรง<br/>confidence: 0.72-0.95]
    
    B -->|ไม่| D[detection_level = L1-NeedsValidation<br/>ส่ง L2 ตรวจสอบ]
    
    D --> E{context_valid = False<br/>AND<br/>confidence < 0.30?}
    
    E -->|ใช่| F[Filtered Out<br/>กรองออกที่ L1]
    E -->|ไม่| G[ส่งต่อ L2 Validation]
    
    style C fill:#c8e6c9
    style F fill:#ffcdd2
    style G fill:#fff9c4
```
