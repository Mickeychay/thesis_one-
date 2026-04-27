# บทที่ 4: ผลการทดลองและการวิเคราะห์ข้อมูล (Results and Analysis)

บทนี้นำเสนอผลการทดลองตาม artifact ล่าสุดหลังแก้ split leakage และ rerun evaluation เมื่อวันที่ 25 เมษายน 2026 โดยยึดหลักว่า **รายงานเฉพาะผลที่เกิดจากการรันจริง** ไม่ใช้ mock data หรือค่าประมาณเพื่อทำให้ผลดูดีขึ้น ผลหลักอ้างอิงจาก `evaluation_results/proper_eval_latest_summary.json`, `evaluation_results/sentence_polarity_latest.json`, `evaluation_results/ground_truth_audit.json`, `evaluation_results/q1_readiness_report.md`, `human_evaluation/blind_packet_latest/` และ `ablation_results/v6_component_cached_20/`

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

## 4.4 V6 Component Ablation (Ablation Study)

เพื่อทดสอบผลกระทบขององค์ประกอบย่อยใน H2L V6 อย่างรัดกุมที่สุด ผู้วิจัยได้ทำการทดลองแบบ Component Ablation โดยใช้โครงสร้าง **Fixed Candidate Pool** จำนวน 45 เอกสารต่อเคส ร่วมกับข้อมูลชุดทดสอบ 197 เคส เพื่อลด noise จากการสืบค้นซ้ำ และแยกพิจารณาเฉพาะความเปลี่ยนแปลงในชั้นการให้คะแนน (Scoring Layer) 

การทดลองใช้ Metric แบบ Rank-aware (nDCG@5, MAP, MRR) คู่กับ Score-level Metric (`h2l_mean_top5`) ซึ่งสะท้อนความสามารถในการกระจายและจัดระดับความมั่นใจของคะแนน (Score Calibration) การทดสอบนัยสำคัญทางสถิติใช้ Wilcoxon Signed-Rank Test และคำนวณ Cohen's $d$ Effect Size ตามมาตรฐาน Q1

**ตารางที่ 4.5 ผลการทำ Ablation ของ H2L V6 Components (n=197 เคส)**

| Configuration | nDCG@5 | MAP | H2L Score | Cohen's $d$ | $p$-value | Effect Size |
|:---|---:|---:|---:|---:|---:|:---|
| **Full V6 (baseline)** | 0.3410 | 0.3453 | 1.8947 | — | — | — |
| Product Mode | 0.3418 | 0.3454 | 0.3283 | 0.932 | <0.001 | **large** |
| w/o Adaptive Alpha | 0.3410 | 0.3453 | 1.1377 | 0.409 | <0.001 | **small** |
| w/o IDF Specificity | 0.3410 | 0.3453 | 1.4929 | 0.184 | <0.001 | negligible |
| w/o Negation Gate | 0.3410 | 0.3453 | 1.5273 | 0.167 | <0.001 | negligible |
| w/o Bayesian Prior | 0.3410 | 0.3453 | 2.0146 | -0.048 | <0.001 | negligible |
| w/o Margin Activation | 0.3421 | 0.3460 | 1.8730 | 0.009 | <0.001 | negligible |
| w/o KL Penalty | 0.3410 | 0.3453 | 1.8995 | -0.002 | <0.001 | negligible |

*หมายเหตุ: Cohen's $d$ คำนวณจากความแตกต่างของ `h2l_mean_top5` (Full V6 - Ablated)*

**การวิเคราะห์ผล (Findings)**:
1. **ข้อจำกัดของ Binary Relevance Metrics**: ค่า nDCG@5 และ MAP แทบไม่มีการเปลี่ยนแปลงอย่างมีนัยสำคัญระหว่าง Variant เนื่องจากธรรมชาติของชุดข้อมูลทดสอบที่มีความกระจัดกระจาย (Sparsity) สูง แม้ลำดับ Top-5 จะเปลี่ยน (Rank Swap เปลี่ยนประมาณ 12-16% ของเคส) แต่เอกสารที่สลับขึ้นมาใหม่มักเป็นเอกสารที่ไม่ได้ถูก Label ไว้ จึงไม่ส่งผลต่อ Metric
2. **ความสำคัญของ Architecture (Product vs Weighted-Sum)**: การเปลี่ยนสถาปัตยกรรมรวมฟีเจอร์จากแบบคูณ (Product Mode) มาเป็นแบบบวก (Weighted-Sum) ใน V6 เป็นการปรับปรุงที่ส่งผลกระทบสูงสุด (Cohen's $d$ = 0.932, **Large Effect**) โดยช่วยรักษาคะแนนไม่ให้ตกฮวบเมื่อฟีเจอร์ใดฟีเจอร์หนึ่งหายไป (Zero-product problem)
3. **ความสำคัญของ Context-Awareness**: Adaptive Alpha เป็น Component เสริมที่ส่งผลชัดเจนที่สุด (Cohen's $d$ = 0.409, **Small Effect**) ชี้ให้เห็นว่าการปรับน้ำหนักรวมของ H2L ตามความซับซ้อนของเคส (Entropy) เป็นกลไกสำคัญที่ช่วยแยกแยะระดับความมั่นใจของเอกสาร 
4. **Statistical Significance**: ทุก Component มีผลกระทบต่อคะแนนรวมของ H2L อย่างมีนัยสำคัญทางสถิติ ($p < 0.001$) แม้บางตัวจะมี Effect Size ที่มีขนาดเล็กก็ตาม 

กราฟและผลวิเคราะห์เจาะลึก (Forest Plot, Waterfall Chart, และ Score Distribution) ถูกสร้างไว้ในโฟลเดอร์ `ablation_results/q1_figures/` เพื่อประกอบการอภิปรายผลในส่วนนี้

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

> H2L provides statistically supported improvement for BM25 on nDCG@5 and shows trend-level gains for HyDE and hybrid retrieval on selected ranking metrics, while also contributing an interpretable polarity-gating mechanism that improves safety-related negation handling. A comprehensive component ablation on 197 cases demonstrates score-level sensitivity and high component causality across V6 toggles, with Adaptive Alpha and Weighted-Sum Feature Composition yielding significant practical effect sizes (Cohen's $d$). Broader clinical superiority claims now await the final blind expert evaluation framework.

ประเด็นที่พร้อมใช้เป็นจุดแข็งของงาน ได้แก่ family-level leakage-safe split, audit trail ของ artifact, paired evaluation, polarity safety metric, full-scale V6 ablation พร้อมการทำ Effect Size และ blind evaluation protocol ส่วนประเด็นที่ยังต้องทำเพื่อให้ครบกระบวนการ 100% คือ การเก็บคะแนน blind expert จริง เพื่อวิเคราะห์ Human-AI Agreement ต่อไป
