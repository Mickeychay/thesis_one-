# บทที่ 4: ผลการทดลองและการวิเคราะห์ข้อมูล (Results and Analysis)

บทนี้นำเสนอผลการทดลองตาม artifact ล่าสุดหลังแก้ split leakage และ rerun evaluation เมื่อวันที่ 25 เมษายน 2026 โดยยึดหลักว่า **รายงานเฉพาะผลที่เกิดจากการรันจริง** ไม่ใช้ mock data หรือค่าประมาณเพื่อทำให้ผลดูดีขึ้น ผลหลักอ้างอิงจาก `evaluation_results/proper_eval_latest_summary.json`, `evaluation_results/sentence_polarity_latest.json`, `evaluation_results/ground_truth_audit.json`, `evaluation_results/q1_readiness_report.md`, `human_evaluation/blind_packet_latest/` และ `ablation_results/v6_component_latest/`

---

## 4.1 กรอบการประเมินผลและข้อมูลที่ใช้

ชุดข้อมูลหลักคือ `expanded_ground_truth.json` จำนวน 197 เคส หลังปรับเป็น family-level split แล้วแบ่งเป็น train 129 เคส และ test 68 เคส การตรวจ `ground_truth_audit` ไม่พบ case family ที่รั่วข้าม train/test และไม่พบ near-duplicate train/test pair เหนือ threshold ที่กำหนด เหลือ risk flag เพียงข้อเดียวคือชุดข้อมูลยังมี generated / augmented cases ซึ่งต้องรายงานเป็น stress-test slice แยกจากข้ออ้างเชิง generalization

**ตารางที่ 4.1 สรุปสถานะข้อมูลและ protocol ล่าสุด**

| รายการ | ค่า |
|:---|:---|
| ชุดข้อมูลทั้งหมด | 197 เคส |
| Train/Test split | 129 / 68 |
| Split method | family-level leakage-safe split |
| Cross-split family leakage | 0 |
| Near-duplicate train/test pair | 0 |
| Risk flag ที่เหลือ | generated cases ต้องรายงานแยก |
| Retrieval protocol หลัก | `problem_source=detected`, `top_k=15` |
| กลยุทธ์ที่เปรียบเทียบ | 8 กลยุทธ์ |
| สถิติ paired comparison | Wilcoxon Signed-Rank Test |

กลยุทธ์ทั้ง 8 แบบประกอบด้วย baseline 4 แบบ ได้แก่ `bm25_only`, `naive_rag`, `hyde`, `basic` และ H2L-enhanced counterpart 4 แบบ ได้แก่ `h2l-bm25`, `h2l-naive_rag`, `h2l-hyde`, `h2l-hybrid` การตีความในบทนี้ใช้ claim policy แบบ conservative โดยแบ่งผลเป็น `supported`, `trend_only`, `practically_tied` และ `baseline_supported`

---

## 4.2 ผลการประเมิน Sentence Polarity

การประเมิน sentence polarity ใช้ test split ล่าสุดจำนวน 68 เคส แบ่งเป็นเคสยืนยันปัญหา 50 เคส และเคสปฏิเสธปัญหา 18 เคส เป้าหมายของการประเมินนี้คือดูว่า polarity gate สามารถลด false positive จากประโยคปฏิเสธได้หรือไม่ โดยแยกจาก retrieval ranking metrics

**ตารางที่ 4.2 ผลการประเมิน sentence polarity หลังแก้ split leakage**

| ตัวชี้วัด | ค่า |
|:---|---:|
| Total cases | 68 |
| Positive / Negated cases | 50 / 18 |
| Accuracy | 0.8824 |
| Negation Detection Rate (NDR) | 0.7222 |
| False Positive Rate (FPR) | 0.0600 |
| Precision | 0.8125 |
| F1 | 0.7650 |
| Mean G_neg positive | 0.9760 |
| Mean G_neg negated | 0.6000 |

ผลนี้หมายความว่า polarity gate ตรวจจับเคสปฏิเสธได้ 13 จาก 18 เคส และเกิด false positive ในเคสยืนยันปัญหา 3 จาก 50 เคส จุดแข็งคือระบบลด false positive ได้จริงในเคสปฏิเสธจำนวนมาก แต่จุดที่ยังต้องปรับปรุงคือ negation ในข้อความยาว โดยผลแยกตามความยาวพบว่า short NDR = 100.0%, medium NDR = 66.7% และ long NDR = 50.0%

ดังนั้น polarity gate ควรถูกอภิปรายเป็น **safety mechanism ที่มีผลเชิงบวกแต่ยังไม่สมบูรณ์** ไม่ใช่กลไกที่แก้ negation blindness ได้ทั้งหมด

---

## 4.3 ผลการประเมิน Retrieval Performance

### 4.3.1 ผลรวมทุกกลยุทธ์

**ตารางที่ 4.3 ผลรวม retrieval metrics จาก proper evaluation ล่าสุด**

| กลยุทธ์ | nDCG@5 | MAP | MRR | P@5 | F1@5 | เวลาเฉลี่ยต่อเคส (วินาที) |
|:---|---:|---:|---:|---:|---:|---:|
| `bm25_only` | 0.2079 | 0.2196 | 0.2697 | 0.0971 | 0.1252 | **0.0013** |
| `naive_rag` | 0.2034 | 0.2003 | 0.2635 | 0.1029 | 0.1321 | 0.0867 |
| `hyde` | 0.1120 | 0.1113 | 0.1224 | 0.0412 | 0.0596 | 3.8283 |
| `basic` | 0.2270 | 0.2250 | 0.2710 | 0.1118 | 0.1435 | 1.0582 |
| `h2l-bm25` | **0.2437** | 0.2289 | 0.2687 | **0.1176** | **0.1529** | 0.0137 |
| `h2l-naive_rag` | 0.1962 | 0.1936 | 0.2703 | 0.1000 | 0.1252 | 0.9222 |
| `h2l-hyde` | 0.1405 | 0.1479 | 0.1697 | 0.0441 | 0.0641 | 7.0039 |
| `h2l-hybrid` | 0.2290 | **0.2362** | **0.2893** | 0.1088 | 0.1403 | 7.6807 |

ผลรวมล่าสุดชี้ว่า `h2l-bm25` เป็นกลยุทธ์ที่ได้ nDCG@5, P@5 และ F1@5 สูงสุด ขณะที่ `h2l-hybrid` ได้ MAP และ MRR สูงสุด แต่มีต้นทุนเวลาเฉลี่ยต่อเคสมากที่สุดในกลุ่มที่รันครบ ระบบ baseline `bm25_only` ยังคงเร็วที่สุดอย่างชัดเจน

### 4.3.2 การเปรียบเทียบแบบ paired ระหว่าง baseline และ H2L

**ตารางที่ 4.4 ผลเปรียบเทียบแบบคู่ตาม Q1 readiness report**

| คู่เปรียบเทียบ | Metric | Baseline | H2L | Delta | p-value | Verdict |
|:---|:---|---:|---:|---:|---:|:---|
| `bm25_only` vs `h2l-bm25` | MAP | 0.2196 | 0.2289 | +0.0093 | 0.9612 | practically_tied |
| `bm25_only` vs `h2l-bm25` | MRR | 0.2697 | 0.2687 | -0.0010 | 0.4061 | practically_tied |
| `bm25_only` vs `h2l-bm25` | nDCG@5 | 0.2079 | 0.2437 | +0.0359 | 0.0131 | supported |
| `naive_rag` vs `h2l-naive_rag` | MAP | 0.2003 | 0.1936 | -0.0067 | 0.1330 | practically_tied |
| `naive_rag` vs `h2l-naive_rag` | MRR | 0.2635 | 0.2703 | +0.0068 | 0.6002 | practically_tied |
| `naive_rag` vs `h2l-naive_rag` | nDCG@5 | 0.2034 | 0.1962 | -0.0072 | 0.1156 | practically_tied |
| `hyde` vs `h2l-hyde` | MAP | 0.1113 | 0.1479 | +0.0366 | 0.1443 | trend_only |
| `hyde` vs `h2l-hyde` | MRR | 0.1224 | 0.1697 | +0.0473 | 0.0800 | trend_only |
| `hyde` vs `h2l-hyde` | nDCG@5 | 0.1120 | 0.1405 | +0.0284 | 0.2894 | trend_only |
| `basic` vs `h2l-hybrid` | MAP | 0.2250 | 0.2362 | +0.0112 | 0.2668 | trend_only |
| `basic` vs `h2l-hybrid` | MRR | 0.2710 | 0.2893 | +0.0183 | 0.1230 | trend_only |
| `basic` vs `h2l-hybrid` | nDCG@5 | 0.2270 | 0.2290 | +0.0019 | 0.8590 | practically_tied |

ผล paired comparison สรุปได้ว่า หลักฐานที่ถึงระดับ `supported` มี 1 รายการ คือ H2L-BM25 เพิ่ม nDCG@5 เหนือ BM25 อย่างมีนัยสำคัญ ส่วน `hyde` และ `h2l-hybrid` มีทิศทางบวกหลาย metric แต่ยังเป็น `trend_only` เพราะค่า p-value ยังไม่ต่ำกว่า 0.05 ใน test split ปัจจุบัน ส่วน `naive_rag` กับ `h2l-naive_rag` อยู่ในระดับ practically tied

### 4.3.3 การตีความผลเชิง Q1

ผล retrieval ปัจจุบันยังไม่ควรสรุปว่า H2L เหนือกว่า baseline โดยรวมทุกกรณี ข้อสรุปที่ปลอดภัยกว่าและสอดคล้องกับหลักฐานคือ:

1. H2L ให้ผลดีชัดที่สุดเมื่อครอบบน BM25 ใน metric nDCG@5
2. H2L-HyDE และ H2L-Hybrid มีแนวโน้มดีขึ้นใน MAP/MRR แต่ยังไม่ significant
3. H2L มีต้นทุนเวลาเพิ่มขึ้น โดยเฉพาะ backbone ที่ใช้ HyDE หรือ hybrid retrieval
4. ผลด้าน retrieval ranking ควรอภิปรายคู่กับผลด้าน polarity/safety เพราะเป็นคนละมิติของคุณภาพระบบ

---

## 4.4 V6 Component Ablation

เพื่อทดสอบองค์ประกอบของ H2L V6 ผู้วิจัยรัน smoke ablation บน sample ขนาดเล็กจำนวน 5 เคส ครอบคลุม 8 variants และได้ผลลัพธ์รวม 40 แถวใน `ablation_results/v6_component_latest/rq6_results.csv`

**ตารางที่ 4.5 ผล smoke ablation ของ V6 components**

| Variant | MAP | MRR | nDCG@5 |
|:---|---:|---:|---:|
| Full V6 | 0.3110 | 0.4000 | 0.1733 |
| Product Feature Mode | 0.3110 | 0.4000 | 0.1733 |
| w/o Adaptive Alpha | 0.3110 | 0.4000 | 0.1733 |
| w/o Bayesian Prior | 0.3110 | 0.4000 | 0.1733 |
| w/o IDF Specificity | 0.3110 | 0.4000 | 0.1733 |
| w/o KL Penalty | 0.3110 | 0.4000 | 0.1733 |
| w/o Margin Activation | 0.3110 | 0.4000 | 0.1733 |
| w/o Negation Gate | 0.3110 | 0.4000 | 0.1733 |

ผลนี้มีประโยชน์ในฐานะ sanity check ว่า ablation runner สามารถรัน retrieval pipeline จริงได้ครบทุก variant แต่ยังไม่เพียงพอสำหรับ claim เชิง causal ว่าองค์ประกอบใดของ V6 สำคัญกว่าองค์ประกอบใด เพราะทุก variant ให้ค่าเท่ากันใน sample นี้ ข้อสรุปเชิง Q1 คือ ต้องรัน ablation บน sample ที่ใหญ่ขึ้นและตรวจว่าแต่ละ toggle เปลี่ยน live scoring path จริง ก่อนนำผลไปใช้เป็นหลักฐาน component-level

---

## 4.5 Blind Expert Evaluation

งานรุ่นล่าสุดเพิ่ม blind expert evaluation packet แล้วที่ `human_evaluation/blind_packet_latest/` ประกอบด้วย

- `evaluation_form.csv` สำหรับส่งให้ผู้เชี่ยวชาญให้คะแนน
- `evaluation_rubric.md` สำหรับเกณฑ์การให้คะแนน
- `evaluation_cases.json` สำหรับ metadata ของเคสที่สุ่มมา
- `blind_mapping.hidden.json` สำหรับ mapping ระหว่างระบบจริงกับ label ลับ

การประเมินนี้ยังไม่ถือว่าเสร็จสมบูรณ์จนกว่าจะมีผู้เชี่ยวชาญอย่างน้อย 3 คนให้คะแนนและนำผลมาวิเคราะห์ inter-rater agreement กับ paired comparison ระหว่างระบบ ดังนั้นในบทนี้จึงรายงานสถานะว่า **เตรียม protocol และ packet แล้ว แต่ยังรอคะแนนผู้เชี่ยวชาญจริง** ไม่ควรรายงานเป็นผลรับรองด้าน usability หรือ clinical relevance จนกว่าข้อมูลส่วนนี้จะครบ

---

## 4.6 สรุปความพร้อมต่อการส่ง Q1

`q1_readiness_report.md` สรุปผลปัจจุบันดังนี้

| ประเภทข้อสรุป | จำนวน metric comparisons |
|:---|---:|
| Supported H2L comparisons | 1 |
| Trend-only comparisons | 5 |
| Practical ties | 6 |
| Baseline-supported comparisons | 0 |

ดังนั้น สถานะปัจจุบันของงานคือ **มีหลักฐานเชิงบวกบางส่วนและมี methodology ที่แข็งแรงขึ้นหลังแก้ leakage แต่ยังไม่ควร claim broad superiority** ข้อความสรุปที่เหมาะสมสำหรับบทความหรือวิทยานิพนธ์คือ:

> H2L provides statistically supported improvement for BM25 on nDCG@5 and shows trend-level gains for HyDE and hybrid retrieval on selected ranking metrics, while also contributing an interpretable polarity-gating mechanism that improves safety-related negation handling. However, broader superiority claims require completed blind expert evaluation, larger component ablation, and ideally an external holdout set.

ประเด็นที่พร้อมใช้เป็นจุดแข็งของงาน ได้แก่ family-level leakage-safe split, audit trail ของ artifact, paired evaluation, polarity safety metric และ blind evaluation protocol ส่วนประเด็นที่ยังต้องทำก่อนยื่น Q1 อย่างมั่นใจ ได้แก่ เก็บคะแนน blind expert จริง, rerun V6 ablation บน sample ใหญ่กว่า smoke set, และเพิ่ม external holdout หรืออย่างน้อยแยก generated stress-test cases ออกจาก claim หลักอย่างชัดเจน
